from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingestion_v2.checkpoint import proposal_fingerprint, read_checkpoint
from ingestion_v2.comparison import ComparisonReport, compare_candidate
from ingestion_v2.comparison_groups import apply_exact_contaminant_group
from ingestion_v2.comparison_categories import (
    apply_category_reference_values,
    categorize_comparison_changes,
)
from ingestion_v2.domain import (
    Candidate, DispositionAction, DomainError, Finding, FindingDisposition,
    Proposal, QuestionRecord, ReviewAction, ReviewDecision, SourceVerification,
)
from ingestion_v2.engine import build_candidate
from ingestion_v2.identity import IdentityReport, match_existing_pack_identity
from ingestion_v2.identity_review import IdentityReviewCase, authorize_reviewed_identity, build_identity_review_cases
from ingestion_v2.pack_bridge import pack_questions_to_domain
from ingestion_v2.parser import ExistingParserAdapter, ParseBatch
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.proposal_adapter import draft_benchmark_answer_proposals, draft_deterministic_proposals
from ingestion_v2.qa_adapter import QaResult, detect_candidate_damage
from ingestion_v2.run_lifecycle import RunLifecycle


@dataclass(frozen=True)
class RecoveredRun:
    lifecycle: RunLifecycle
    parse_batch: ParseBatch
    identity_report: IdentityReport
    identity_cases: tuple[IdentityReviewCase, ...]
    identity_actions: dict[str, dict[str, str]]
    identity_mapping: dict[str, str]
    questions: tuple[QuestionRecord, ...]
    findings: tuple[Finding, ...]
    proposals: tuple[Proposal, ...]
    decisions: tuple[ReviewDecision, ...]
    verifications: tuple[SourceVerification, ...]
    dispositions: tuple[FindingDisposition, ...]
    benchmark: tuple[QuestionRecord, ...]
    qa_result: QaResult
    candidate: Candidate | None
    comparison: ComparisonReport | None
    comparison_group_ids: tuple[str, ...] = ()
    post_group_qa_result: QaResult | None = None
    comparison_category_decisions: tuple[tuple[str, str], ...] = ()


def list_recoverable_runs(workspace_root: Path, protected_pack_ids: set[str]) -> tuple[dict, ...]:
    """Return source-neutral summaries of active runs that have safe checkpoints."""
    root = Path(workspace_root)
    if root.is_symlink() or not root.is_dir():
        return ()
    summaries = []
    for run_directory in root.iterdir():
        if run_directory.is_symlink() or not run_directory.is_dir():
            continue
        try:
            lifecycle = RunLifecycle.open(run_directory)
            manifest = lifecycle.manifest()
            checkpoint = read_checkpoint(run_directory)
            pack_id = checkpoint["target_pack_id"]
            cleaned = run_directory / "artifacts" / "cleaned.txt"
            if (
                manifest.get("status") != "running"
                or manifest.get("stage") in {"created", "staged", "extracted", "cleaned", "completed", "failed", "failed_cleaned"}
                or pack_id not in protected_pack_ids
                or cleaned.is_symlink()
                or not cleaned.is_file()
            ):
                continue
            summaries.append(
                {
                    "run_id": manifest["run_id"],
                    "pack_id": pack_id,
                    "stage": manifest["stage"],
                    "parsed_records": manifest.get("parsed_records", 0),
                    "finding_count": manifest.get("finding_count", 0),
                }
            )
        except (DomainError, OSError):
            continue
    return tuple(sorted(summaries, key=lambda item: item["run_id"]))


