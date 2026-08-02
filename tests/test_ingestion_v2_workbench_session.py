import json

import pytest
from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ingestion_v2.demo import SYNTHETIC_DOCUMENT

from ingestion_v2.domain import DomainError
from ingestion_v2.workbench_session import SyntheticWorkbenchSession


def case(payload: dict, finding_id: str) -> dict:
    return next(item for item in payload["cases"] if item["finding_id"] == finding_id)


def synthetic_pdf_bytes(lines: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    commands = ["BT /F1 11 Tf 72 740 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj 0 -14 Td")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("latin-1"))
    page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


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
        "extraction": None,
        "cleaning": None,
        "identity_pending": False,
        "identity": {"state": "not_run"},
        "qa": {"state": "not_run"},
        "proposal_generation": {
            "state": "not_run",
            "proposal_count": 0,
            "automatic_applications": 0,
        },
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
    assert started["pipeline"]["extraction"] == {
        "adapter": "synthetic_text_utf8_v1",
        "page_count": 1,
        "extracted_characters": len(SYNTHETIC_DOCUMENT),
    }
    assert started["pipeline"]["cleaning"] == {
        "cleaner": "guarded_page_aware_source_neutral_v1",
        "removed_repeated_lines": 0,
        "stripped_repeated_suffixes": 0,
        "protected_repeated_structures": 0,
        "meaning_repairs": 0,
        "source_specific_rules": 0,
    }
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


def test_real_pdf_bytes_run_front_half_and_stop_at_identity_gate(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Which option is expected?",
            "a. First option",
            "b. Second option",
            "ANS: B",
            "The second option is expected.",
            "DIF: Synthetic",
        ]
    )
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")

    payload = session.start_pdf_run(pdf)

    assert payload["run"]["state"] == "identity_pending"
    assert payload["run"]["staged_copy_present"] is False
    assert payload["run"]["raw_text_present"] is True
    assert payload["run"]["cleaned_text_present"] is True
    assert payload["run"]["parsed_records"] == 1
    assert payload["pipeline"]["extraction"]["adapter"] == "text_pdf_pages_v1"
    assert payload["pipeline"]["extraction"]["page_count"] == 1
    assert payload["pipeline"]["identity_pending"] is True
    assert payload["cases"] == []
    manifest_text = (session._lifecycle.run_directory / "run.json").read_text()
    assert "Synthetic PDF" not in manifest_text
    assert ".pdf" not in manifest_text


def test_pdf_identity_assessment_matches_only_unique_exact_existing_pack_stems(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Which option is expected?",
            "a. First option",
            "b. Second option",
            "ANS: B",
            "The second option is expected.",
            "DIF: Synthetic",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test",
        "questions": [
            {
                "id": "PFQ-test-000000001",
                "chapter": 1,
                "type": "mc",
                "stem": "Which option is expected?",
            }
        ],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)

    payload = session.match_existing_pack(target)

    assert payload["run"]["state"] == "identity_matched"
    assert payload["pipeline"]["identity"]["matched_count"] == 1
    assert payload["pipeline"]["identity"]["finding_count"] == 0
    assert payload["pipeline"]["identity"]["automatic_id_assignments_authorized"] is True
    assert payload["candidate"]["state"] == "not_built"
    assert payload["run"]["promotion_available"] is False


def test_changed_pdf_stem_stops_in_identity_review_without_guessed_id(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Changed stem?",
            "a. First option",
            "b. Second option",
            "ANS: B",
            "Rationale.",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test",
        "questions": [
            {"id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Original stem?"}
        ],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)

    payload = session.match_existing_pack(target)

    assert payload["run"]["state"] == "identity_review"
    assert payload["pipeline"]["identity"]["matches"] == []
    assert payload["pipeline"]["identity"]["findings"][0]["candidate_question_ids"] == []
    assert payload["pipeline"]["identity"]["automatic_id_assignments_authorized"] is False

    reviewed = session.record_identity_action(
        "PFV2-REC-000001", "approve", "PFQ-test-000000001"
    )

    assert reviewed["run"]["state"] == "identity_matched"
    assert reviewed["pipeline"]["identity"]["reviewed_id_assignments_authorized"] is True
    assert reviewed["pipeline"]["identity"]["automatic_id_assignments_authorized"] is False
    assert reviewed["candidate"]["state"] == "not_built"

    materialized = session.materialize_identity_review()
    assert materialized["run"]["state"] == "review_ready"
    assert materialized["pipeline"]["parsed_records"] == 1
    assert materialized["candidate"]["state"] == "not_built"

    built = session.build_isolated_candidate()
    assert built["run"]["state"] == "candidate_built"
    assert built["candidate"]["question_count"] == 1
    compared = session.compare_isolated_candidate()
    assert compared["run"]["state"] == "compared"
    assert compared["comparison"]["stable_ids_exact"] is True
    assert compared["comparison"]["field_change_count"] > 0
    assert {change["question_id"] for change in compared["comparison"]["field_changes"]} == {
        "PFQ-test-000000001"
    }


def test_identity_defer_keeps_run_blocked_and_invalid_selection_is_rejected(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Changed stem?",
            "a. First",
            "b. Second",
            "ANS: A",
            "Rationale.",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "stem": "Original stem?"}],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)

    deferred = session.record_identity_action("PFV2-REC-000001", "defer")

    assert deferred["run"]["state"] == "identity_review"
    assert deferred["pipeline"]["identity"]["review_cases"][0]["status"] == "defer"
    with pytest.raises(DomainError, match="displayed identity suggestion"):
        session.record_identity_action(
            "PFV2-REC-000001", "approve", "PFQ-test-999999999"
        )


