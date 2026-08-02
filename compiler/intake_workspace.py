import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from compiler.pdf_reader import read_pdf_pages
from compiler.cleaner import clean_text_generalized
from compiler.detector import detect_structure
from compiler.source_parser import parse_source_questions
from compiler.diagnostics import DiagnosticSeverity
from compiler.normalizer import normalize_questions
from compiler.validator import validate_questions
from compiler.record_match import RecordMatchError, match_ordered_records
from compiler.intake_compare import IntakeComparisonError, compare_intake_candidate
from compiler.intake_attribution import IntakeAttributionError, attribute_drift
from compiler.candidate import build_candidate


class IntakeWorkspaceError(ValueError):
    """Raised when an isolated intake run cannot proceed safely."""


@dataclass(frozen=True)
class IntakeExtractionResult:
    run_id: str
    run_directory: Path
    raw_artifact: Path
    extracted_characters: int
    staged_source_deleted: bool


@dataclass(frozen=True)
class IntakeCleaningResult:
    run_id: str
    run_directory: Path
    cleaned_artifact: Path
    raw_characters: int
    cleaned_characters: int
    chapter_count: int
    question_count: int


@dataclass(frozen=True)
class IntakeParsingResult:
    run_id: str
    run_directory: Path
    questions_artifact: Path
    parsed_questions: int
    question_types: dict[str, int]
    missing_chapter: int
    missing_answers: int
    choice_sequence_findings: int


@dataclass(frozen=True)
class IntakeValidationResult:
    run_id: str
    run_directory: Path
    normalized_artifact: Path
    diagnostics_artifact: Path
    normalized_questions: int
    eligible_questions: int
    skipped_questions: int
    diagnostics_by_severity: dict[str, int]
    diagnostics_by_code: dict[str, int]


@dataclass(frozen=True)
class IntakeMatchResult:
    run_id: str
    report_artifact: Path
    canonical_matched: int
    candidate_matched: int
    parsed_only: int
    target_only: int


@dataclass(frozen=True)
class IntakeCandidateResult:
    run_id: str
    candidate_artifact: Path
    manifest_artifact: Path
    question_count: int
    boundary_findings: int
    promotion_ready: bool


@dataclass(frozen=True)
class IntakeComparisonResult:
    run_id: str
    report_artifact: Path
    evaluated_candidate_artifact: Path
    repair_lesson_counts: dict[str, int]
    known_blockers: int
    isolated_blockers: int


@dataclass(frozen=True)
class IntakeAttributionResult:
    run_id: str
    report_artifact: Path
    field_category_counts: dict
    blocker_attribution: dict


def _write_manifest(run_directory: Path, value: dict) -> None:
    path = run_directory / "run-status.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _new_run_directory(workspace_root: Path) -> tuple[str, Path]:
    workspace_root.mkdir(parents=True, exist_ok=True)
    if workspace_root.is_symlink():
        raise IntakeWorkspaceError("Intake workspace root cannot be a symbolic link")
    run_id = "run-" + uuid.uuid4().hex
    run_directory = workspace_root / run_id
    run_directory.mkdir(mode=0o700)
    (run_directory / "incoming").mkdir(mode=0o700)
    (run_directory / "artifacts").mkdir(mode=0o700)
    return run_id, run_directory


def _delete_staged_source(staged_source: Path, run_directory: Path) -> None:
    expected_parent = (run_directory / "incoming").resolve(strict=True)
    if staged_source.parent.resolve(strict=True) != expected_parent:
        raise IntakeWorkspaceError("Staged source is outside the run incoming directory")
    if staged_source.name != "source.pdf" or staged_source.is_symlink():
        raise IntakeWorkspaceError("Staged source is not the expected disposable copy")
    staged_source.unlink()


