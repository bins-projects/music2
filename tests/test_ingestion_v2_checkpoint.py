import json

import pytest

from ingestion_v2.checkpoint import proposal_fingerprint, read_checkpoint, write_checkpoint
from ingestion_v2.domain import DomainError
from ingestion_v2.run_lifecycle import RunLifecycle


def payload(run_id: str) -> dict:
    return {
        "format": "prepflow_v2_checkpoint",
        "version": "1.0",
        "run_id": run_id,
        "target_pack_id": "medical_surgical",
        "identity_actions": [{"record_id": "PFV2-REC-000001", "action": "approve", "target_question_id": "PFQ-medical_surgical-000000001"}],
        "review_decisions": [{"decision_id": "PFV2-DEC-SESSION-000001", "proposal_id": "PFV2-PROP-ANSWER-000001", "action": "approve"}],
        "verifications": [{"verification_id": "PFV2-VERIFY-SESSION-000002", "proposal_id": "PFV2-PROP-ANSWER-000001", "verified": True}],
        "proposal_fingerprints": [{
            "proposal_id": "PFV2-PROP-ANSWER-000001",
            "fingerprint": "a" * 64,
        }],
        "comparison_group_decisions": [],
        "comparison_category_decisions": [],
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


def test_proposal_fingerprint_is_content_free_and_changes_with_proposal_value() -> None:
    common = {
        "finding_id": "PFV2-FIND-PARSE-000001",
        "question_id": "PFQ-medical_surgical-000000001",
        "field": "correct_answers",
        "expected_before": ["A", "C", "E"],
        "requires_source_verification": True,
    }

    answer_c = proposal_fingerprint(**common, proposed_after=["C"])
    answer_a = proposal_fingerprint(**common, proposed_after=["A"])

    assert len(answer_c) == 64
    assert answer_c != answer_a
    assert "C" not in answer_c


def test_checkpoint_rejects_malformed_proposal_fingerprint(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    value = payload(run.run_directory.name)
    value["proposal_fingerprints"][0]["fingerprint"] = "not-a-sha256"

    with pytest.raises(DomainError, match="proposal fingerprint"):
        write_checkpoint(run.run_directory, value)


def test_checkpoint_accepts_only_exact_group_approval_records(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    value = payload(run.run_directory.name)
    value["comparison_group_decisions"] = [{
        "group_id": "PFV2-GROUP-0123456789abcdef",
        "action": "approve_exact_group",
    }]

    assert write_checkpoint(run.run_directory, value).is_file()

    value["comparison_group_decisions"][0]["action"] = "approve_everything"
    with pytest.raises(DomainError, match="comparison group"):
        write_checkpoint(run.run_directory, value)


def test_checkpoint_rejects_invalid_comparison_category_action(tmp_path) -> None:
    run = RunLifecycle.create(tmp_path / "runs")
    value = payload(run.run_directory.name)
    value["comparison_category_decisions"] = [{
        "category_id": "PFV2-CATEGORY-0123456789abcdef",
        "action": "accept_everything",
    }]

    with pytest.raises(DomainError, match="comparison category"):
        write_checkpoint(run.run_directory, value)
