import json
from pathlib import Path

import pytest

from compiler.intake_workspace import (
    IntakeWorkspaceError,
    build_isolated_comparison_candidate,
    clean_isolated_run,
    extract_pdf_in_isolated_run,
    parse_isolated_run,
    match_isolated_run,
    validate_isolated_run,
)


def test_success_uses_copy_deletes_staging_and_preserves_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "original.pdf"
    original = b"untouched original"
    source.write_bytes(original)
    observed = {}

    def fake_read(path: Path) -> str:
        observed["path"] = path
        observed["bytes"] = path.read_bytes()
        return "Extracted source-neutral text"

    monkeypatch.setattr(
        "compiler.intake_workspace.read_pdf_pages",
        lambda path: (fake_read(path),),
    )

    result = extract_pdf_in_isolated_run(
        source,
        workspace_root=tmp_path / "runs",
    )

    assert observed["path"] != source
    assert observed["bytes"] == original
    assert source.read_bytes() == original
    assert result.staged_source_deleted is True
    assert not (result.run_directory / "incoming" / "source.pdf").exists()
    assert result.raw_artifact.read_text() == "Extracted source-neutral text"
    status = json.loads((result.run_directory / "run-status.json").read_text())
    assert status["status"] == "success"
    assert status["staged_source_present"] is False
    assert str(source) not in json.dumps(status)
    assert source.name not in json.dumps(status)


def test_failed_extraction_preserves_original_and_confines_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "original.pdf"
    original = b"untouched original"
    source.write_bytes(original)

    def fail(_path: Path) -> str:
        raise ValueError("source-identifying failure details")

    monkeypatch.setattr(
        "compiler.intake_workspace.read_pdf_pages",
        lambda path: (fail(path),),
    )

    with pytest.raises(IntakeWorkspaceError, match="isolated run"):
        extract_pdf_in_isolated_run(source, workspace_root=tmp_path / "runs")

    assert source.read_bytes() == original
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    status = json.loads((runs[0] / "run-status.json").read_text())
    assert status["status"] == "failed"
    assert status["failure_stage"] == "extraction"
    assert status["failure_type"] == "ValueError"
    assert "source-identifying" not in json.dumps(status)
    assert (runs[0] / "incoming" / "source.pdf").exists()


def test_rejects_symlink_source(tmp_path: Path) -> None:
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    link = tmp_path / "linked.pdf"
    link.symlink_to(source)

    with pytest.raises(IntakeWorkspaceError, match="regular file"):
        extract_pdf_in_isolated_run(link, workspace_root=tmp_path / "runs")

    assert not (tmp_path / "runs").exists()


def test_rejects_non_pdf_before_creating_workspace(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("not a PDF")

    with pytest.raises(IntakeWorkspaceError, match="PDF files only"):
        extract_pdf_in_isolated_run(source, workspace_root=tmp_path / "runs")

    assert not (tmp_path / "runs").exists()


def test_generalized_cleaning_updates_isolated_run_without_legacy_rules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    monkeypatch.setattr(
        "compiler.intake_workspace.read_pdf_pages",
        lambda _path: ((
            "Chapter 01: Test  \n\n\n"
            "1. Question  \n"
            "Document shared on https://www.docsity.com/example\n"
        ),),
    )
    extraction = extract_pdf_in_isolated_run(source, workspace_root=tmp_path / "runs")

    result = clean_isolated_run(extraction.run_directory)

    cleaned = result.cleaned_artifact.read_text()
    assert "docsity" in cleaned.lower()
    assert "  \n" not in cleaned
    assert "\n\n\n" not in cleaned
    assert result.chapter_count == 1
    assert result.question_count == 1
    status = json.loads((result.run_directory / "run-status.json").read_text())
    assert status["stage"] == "cleaning_complete"
    assert status["generalized_cleaning"] == "source_neutral_whitespace_v1"


def test_cleaning_rejects_unready_or_external_shape(tmp_path: Path) -> None:
    run = tmp_path / "not-a-run"
    run.mkdir()

    with pytest.raises(IntakeWorkspaceError, match="raw artifact"):
        clean_isolated_run(run)


def test_isolated_parser_excludes_broad_missing_a_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    monkeypatch.setattr(
        "compiler.intake_workspace.read_pdf_pages",
        lambda _path: ("""Chapter 1: Test
MULTIPLE CHOICE
1. Which response is correct? First response
b. Second response
c. Third response
ANS: A
Rationale text.
""",),
    )
    extraction = extract_pdf_in_isolated_run(source, workspace_root=tmp_path / "runs")
    clean_isolated_run(extraction.run_directory)

    result = parse_isolated_run(extraction.run_directory)

    questions = json.loads(result.questions_artifact.read_text())
    assert result.parsed_questions == 1
    assert [choice["label"] for choice in questions[0]["choices"]] == ["B", "C"]
    assert result.choice_sequence_findings == 1
    status = json.loads((result.run_directory / "run-status.json").read_text())
    assert status["parser"] == "source_parser_without_broad_missing_a_recovery"


def test_isolated_validation_is_source_neutral_and_does_not_build_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    monkeypatch.setattr(
        "compiler.intake_workspace.read_pdf_pages",
        lambda _path: ("""Chapter 1: Test
MULTIPLE CHOICE
1. First question?
a. First
b. Second
ANS: A
Rationale.
DIF: Test
2. Missing answer?
a. First
b. Second
Rationale.
""",),
    )
    extraction = extract_pdf_in_isolated_run(source, workspace_root=tmp_path / "runs")
    clean_isolated_run(extraction.run_directory)
    parse_isolated_run(extraction.run_directory)

    result = validate_isolated_run(extraction.run_directory)

    assert result.normalized_questions == 2
    assert result.eligible_questions == 1
    assert result.skipped_questions == 1
    assert result.diagnostics_by_code["missing_correct_answer"] == 1
    report = json.loads(result.diagnostics_artifact.read_text())
    assert all(set(item) == {"severity", "label", "code"} for item in report["diagnostics"])
    assert not list(result.run_directory.rglob("*.prepflow.json"))

    canonical = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Test",
                "type": "mc",
                "stem": "First question?",
                "choices": [
                    {"label": "A", "text": "First"},
                    {"label": "B", "text": "Second"},
                ],
                "correct_answers": ["A"],
                "rationale": "Rationale.",
            },
            {
                "id": "PFQ-test-pack-000000002",
                "chapter": 1,
                "chapter_title": "Test",
                "type": "mc",
                "stem": "Missing answer?",
                "choices": [
                    {"label": "A", "text": "First"},
                    {"label": "B", "text": "Second"},
                ],
                "correct_answers": [],
                "rationale": "Rationale.",
            },
        ],
    }
    original_canonical = json.loads(json.dumps(canonical))
    match_isolated_run(
        extraction.run_directory,
        canonical_pack=canonical,
        candidate_pack=canonical,
    )

    candidate_result = build_isolated_comparison_candidate(
        extraction.run_directory,
        canonical_pack=canonical,
    )

    candidate = json.loads(candidate_result.candidate_artifact.read_text())
    manifest = json.loads(candidate_result.manifest_artifact.read_text())
    assert [question["id"] for question in candidate["questions"]] == [
        "PFQ-test-pack-000000001",
        "PFQ-test-pack-000000002",
    ]
    assert manifest["repairs_applied"] == 0
    assert manifest["promotion_ready"] is False
    assert "explicit_approval_required" in manifest["promotion_blockers"]
    assert canonical == original_canonical