def extract_pdf_in_isolated_run(
    source_path: str | Path,
    *,
    workspace_root: str | Path = Path("output/intake-runs"),
) -> IntakeExtractionResult:
    """Extract a PDF from a disposable copy without modifying the original."""
    source = Path(source_path)
    if not source.is_file() or source.is_symlink():
        raise IntakeWorkspaceError("Source must be an existing regular file")
    if source.suffix.lower() != ".pdf":
        raise IntakeWorkspaceError("The first intake adapter accepts PDF files only")

    run_id, run_directory = _new_run_directory(Path(workspace_root))
    staged_source = run_directory / "incoming" / "source.pdf"
    manifest = {
        "format": "prepflow_intake_run_status",
        "version": "1.0",
        "run_id": run_id,
        "source_type": "pdf",
        "stage": "staging",
        "status": "running",
        "staged_source_present": False,
        "raw_artifact_present": False,
    }
    _write_manifest(run_directory, manifest)

    try:
        with source.open("rb") as source_file, staged_source.open("xb") as staged_file:
            shutil.copyfileobj(source_file, staged_file)
            staged_file.flush()
            os.fsync(staged_file.fileno())
        manifest.update(stage="extraction", staged_source_present=True)
        _write_manifest(run_directory, manifest)

        pages = read_pdf_pages(staged_source)
        raw_text = "\n\f\n".join(pages)
        raw_artifact = run_directory / "artifacts" / "01_raw.txt"
        raw_artifact.write_text(raw_text, encoding="utf-8")
        manifest.update(raw_artifact_present=True)
        _write_manifest(run_directory, manifest)

        _delete_staged_source(staged_source, run_directory)
        manifest.update(
            stage="extraction_complete",
            status="success",
            staged_source_present=False,
            extracted_characters=len(raw_text),
            extracted_pages=len(pages),
        )
        _write_manifest(run_directory, manifest)
    except Exception as error:
        manifest.update(
            status="failed",
            failure_stage=manifest["stage"],
            failure_type=type(error).__name__,
            staged_source_present=staged_source.is_file(),
        )
        _write_manifest(run_directory, manifest)
        if isinstance(error, IntakeWorkspaceError):
            raise
        raise IntakeWorkspaceError(
            f"Intake extraction failed in isolated run {run_id}"
        ) from error

    return IntakeExtractionResult(
        run_id=run_id,
        run_directory=run_directory,
        raw_artifact=raw_artifact,
        extracted_characters=len(raw_text),
        staged_source_deleted=not staged_source.exists(),
    )


def clean_isolated_run(run_directory: str | Path) -> IntakeCleaningResult:
    """Clean one verified extraction with the generalized default only."""
    run = Path(run_directory)
    if not run.is_dir() or run.is_symlink():
        raise IntakeWorkspaceError("Run directory must be an existing real directory")
    status_path = run / "run-status.json"
    raw_artifact = run / "artifacts" / "01_raw.txt"
    if raw_artifact.is_symlink() or not raw_artifact.is_file():
        raise IntakeWorkspaceError("Run is missing its contained raw artifact")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Run status is missing or malformed") from error
    if (
        status.get("format") != "prepflow_intake_run_status"
        or status.get("run_id") != run.name
        or status.get("status") != "success"
        or status.get("stage") not in {"extraction_complete", "cleaning_complete"}
    ):
        raise IntakeWorkspaceError("Run is not ready for generalized cleaning")

    raw_text = raw_artifact.read_text(encoding="utf-8")
    cleaned_text = clean_text_generalized(raw_text)
    cleaned_artifact = run / "artifacts" / "02_clean.txt"
    temporary = cleaned_artifact.with_suffix(".txt.tmp")
    temporary.write_text(cleaned_text, encoding="utf-8")
    temporary.replace(cleaned_artifact)
    detection = detect_structure(cleaned_text)
    status.update(
        stage="cleaning_complete",
        generalized_cleaning="source_neutral_guarded_page_noise_v2",
        cleaned_artifact_present=True,
        raw_characters=len(raw_text),
        cleaned_characters=len(cleaned_text),
        detected_chapters=detection.chapter_count,
        detected_questions=detection.question_count,
    )
    _write_manifest(run, status)
    return IntakeCleaningResult(
        run_id=run.name,
        run_directory=run,
        cleaned_artifact=cleaned_artifact,
        raw_characters=len(raw_text),
        cleaned_characters=len(cleaned_text),
        chapter_count=detection.chapter_count,
        question_count=detection.question_count,
    )


