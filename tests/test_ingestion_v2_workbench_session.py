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
    assert payload["capabilities"]["build_isolated_candidate"] is True
    assert payload["capabilities"]["compare_isolated_candidate"] is True
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


def test_candidate_before_verification_preserves_held_change_and_all_blockers() -> None:
    session = SyntheticWorkbenchSession()
    session.record_action("PFV2-FIND-PARSE-000002", "approve")

    payload = session.build_isolated_candidate()

    assert payload["candidate"]["state"] == "built_in_memory"
    assert payload["candidate"]["question_count"] == 2
    assert payload["candidate"]["applied_proposal_ids"] == []
    assert len(payload["candidate"]["unresolved_finding_ids"]) == 3
    assert payload["candidate"]["promotion_ready"] is False
    assert "candidate_comparison_incomplete" in payload["candidate"]["blocking_reasons"]
    assert session.questions[0].correct_answers == ("A",)


def test_verified_approval_changes_only_isolated_candidate_and_remains_blocked() -> None:
    session = SyntheticWorkbenchSession()
    session.record_action("PFV2-FIND-PARSE-000002", "approve")
    session.record_verification("PFV2-FIND-PARSE-000002")

    payload = session.build_isolated_candidate()

    assert payload["candidate"]["applied_proposal_ids"] == ["PFV2-PROP-0001"]
    assert payload["candidate"]["unresolved_finding_ids"] == [
        "PFV2-FIND-PARSE-000001",
        "PFV2-FIND-PARSE-000003",
    ]
    assert payload["candidate"]["promotion_ready"] is False
    assert session.questions[0].correct_answers == ("A",)
    assert session._candidate.questions[0].correct_answers == ("B",)
    assert payload["session"]["events"][-1]["event_type"] == "candidate:built_in_memory"


def test_comparison_explains_verified_candidate_delta_and_clears_stale_gate() -> None:
    session = SyntheticWorkbenchSession()
    session.record_action("PFV2-FIND-PARSE-000002", "approve")
    session.record_verification("PFV2-FIND-PARSE-000002")
    session.build_isolated_candidate()

    payload = session.compare_isolated_candidate()

    assert payload["comparison"]["state"] == "complete"
    assert payload["comparison"]["stable_ids_exact"] is True
    assert payload["comparison"]["field_change_count"] == 1
    assert payload["comparison"]["field_changes"] == [
        {
            "question_id": "PFQ-synthetic-000000108",
            "field": "correct_answers",
            "benchmark_value": ("A",),
            "candidate_value": ("B",),
        }
    ]
    assert "candidate_comparison_incomplete" not in payload["candidate"]["blocking_reasons"]
    assert payload["candidate"]["promotion_ready"] is False


def test_review_change_invalidates_candidate_and_its_comparison() -> None:
    session = SyntheticWorkbenchSession()
    session.record_action("PFV2-FIND-PARSE-000002", "defer")
    session.build_isolated_candidate()
    session.compare_isolated_candidate()

    payload = session.record_action("PFV2-FIND-PARSE-000002", "approve")

    assert payload["candidate"]["state"] == "not_built"
    assert payload["comparison"]["state"] == "not_run"


def test_comparison_requires_a_built_candidate() -> None:
    with pytest.raises(DomainError, match="before comparison"):
        SyntheticWorkbenchSession().compare_isolated_candidate()


def test_retain_blocker_records_disposition_without_resolving_finding() -> None:
    session = SyntheticWorkbenchSession()

    payload = session.record_disposition("PFV2-FIND-PARSE-000003", "leave_blocked")
    payload = session.build_isolated_candidate()

    assert case(payload, "PFV2-FIND-PARSE-000003")["status"] == "retained_blocker"
    assert "PFV2-FIND-PARSE-000003" in payload["candidate"]["unresolved_finding_ids"]
    assert payload["session"]["events"][0]["event_type"] == "disposition:retain_blocker"


def test_explicit_exclusion_accounts_for_whole_record_and_all_its_findings() -> None:
    session = SyntheticWorkbenchSession()

    payload = session.record_disposition("PFV2-FIND-PARSE-000001", "exclude_record")
    assert case(payload, "PFV2-FIND-PARSE-000001")["status"] == "excluded_record"
    assert case(payload, "PFV2-FIND-PARSE-000002")["status"] == "excluded_record"

    session.build_isolated_candidate()
    payload = session.compare_isolated_candidate()

    assert payload["candidate"]["question_count"] == 1
    assert payload["candidate"]["excluded_question_ids"] == [
        "PFQ-synthetic-000000108"
    ]
    assert payload["candidate"]["unresolved_finding_ids"] == [
        "PFV2-FIND-PARSE-000003"
    ]
    assert payload["comparison"]["stable_ids_exact"] is False
    assert payload["comparison"]["id_accounting_complete"] is True
    assert payload["comparison"]["documented_excluded_question_ids"] == [
        "PFQ-synthetic-000000108"
    ]
    assert payload["candidate"]["promotion_ready"] is False


def test_managed_session_runs_document_through_lifecycle_and_final_cleanup(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")

    before = session.view()
    assert before["run"]["state"] == "not_started"
    assert before["cases"] == []
    with pytest.raises(DomainError, match="Start"):
        session.build_isolated_candidate()

    started = session.start_run()
    assert started["run"]["state"] == "review_ready"
    assert started["run"]["staged_copy_present"] is False
    assert started["run"]["raw_text_present"] is True
    assert started["run"]["cleaned_text_present"] is True
    assert len(started["cases"]) == 3

    candidate = session.build_isolated_candidate()
    assert candidate["run"]["state"] == "candidate_built"
    compared = session.compare_isolated_candidate()
    assert compared["run"]["state"] == "compared"
    completed = session.complete_run()

    assert completed["run"]["state"] == "completed"
    assert completed["run"]["raw_text_present"] is False
    assert completed["run"]["cleaned_text_present"] is False
    assert completed["run"]["promotion_available"] is False
    with pytest.raises(DomainError, match="completed"):
        session.build_isolated_candidate()


def test_review_change_returns_managed_compared_run_to_review_stage(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_run()
    session.build_isolated_candidate()
    session.compare_isolated_candidate()

    payload = session.record_action("PFV2-FIND-PARSE-000002", "defer")

    assert payload["run"]["state"] == "review_ready"
    assert payload["candidate"]["state"] == "not_built"
    assert payload["comparison"]["state"] == "not_run"
