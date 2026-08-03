import json

import pytest

from ingestion_v2.checkpoint import read_checkpoint, write_checkpoint
from ingestion_v2.domain import DomainError
from ingestion_v2.run_lifecycle import RunLifecycle


def payload(run_id: str) -> dict:
    return {
        "format": "prepflow_v2_checkpoint",
        "version": "1.0",
        "run_id": run_id,
        "target_pack_id": "medical_surgical",
        "identity_actions": [{"record_id": "PFV2-REC-000001", "target_question_id": "PFQ-medical_surgical-000000001"}],
        "review_decisions": [{"decision_id": "PFV2-DEC-SESSION-000001", "proposal_id": "PFV2-PROP-ANSWER-000001", "action": "approve"}],
        "verifications": [{"verification_id": "PFV2-VERIFY-SESSION-000002", "proposal_id": "PFV2-PROP-ANSWER-000001", "verified": True}],
        "dispositions": [{"disposition_id": "PFV2-DISP-SESSION-000003", "finding_id": "PFV2-FIND-QA-000001", "question_id": "PFQ-medical_surgical-000000060", "action": "exclude_record"}],
        "comparison_counts": {"field_changes": 73, "excluded_questions": 2},
    }


def test_checkpoint_round_trip_contains_only_source_neutral_decisions(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    expected = payload(run.run_directory.name)

    path = write_checkpoint(run.run_directory, expected)

    assert read_checkpoint(run.run_directory) == expected
    encoded = path.read_text()
    assert "Medical-Surgical Nursing" not in encoded
    assert "source.bin" not in encoded


@pytest.mark.parametrize("key", ["stem", "page_text", "source_path", "proposed_after"])
def test_checkpoint_rejects_source_or_question_content_fields(tmp_path, key) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    value = payload(run.run_directory.name)
    value[key] = "private content"

    with pytest.raises(DomainError, match="source-bearing"):
        write_checkpoint(run.run_directory, value)


def test_checkpoint_rejects_wrong_run_identity_and_symlink(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    with pytest.raises(DomainError, match="identity"):
        write_checkpoint(run.run_directory, payload("v2-run-wrong"))

    outside = tmp_path / "outside"
    outside.mkdir()
    (run.run_directory / "audit").symlink_to(outside)
    with pytest.raises(DomainError, match="unsafe"):
        write_checkpoint(run.run_directory, payload(run.run_directory.name))