def parse_isolated_run(run_directory: str | Path) -> IntakeParsingResult:
    """Parse generalized-cleaned text without broad missing-A recovery."""
    run = Path(run_directory)
    if not run.is_dir() or run.is_symlink():
        raise IntakeWorkspaceError("Run directory must be an existing real directory")
    status_path = run / "run-status.json"
    cleaned_artifact = run / "artifacts" / "02_clean.txt"
    if cleaned_artifact.is_symlink() or not cleaned_artifact.is_file():
        raise IntakeWorkspaceError("Run is missing its contained cleaned artifact")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Run status is missing or malformed") from error
    if (
        status.get("format") != "prepflow_intake_run_status"
        or status.get("run_id") != run.name
        or status.get("status") != "success"
        or status.get("stage") not in {"cleaning_complete", "parsing_complete"}
    ):
        raise IntakeWorkspaceError("Run is not ready for isolated parsing")

    cleaned_text = cleaned_artifact.read_text(encoding="utf-8")
    questions = parse_source_questions(
        cleaned_text,
        allow_missing_a_recovery=False,
    )
    questions_artifact = run / "artifacts" / "03_questions.json"
    temporary = questions_artifact.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(questions, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(questions_artifact)

    question_types: dict[str, int] = {}
    missing_chapter = 0
    missing_answers = 0
    choice_sequence_findings = 0
    for question in questions:
        question_type = str(question.get("question_type") or "unknown")
        question_types[question_type] = question_types.get(question_type, 0) + 1
        if not question.get("chapter"):
            missing_chapter += 1
        if not question.get("correct_answers"):
            missing_answers += 1
        choices = question.get("choices")
        if isinstance(choices, list) and choices:
            labels = [str(choice.get("label") or "").upper() for choice in choices]
            expected = [chr(ord("A") + index) for index in range(len(labels))]
            if labels != expected:
                choice_sequence_findings += 1

    status.update(
        stage="parsing_complete",
        parser="source_parser_without_broad_missing_a_recovery",
        questions_artifact_present=True,
        parsed_questions=len(questions),
        parsed_question_types=dict(sorted(question_types.items())),
        missing_chapter=missing_chapter,
        missing_answers=missing_answers,
        choice_sequence_findings=choice_sequence_findings,
    )
    _write_manifest(run, status)
    return IntakeParsingResult(
        run_id=run.name,
        run_directory=run,
        questions_artifact=questions_artifact,
        parsed_questions=len(questions),
        question_types=dict(sorted(question_types.items())),
        missing_chapter=missing_chapter,
        missing_answers=missing_answers,
        choice_sequence_findings=choice_sequence_findings,
    )


def _diagnostic_code(message: str) -> str:
    if message.startswith("duplicate question number"):
        return "duplicate_question_number"
    if message.startswith("duplicate question text"):
        return "duplicate_question_text"
    return message.replace(" ", "_")


def validate_isolated_run(run_directory: str | Path) -> IntakeValidationResult:
    """Normalize and validate parsed records without building a Pack."""
    run = Path(run_directory)
    if not run.is_dir() or run.is_symlink():
        raise IntakeWorkspaceError("Run directory must be an existing real directory")
    status_path = run / "run-status.json"
    questions_artifact = run / "artifacts" / "03_questions.json"
    if questions_artifact.is_symlink() or not questions_artifact.is_file():
        raise IntakeWorkspaceError("Run is missing its contained questions artifact")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        questions = json.loads(questions_artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Run status or questions are malformed") from error
    if (
        status.get("format") != "prepflow_intake_run_status"
        or status.get("run_id") != run.name
        or status.get("status") != "success"
        or status.get("stage") not in {"parsing_complete", "validation_complete"}
        or not isinstance(questions, list)
    ):
        raise IntakeWorkspaceError("Run is not ready for isolated validation")

    normalized = normalize_questions(questions)
    diagnostics = validate_questions(normalized)
    normalized_artifact = run / "artifacts" / "04_normalized.json"
    temporary = normalized_artifact.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(normalized_artifact)

    severity_counts: dict[str, int] = {}
    code_counts: dict[str, int] = {}
    sanitized = []
    blocked_labels = set()
    for diagnostic in diagnostics:
        severity = diagnostic.severity.value
        code = _diagnostic_code(diagnostic.message)
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        code_counts[code] = code_counts.get(code, 0) + 1
        sanitized.append(
            {"severity": severity, "label": diagnostic.label, "code": code}
        )
        if diagnostic.severity == DiagnosticSeverity.RECOVERABLE:
            blocked_labels.add(diagnostic.label)

    eligible = [
        question
        for question in normalized
        if (
            f"Chapter {question.get('chapter', 'Unknown')}, "
            f"Question {question.get('question_number', 'Unknown')}"
        )
        not in blocked_labels
    ]
    diagnostics_artifact = run / "artifacts" / "05_validation.json"
    temporary = diagnostics_artifact.with_suffix(".json.tmp")
    validation_report = {
        "format": "prepflow_intake_validation",
        "version": "1.0",
        "run_id": run.name,
        "normalized_questions": len(normalized),
        "eligible_questions": len(eligible),
        "skipped_questions": len(normalized) - len(eligible),
        "diagnostics_by_severity": dict(sorted(severity_counts.items())),
        "diagnostics_by_code": dict(sorted(code_counts.items())),
        "diagnostics": sorted(
            sanitized,
            key=lambda item: (item["label"], item["severity"], item["code"]),
        ),
    }
    temporary.write_text(json.dumps(validation_report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(diagnostics_artifact)
    status.update(
        stage="validation_complete",
        normalized_artifact_present=True,
        validation_artifact_present=True,
        normalized_questions=len(normalized),
        eligible_questions=len(eligible),
        skipped_questions=len(normalized) - len(eligible),
        diagnostics_by_severity=dict(sorted(severity_counts.items())),
        diagnostics_by_code=dict(sorted(code_counts.items())),
    )
    _write_manifest(run, status)
    return IntakeValidationResult(
        run_id=run.name,
        run_directory=run,
        normalized_artifact=normalized_artifact,
        diagnostics_artifact=diagnostics_artifact,
        normalized_questions=len(normalized),
        eligible_questions=len(eligible),
        skipped_questions=len(normalized) - len(eligible),
        diagnostics_by_severity=dict(sorted(severity_counts.items())),
        diagnostics_by_code=dict(sorted(code_counts.items())),
    )


def match_isolated_run(
    run_directory: str | Path,
    *,
    canonical_pack: dict,
    candidate_pack: dict,
) -> IntakeMatchResult:
    """Match normalized records read-only against two protected Pack states."""
    run = Path(run_directory)
    normalized_artifact = run / "artifacts" / "04_normalized.json"
    status_path = run / "run-status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        normalized = json.loads(normalized_artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Run status or normalized records are malformed") from error
    if (
        not run.is_dir()
        or run.is_symlink()
        or normalized_artifact.is_symlink()
        or not isinstance(normalized, list)
        or status.get("run_id") != run.name
        or status.get("stage") not in {"validation_complete", "matching_complete"}
    ):
        raise IntakeWorkspaceError("Run is not ready for record matching")
    try:
        canonical = match_ordered_records(normalized, canonical_pack)
        candidate = match_ordered_records(normalized, candidate_pack)
    except RecordMatchError as error:
        raise IntakeWorkspaceError(str(error)) from error
    canonical_ids = [item["target_question_id"] for item in canonical["matches"]]
    candidate_ids = [item["target_question_id"] for item in candidate["matches"]]
    if canonical_ids != candidate_ids:
        raise IntakeWorkspaceError("Canonical and candidate record alignment differs")

    report = {
        "format": "prepflow_intake_record_match",
        "version": "1.0",
        "run_id": run.name,
        "canonical": canonical,
        "candidate_24": candidate,
    }
    report_artifact = run / "artifacts" / "06_record_match.json"
    temporary = report_artifact.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_artifact)
    status.update(
        stage="matching_complete",
        record_match_artifact_present=True,
        canonical_matched=canonical["matched_count"],
        candidate_24_matched=candidate["matched_count"],
        parsed_only=canonical["parsed_only_count"],
        target_only=canonical["target_only_count"],
    )
    _write_manifest(run, status)
    return IntakeMatchResult(
        run_id=run.name,
        report_artifact=report_artifact,
        canonical_matched=canonical["matched_count"],
        candidate_matched=candidate["matched_count"],
        parsed_only=canonical["parsed_only_count"],
        target_only=canonical["target_only_count"],
    )


def build_isolated_comparison_candidate(
    run_directory: str | Path,
    *,
    canonical_pack: dict,
) -> IntakeCandidateResult:
    """Build a non-promotable candidate from verified matched records only."""
    run = Path(run_directory)
    artifacts = run / "artifacts"
    normalized_path = artifacts / "04_normalized.json"
    validation_path = artifacts / "05_validation.json"
    match_path = artifacts / "06_record_match.json"
    status_path = run / "run-status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        match_report = json.loads(match_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Run candidate inputs are missing or malformed") from error
    if (
        not run.is_dir()
        or run.is_symlink()
        or any(path.is_symlink() for path in (normalized_path, validation_path, match_path))
        or status.get("run_id") != run.name
        or status.get("stage") not in {"matching_complete", "candidate_complete"}
        or not isinstance(normalized, list)
    ):
        raise IntakeWorkspaceError("Run is not ready for isolated candidate construction")
    alignment = match_report.get("canonical")
    if not isinstance(alignment, dict) or alignment.get("target_only_count") != 0:
        raise IntakeWorkspaceError("Canonical alignment is incomplete")
    target_questions = canonical_pack.get("questions")
    if not isinstance(target_questions, list):
        raise IntakeWorkspaceError("Canonical Pack questions must be a list")
    target_ids = [question.get("id") for question in target_questions]
    matched = alignment.get("matches")
    if not isinstance(matched, list) or len(matched) != len(target_ids):
        raise IntakeWorkspaceError("Matched record count does not equal canonical count")
    by_target = {item.get("target_question_id"): item for item in matched}
    if set(by_target) != set(target_ids) or len(by_target) != len(matched):
        raise IntakeWorkspaceError("Matched IDs do not exactly cover canonical IDs")

    candidate_questions = []
    for target_id in target_ids:
        item = by_target[target_id]
        index = item.get("parsed_index")
        if not isinstance(index, int) or not 0 <= index < len(normalized):
            raise IntakeWorkspaceError("Match contains an invalid parsed index")
        question = normalized[index]
        question_type = str(question.get("question_type") or "")
        candidate_questions.append(
            {
                "id": target_id,
                "chapter": question.get("chapter"),
                "chapter_title": question.get("chapter_title") or "",
                "type": "mc" if question_type == "multiple_choice" else question_type,
                "stem": question.get("stem") or "",
                "choices": question.get("choices") or [],
                "correct_answers": question.get("correct_answers") or [],
                "rationale": question.get("rationale") or "",
            }
        )
    candidate = {
        "format": "prepflow_pack",
        "version": canonical_pack.get("version", "1.0"),
        "pack_id": canonical_pack.get("pack_id"),
        "title": canonical_pack.get("title"),
        "questions": candidate_questions,
    }
    candidate_artifact = artifacts / "07_candidate.prepflow.json"
    temporary = candidate_artifact.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(candidate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(candidate_artifact)

    boundary_findings = alignment.get("parsed_only") or []
    unresolved_diagnostics = validation.get("diagnostics") or []
    manifest = {
        "format": "prepflow_intake_candidate_manifest",
        "version": "1.0",
        "run_id": run.name,
        "pack_id": candidate.get("pack_id"),
        "question_count": len(candidate_questions),
        "stable_ids_mapped": True,
        "repairs_applied": 0,
        "boundary_findings": boundary_findings,
        "validation_findings": unresolved_diagnostics,
        "promotion_ready": False,
        "promotion_blockers": [
            "unresolved_boundary_findings",
            "unresolved_validation_findings",
            "comparison_not_completed",
            "explicit_approval_required",
        ],
    }
    manifest_artifact = artifacts / "07_candidate-manifest.json"
    temporary = manifest_artifact.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_artifact)
    status.update(
        stage="candidate_complete",
        isolated_candidate_present=True,
        isolated_candidate_questions=len(candidate_questions),
        boundary_findings=len(boundary_findings),
        repairs_applied=0,
        promotion_ready=False,
    )
    _write_manifest(run, status)
    return IntakeCandidateResult(
        run_id=run.name,
        candidate_artifact=candidate_artifact,
        manifest_artifact=manifest_artifact,
        question_count=len(candidate_questions),
        boundary_findings=len(boundary_findings),
        promotion_ready=False,
    )


def compare_isolated_candidate(
    run_directory: str | Path,
    *,
    canonical_pack: dict,
    candidate_24_pack: dict,
    repair_records: list,
    known_manifest: dict,
) -> IntakeComparisonResult:
    run = Path(run_directory)
    artifacts = run / "artifacts"
    candidate_path = artifacts / "07_candidate.prepflow.json"
    status_path = run / "run-status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        isolated = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Isolated candidate is missing or malformed") from error
    known_blockers = known_manifest.get("promotion_blockers")
    if (
        not run.is_dir()
        or run.is_symlink()
        or candidate_path.is_symlink()
        or status.get("run_id") != run.name
        or status.get("stage") not in {"candidate_complete", "comparison_complete"}
        or not isinstance(known_blockers, list)
    ):
        raise IntakeWorkspaceError("Run is not ready for isolated comparison")
    try:
        evaluated, report = compare_intake_candidate(
            isolated,
            canonical_pack,
            candidate_24_pack,
            repair_records,
            known_blockers,
        )
    except IntakeComparisonError as error:
        raise IntakeWorkspaceError(str(error)) from error
    evaluated_path = artifacts / "08_evaluated-candidate.prepflow.json"
    temporary = evaluated_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(evaluated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(evaluated_path)
    report_path = artifacts / "08_comparison.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    status.update(
        stage="comparison_complete",
        comparison_artifact_present=True,
        evaluated_candidate_present=True,
        isolated_blockers=report["blockers"]["isolated_count"],
        known_blockers=report["blockers"]["known_count"],
        repair_lesson_counts=report["repair_lesson_counts"],
        promotion_ready=False,
    )
    _write_manifest(run, status)
    return IntakeComparisonResult(
        run_id=run.name,
        report_artifact=report_path,
        evaluated_candidate_artifact=evaluated_path,
        repair_lesson_counts=report["repair_lesson_counts"],
        known_blockers=report["blockers"]["known_count"],
        isolated_blockers=report["blockers"]["isolated_count"],
    )


