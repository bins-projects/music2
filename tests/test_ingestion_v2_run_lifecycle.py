import json
from pathlib import Path

import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.run_lifecycle import RunLifecycle


def artifact(run: RunLifecycle, directory: str, filename: str) -> Path:
    return run.run_directory / directory / filename


def test_successful_run_deletes_staging_after_cleaning_and_text_at_completion(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(b"synthetic disposable copy", source_type="synthetic_text")
    run.record_extraction("raw synthetic text")

    assert artifact(run, "incoming", "source.bin").is_file()
    run.record_cleaning("clean synthetic text")
    assert not artifact(run, "incoming", "source.bin").exists()
    assert artifact(run, "artifacts", "raw.txt").is_file()
    assert artifact(run, "artifacts", "cleaned.txt").is_file()

    run.record_review_ready(parsed_records=2, finding_count=3)
    run.record_candidate(question_count=2, unresolved_findings=3)
    run.record_comparison(field_changes=0, id_accounting_complete=True)
    manifest = run.complete_and_cleanup()

    assert manifest["stage"] == "completed"
    assert manifest["source_bearing_artifacts_removed"] is True
    assert not artifact(run, "artifacts", "raw.txt").exists()
    assert not artifact(run, "artifacts", "cleaned.txt").exists()
    assert (run.run_directory / "run.json").is_file()


def test_manifest_is_source_neutral_and_contains_no_document_text(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(b"private source bytes", source_type="pdf")
    run.record_extraction("distinctive private extracted sentence")

    serialized = (run.run_directory / "run.json").read_text(encoding="utf-8")

    assert "private source bytes" not in serialized
    assert "distinctive private extracted sentence" not in serialized
    assert ".pdf" not in serialized
    assert str(tmp_path) not in serialized
    assert json.loads(serialized)["source_type"] == "pdf"


def test_failed_run_preserves_controlled_artifacts_until_explicit_cleanup(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(b"synthetic disposable copy", source_type="synthetic_text")
    run.record_extraction("raw synthetic text")

    failed = run.fail("synthetic_parser_failure")

    assert failed["failed_stage"] == "extracted"
    assert artifact(run, "incoming", "source.bin").is_file()
    assert artifact(run, "artifacts", "raw.txt").is_file()

    cleaned = run.cleanup_failed_run()

    assert cleaned["stage"] == "failed_cleaned"
    assert cleaned["source_bearing_artifacts_removed"] is True
    assert not artifact(run, "incoming", "source.bin").exists()
    assert not artifact(run, "artifacts", "raw.txt").exists()


def test_cleanup_refuses_symlink_and_never_deletes_external_target(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(b"synthetic disposable copy", source_type="synthetic_text")
    run.fail("synthetic_staging_failure")
    staged = artifact(run, "incoming", "source.bin")
    staged.unlink()
    external = tmp_path / "user-original.pdf"
    external.write_bytes(b"only original")
    staged.symlink_to(external)

    with pytest.raises(DomainError, match="symbolic-link"):
        run.cleanup_failed_run()

    assert external.read_bytes() == b"only original"


def test_invalid_transition_and_source_bearing_failure_message_are_rejected(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")

    with pytest.raises(DomainError, match="stage staged"):
        run.record_extraction("text")
    with pytest.raises(DomainError, match="source-neutral"):
        run.fail("Failed on /home/user/private-book.pdf")


def test_candidate_or_comparison_can_return_to_review_without_losing_source_text(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(b"copy", source_type="synthetic_text")
    run.record_extraction("raw")
    run.record_cleaning("clean")
    run.record_review_ready(parsed_records=1, finding_count=1)
    run.record_candidate(question_count=1, unresolved_findings=1)
    run.record_comparison(field_changes=0, id_accounting_complete=True)

    manifest = run.return_to_review()

    assert manifest["stage"] == "review_ready"
    assert "comparison_field_changes" not in manifest
    assert artifact(run, "artifacts", "raw.txt").is_file()
    assert artifact(run, "artifacts", "cleaned.txt").is_file()