def list_completed_runs(workspace_root: Path, protected_pack_ids: set[str]) -> tuple[dict, ...]:
    """Return content-free summaries of successfully cleaned private runs."""
    root = Path(workspace_root)
    if root.is_symlink() or not root.is_dir():
        return ()
    summaries = []
    for run_directory in root.iterdir():
        if run_directory.is_symlink() or not run_directory.is_dir():
            continue
        try:
            manifest = RunLifecycle.open(run_directory).manifest()
            pack_id = manifest.get("identity_target_pack_id")
            artifacts = run_directory / "artifacts"
            if (
                manifest.get("stage") != "completed"
                or manifest.get("status") != "success"
                or manifest.get("source_bearing_artifacts_removed") is not True
                or pack_id not in protected_pack_ids
                or any((artifacts / name).exists() for name in ("raw.txt", "cleaned.txt"))
            ):
                continue
            summaries.append(
                {
                    "run_id": manifest["run_id"],
                    "pack_id": pack_id,
                    "stage": "completed",
                    "parsed_records": manifest.get("parsed_records", 0),
                    "candidate_questions": manifest.get("candidate_question_count", 0),
                    "field_changes": manifest.get("comparison_field_changes", 0),
                }
            )
        except (DomainError, OSError):
            continue
    return tuple(sorted(summaries, key=lambda item: item["run_id"], reverse=True))


