import json

import pytest

from ingestion_v2.demo import SYNTHETIC_DOCUMENT

from ingestion_v2.domain import DomainError
from ingestion_v2.workbench_session import SyntheticWorkbenchSession


def case(payload: dict, finding_id: str) -> dict:
    return next(item for item in payload["cases"] if item["finding_id"] == finding_id)


def test_connected_session_starts_in_memory_and_non_promoting() -> None:
    payload = SyntheticWorkbenchSession().view()

    assert payload["session"]["mode"] == "synthetic_in_memory"
    assert payload["session"]["persistent"] is False
    assert payload["session"]["event_count"] == 0
    assert payload["capabilities"]["build_isolated_candidate"] is False
    assert payload["capabilities"]["promote_canonical"] is False
    assert payload["pipeline"] == {
        "input": "synthetic_document",
        "parser": "existing_source_parser_without_broad_missing_a_recovery",
        "parsed_records": 2,
        "automatic_repairs": 0,
        "document_text_in_payload": False,
    }
    assert len(payload["cases"]) == 3
    assert {item["damage_type"] for item in payload["cases"]} == {
        "noncanonical_choice_sequence",
        "correct_answer_without_choice",
        "missing_correct_answer",
    }
    serialized = json.dumps(payload)
    assert SYNTHETIC_DOCUMENT not in serialized
    assert "deliberately conflicted example" not in serialized


def test_decision_is_validated_by_real_queue_and_recorded_in_memory() -> None:
    session = SyntheticWorkbenchSession()

    payload = session.record_action("PFV2-FIND-PARSE-000002", "approve")

    assert case(payload, "PFV2-FIND-PARSE-000002")["status"] == "awaiting_source_verification"
    assert payload["session"]["events"] == [
        {
            "event_id": "PFV2-EVENT-000001",
            "finding_id": "PFV2-FIND-PARSE-000002",
            "event_type": "decision:approve",
        }
    ]


def test_source_hold_requires_approval_then_separate_verification() -> None:
    session = SyntheticWorkbenchSession()

    approved = session.record_action("PFV2-FIND-PARSE-000002", "approve")
    verified = session.record_verification("PFV2-FIND-PARSE-000002")

    assert case(approved, "PFV2-FIND-PARSE-000002")["status"] == "awaiting_source_verification"
    assert case(verified, "PFV2-FIND-PARSE-000002")["status"] == "approved"
    assert verified["session"]["event_count"] == 2


def test_server_adapter_rejects_bypassed_or_unsupported_actions() -> None:
    session = SyntheticWorkbenchSession()

    with pytest.raises(DomainError, match="not allowed"):
        session.record_action("PFV2-FIND-PARSE-000001", "approve")
    with pytest.raises(DomainError, match="not implemented"):
        session.record_action("PFV2-FIND-PARSE-000001", "create_proposal")
    with pytest.raises(DomainError, match="not allowed"):
        session.record_verification("PFV2-FIND-PARSE-000002")


def test_later_decision_replaces_current_state_but_preserves_event_history() -> None:
    session = SyntheticWorkbenchSession()

    session.record_action("PFV2-FIND-PARSE-000002", "defer")
    payload = session.record_action("PFV2-FIND-PARSE-000002", "approve")

    assert case(payload, "PFV2-FIND-PARSE-000002")["status"] == "awaiting_source_verification"
    assert [item["event_type"] for item in payload["session"]["events"]] == [
        "decision:defer",
        "decision:approve",
    ]