def attribute_isolated_drift(
    run_directory: str | Path,
    *,
    canonical_pack: dict,
    candidate_24_pack: dict,
    known_manifest: dict,
) -> IntakeAttributionResult:
    """Use the legacy cleaner only as an in-memory diagnostic baseline."""
    run = Path(run_directory)
    artifacts = run / "artifacts"
    try:
        status = json.loads((run / "run-status.json").read_text(encoding="utf-8"))
        raw_text = (artifacts / "01_raw.txt").read_text(encoding="utf-8")
        match_report = json.loads((artifacts / "06_record_match.json").read_text(encoding="utf-8"))
        isolated = json.loads((artifacts / "08_evaluated-candidate.prepflow.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeWorkspaceError("Attribution inputs are missing or malformed") from error
    if status.get("stage") not in {"comparison_complete", "attribution_complete"}:
        raise IntakeWorkspaceError("Run is not ready for drift attribution")

    from compiler.cleaner import clean_text

    legacy_records = normalize_questions(
        parse_source_questions(clean_text(raw_text), allow_missing_a_recovery=False)
    )
    alignment = match_report.get("canonical", {}).get("matches")
    if not isinstance(alignment, list):
        raise IntakeWorkspaceError("Canonical alignment is missing")
    by_id = {item["target_question_id"]: legacy_records[item["parsed_index"]] for item in alignment}
    legacy_pack = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": canonical_pack.get("pack_id"),
        "title": canonical_pack.get("title"),
        "questions": [],
    }
    for target in canonical_pack.get("questions", []):
        record = by_id[target["id"]]
        question_type = record.get("question_type")
        legacy_pack["questions"].append(
            {
                "id": target["id"],
                "chapter": record.get("chapter"),
                "chapter_title": record.get("chapter_title") or "",
                "type": "mc" if question_type == "multiple_choice" else question_type,
                "stem": record.get("stem") or "",
                "choices": record.get("choices") or [],
                "correct_answers": record.get("correct_answers") or [],
                "rationale": record.get("rationale") or "",
            }
        )
    legacy_evaluated = build_candidate(legacy_pack, [])
    isolated_qa = build_candidate(isolated, [])
    try:
        report = attribute_drift(
            isolated,
            legacy_evaluated.candidate,
            canonical_pack,
            candidate_24_pack,
            isolated_qa.promotion_blockers,
            legacy_evaluated.promotion_blockers,
            known_manifest.get("promotion_blockers", []),
        )
    except IntakeAttributionError as error:
        raise IntakeWorkspaceError(str(error)) from error
    report["run_id"] = run.name
    report_path = artifacts / "09_attribution.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    status.update(
        stage="attribution_complete",
        attribution_artifact_present=True,
        legacy_cleaner_used_for_diagnostics_only=True,
        promotion_ready=False,
    )
    _write_manifest(run, status)
    return IntakeAttributionResult(
        run_id=run.name,
        report_artifact=report_path,
        field_category_counts=report["field_category_counts"],
        blocker_attribution=report["blocker_attribution"],
    )