def recover_run(run_directory: Path, target_pack: dict) -> RecoveredRun:
    lifecycle = RunLifecycle.open(run_directory)
    manifest = lifecycle.manifest()
    if manifest.get("stage") in {"completed", "failed", "failed_cleaned"}:
        raise DomainError("Only an active source-bearing run can be resumed")
    checkpoint = read_checkpoint(run_directory)
    if checkpoint["target_pack_id"] != target_pack.get("pack_id"):
        raise DomainError("Checkpoint target Pack does not match the selected Pack")
    cleaned_path = Path(run_directory) / "artifacts" / "cleaned.txt"
    if cleaned_path.is_symlink() or not cleaned_path.is_file():
        raise DomainError("Resume requires the controlled cleaned artifact")

    batch = ExistingParserAdapter().parse(cleaned_path.read_text(encoding="utf-8"))
    report = match_existing_pack_identity(batch, target_pack)
    cases = build_identity_review_cases(batch, target_pack, report)
    identity_actions = {
        item["record_id"]: {
            "action": item.get("action", "approve"),
            "target_question_id": item.get("target_question_id", ""),
        }
        for item in checkpoint["identity_actions"]
    }
    approvals = {
        record_id: item["target_question_id"]
        for record_id, item in identity_actions.items()
        if item["action"] == "approve"
    }
    exclusions = {
        record_id for record_id, item in identity_actions.items()
        if item["action"] in {"exclude_parser_debris", "exclude_duplicate"}
    }
    new_questions = {
        record_id: item["target_question_id"]
        for record_id, item in identity_actions.items()
        if item["action"] == "retain_new_question"
    }
    if report.complete:
        mapping = report.stable_id_by_record_id
    elif manifest.get("stage") == "identity_review":
        # An incomplete identity review is a valid resumable state. Preserve
        # its content-free decisions without attempting to materialize data.
        return RecoveredRun(
            lifecycle, batch, report, cases, identity_actions, {}, (), (), (),
            (), (), (), (), QaResult(findings=(), detector_counts={}),
            None, None,
        )
    else:
        mapping = authorize_reviewed_identity(
            report, cases, approvals, exclusions, new_questions
        )

    retained_batch = ParseBatch(
        records=tuple(item for item in batch.records if item.record_id in mapping),
        findings=tuple(item for item in batch.findings if item.record_id in mapping),
        parser_name=batch.parser_name,
        automatic_repairs=batch.automatic_repairs,
    )
    questions, parser_findings = materialize_matched_batch(retained_batch, mapping)
    benchmark = pack_questions_to_domain(target_pack)
    qa = detect_candidate_damage(questions)
    parser_answer_ids = {
        item.question_id for item in parser_findings
        if item.damage_type == "correct_answer_without_choice"
    }
    qa = QaResult(
        findings=tuple(
            item for item in qa.findings
            if not (
                item.question_id in parser_answer_ids
                and item.damage_type == "choice_structure__correct_answer_without_choice"
            )
        ),
        detector_counts=qa.detector_counts,
    )
    findings = parser_findings + qa.findings
    proposals = (
        draft_deterministic_proposals(questions, findings)
        + draft_benchmark_answer_proposals(questions, benchmark, findings)
    )
    proposal_ids = {item.proposal_id for item in proposals}
    proposal_by_fingerprint = {
        proposal_fingerprint(
            finding_id=item.finding_id,
            question_id=item.question_id,
            field=item.field,
            expected_before=item.expected_before,
            proposed_after=item.proposed_after,
            requires_source_verification=item.requires_source_verification,
        ): item.proposal_id
        for item in proposals
    }
    recovered_proposal_id = {
        item["proposal_id"]: proposal_by_fingerprint.get(item["fingerprint"])
        for item in checkpoint.get("proposal_fingerprints", [])
    }
    def proposal_id(value: str) -> str:
        return value if value in proposal_ids else recovered_proposal_id.get(value) or value
    finding_by_id = {item.finding_id: item for item in findings}

    decisions = tuple(
        ReviewDecision(item["decision_id"], proposal_id(item["proposal_id"]), ReviewAction(item["action"]), "Recovered from private checkpoint.")
        for item in checkpoint["review_decisions"]
    )
    verifications = tuple(
        SourceVerification(item["verification_id"], proposal_id(item["proposal_id"]), item["verified"], "Recovered verified checkpoint event.")
        for item in checkpoint["verifications"]
    )
    if any(item.proposal_id not in proposal_ids for item in decisions + verifications):
        raise DomainError("Checkpoint references a proposal that cannot be reproduced exactly")
    dispositions = []
    for item in checkpoint["dispositions"]:
        finding = finding_by_id.get(item["finding_id"])
        if finding is None or item["question_id"] not in {
            finding.question_id, finding.related_question_id
        }:
            raise DomainError("Checkpoint disposition finding cannot be reproduced exactly")
        dispositions.append(
            FindingDisposition(
                item["disposition_id"], item["finding_id"], item["question_id"],
                DispositionAction(item["action"]), "Recovered from private checkpoint.",
            )
        )
    dispositions = tuple(dispositions)

    candidate = comparison = None
    counts = checkpoint["comparison_counts"]
    if manifest["stage"] in {"candidate_built", "compared"} or counts:
        candidate = build_candidate(questions, findings, proposals, decisions, verifications, dispositions)
    comparison_group_ids = tuple(
        item["group_id"] for item in checkpoint.get("comparison_group_decisions", [])
    )
    post_group_qa = None
    for group_id in comparison_group_ids:
        candidate, _ = apply_exact_contaminant_group(candidate, benchmark, group_id)
    comparison_category_decisions = tuple(
        (item["category_id"], item["action"])
        for item in checkpoint.get("comparison_category_decisions", [])
    )
    for category_id, action in comparison_category_decisions:
        current = compare_candidate(candidate, benchmark)
        categories = {
            item.category_id: item
            for item in categorize_comparison_changes(current)
        }
        category = categories.get(category_id)
        if category is None:
            raise DomainError("Checkpoint comparison category cannot be reproduced exactly")
        expected_action = (
            "accept_candidate"
            if category.classification == "repeated_metadata_difference"
            else "use_reference"
        )
        if action != expected_action:
            raise DomainError("Checkpoint comparison category action is invalid for its evidence")
        if action == "use_reference":
            candidate = apply_category_reference_values(candidate, category)
    if comparison_group_ids or comparison_category_decisions:
        post_group_qa = detect_candidate_damage(candidate.questions)
    if counts:
        comparison = compare_candidate(candidate, benchmark)
        expected = {
            "field_changes": len(comparison.field_changes),
            "excluded_questions": len(comparison.documented_excluded_question_ids),
            "candidate_questions": comparison.candidate_question_count,
        }
        if counts != expected:
            raise DomainError("Recovered comparison counts do not match the checkpoint")
    return RecoveredRun(
        lifecycle, batch, report, cases, identity_actions, mapping, questions,
        findings, proposals, decisions, verifications, dispositions, benchmark,
        qa, candidate, comparison, comparison_group_ids, post_group_qa,
        comparison_category_decisions,
    )