def test_materialized_pdf_runs_qa_detectors_without_repairs_or_proposals(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Which action is expected?",
            "a. Damaged abCdEf xyZaBc g h j fragments",
            "b. Clean choice",
            "ANS: B",
            "Clean rationale.",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [
            {
                "id": "PFQ-test-000000001",
                "chapter": 1,
                "type": "mc",
                "stem": "Which action is expected?",
                "choices": [
                    {"label": "A", "text": "Original choice"},
                    {"label": "B", "text": "Clean choice"},
                ],
                "correct_answers": ["B"],
                "rationale": "Clean rationale.",
            }
        ],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    matched = session.match_existing_pack(target)
    assert matched["run"]["state"] == "identity_matched"

    payload = session.materialize_identity_review()

    assert payload["pipeline"]["qa"]["finding_count"] >= 1
    assert payload["pipeline"]["qa"]["detector_counts"]["interleaving"] == 1
    assert payload["pipeline"]["qa"]["automatic_repairs"] == 0
    assert payload["pipeline"]["qa"]["proposals_created"] == 0
    qa_cases = [item for item in payload["cases"] if item["finding_id"].startswith("PFV2-FIND-QA-")]
    assert any(item["field"] == "choices" for item in qa_cases)
    assert all(item["proposal"] is None for item in qa_cases)


def test_materialized_embedded_choice_is_proposed_but_not_applied(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Which action is appropriate?",
            "a. First action b. Second action",
            "c. Third action",
            "d. Fourth action",
            "ANS: D",
            "The fourth action is appropriate.",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [
            {
                "id": "PFQ-test-000000001",
                "chapter": 1,
                "type": "mc",
                "stem": "Which action is appropriate?",
                "choices": [
                    {"label": "A", "text": "First action"},
                    {"label": "B", "text": "Second action"},
                    {"label": "C", "text": "Third action"},
                    {"label": "D", "text": "Fourth action"},
                ],
                "correct_answers": ["D"],
                "rationale": "The fourth action is appropriate.",
            }
        ],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)

    payload = session.materialize_identity_review()

    assert payload["pipeline"]["proposal_generation"] == {
        "state": "complete",
        "proposal_count": 1,
        "automatic_applications": 0,
    }
    case = next(item for item in payload["cases"] if item["damage_type"] == "embedded_choice_recovery_candidate")
    assert case["proposal"] is not None
    assert case["status"] == "awaiting_decision"
    built = session.build_isolated_candidate()
    assert built["candidate"]["applied_proposal_ids"] == []
    assert case["finding_id"] in built["candidate"]["unresolved_finding_ids"]

    approved = session.record_action(case["finding_id"], "approve")
    rebuilt = session.build_isolated_candidate()
    assert approved["candidate"]["state"] == "not_built"
    assert rebuilt["candidate"]["applied_proposal_ids"] == [case["proposal"]["proposal_id"]]


def test_pdf_run_rejects_empty_selection_before_creating_workspace(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")

    with pytest.raises(DomainError, match="empty"):
        session.start_pdf_run(b"")

    assert not (tmp_path / "runs").exists()


def test_identity_pending_pdf_can_be_cancelled_cleaned_and_retried(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Which option?",
            "a. First",
            "b. Second",
            "ANS: A",
            "First is expected.",
        ]
    )
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    run_directory = session._lifecycle.run_directory

    payload = session.cleanup_run()

    assert payload["run"]["state"] == "not_started"
    assert payload["run"]["last_cleanup"]["source_bearing_artifacts_removed"] is True
    assert not (run_directory / "incoming" / "source.bin").exists()
    assert not (run_directory / "artifacts" / "raw.txt").exists()
    assert not (run_directory / "artifacts" / "cleaned.txt").exists()
    assert json.loads((run_directory / "run.json").read_text())["stage"] == "failed_cleaned"

    retry = session.start_pdf_run(pdf)
    assert retry["run"]["state"] == "identity_pending"


def test_invalid_pdf_failure_can_be_explicitly_cleaned(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")

    with pytest.raises(DomainError, match="PDF extraction failed"):
        session.start_pdf_run(b"not a pdf")

    failed_run = session._lifecycle.run_directory
    assert session.view()["run"]["state"] == "failed"
    payload = session.cleanup_run()

    assert payload["run"]["state"] == "not_started"
    assert not (failed_run / "incoming" / "source.bin").exists()


def test_completed_run_manifest_survives_while_new_run_starts(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_run()
    session.build_isolated_candidate()
    session.compare_isolated_candidate()
    completed = session.complete_run()
    completed_directory = session._lifecycle.run_directory

    assert completed["run"]["state"] == "completed"
    next_run = session.start_run()

    assert next_run["run"]["state"] == "review_ready"
    assert session._lifecycle.run_directory != completed_directory
    prior_manifest = json.loads((completed_directory / "run.json").read_text())
    assert prior_manifest["stage"] == "completed"
    assert not (completed_directory / "artifacts" / "raw.txt").exists()
    assert not (completed_directory / "artifacts" / "cleaned.txt").exists()
