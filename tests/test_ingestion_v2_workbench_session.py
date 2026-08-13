import json
import os
from dataclasses import replace

import pytest
from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ingestion_v2.demo import SYNTHETIC_DOCUMENT

from ingestion_v2.domain import Candidate, DomainError, Finding, FindingSeverity, Proposal, QuestionRecord
from ingestion_v2.recovery import (
    _restore_private_proposal_collections,
    list_completed_runs,
    list_recoverable_runs,
)
from ingestion_v2.workbench_session import SyntheticWorkbenchSession, _source_context_page_indexes


def case(payload: dict, finding_id: str) -> dict:
    return next(item for item in payload["cases"] if item["finding_id"] == finding_id)


def synthetic_pdf_bytes(lines: list[str]) -> bytes:
    return synthetic_pdf_pages_bytes([lines])


def synthetic_pdf_pages_bytes(pages: list[list[str]]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
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
            "document_findings": [],
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


def test_user_authored_proposal_requires_separate_approval_and_verification() -> None:
    session = SyntheticWorkbenchSession()
    original = case(session.view(), "PFV2-FIND-PARSE-000001")["preserved_value"]

    drafted = session.draft_user_proposal(
        "PFV2-FIND-PARSE-000001",
        [["A", "First option"], ["B", "Second option"], ["C", "Third option"]],
        "The temporary source shows the missing first option.",
        requires_source_verification=True,
    )

    drafted_case = case(drafted, "PFV2-FIND-PARSE-000001")
    assert drafted_case["status"] == "awaiting_decision"
    assert drafted_case["preserved_value"] == original
    assert drafted_case["proposal"]["proposed_value"][0] == ("A", "First option")
    assert drafted_case["preserved_question"]["choices"][0] == ["B", "Second option"]
    assert drafted_case["proposed_question"]["choices"][0] == ["A", "First option"]
    assert drafted_case["proposed_question"]["changed_fields"] == ["choices"]
    assert drafted_case["proposal"]["requires_source_verification"] is True
    unapproved = session.build_isolated_candidate()
    assert unapproved["candidate"]["applied_proposal_ids"] == []

    approved = session.record_action("PFV2-FIND-PARSE-000001", "approve")
    assert case(approved, "PFV2-FIND-PARSE-000001")["status"] == "awaiting_source_verification"
    verified = session.record_verification("PFV2-FIND-PARSE-000001")
    rebuilt = session.build_isolated_candidate()
    assert case(verified, "PFV2-FIND-PARSE-000001")["status"] == "approved"
    assert len(rebuilt["candidate"]["applied_proposal_ids"]) == 1


def test_source_first_accept_as_is_resolves_a_flag_without_a_proposal() -> None:
    session = SyntheticWorkbenchSession()

    accepted = session.record_disposition("PFV2-FIND-PARSE-000001", "accept_as_is")
    candidate = session.build_isolated_candidate()

    assert case(accepted, "PFV2-FIND-PARSE-000001")["status"] == "approved"
    assert "PFV2-FIND-PARSE-000001" not in candidate["candidate"]["unresolved_finding_ids"]


def test_candidate_inspection_reports_ordered_chapters_and_question_packets() -> None:
    session = SyntheticWorkbenchSession()
    session._candidate = Candidate((
        QuestionRecord("PFQ-test-000000001", 1, "multiple_choice", "First?", (("A", "One"),), ("A",), "First rationale.", "One", "PFV2-REC-000001"),
        QuestionRecord("PFQ-test-000000002", 2, "completion", "Second?", (), ("Two",), "Second rationale.", "Two", "PFV2-REC-000002"),
    ))

    inspection = session.candidate_inspection()

    assert inspection["state"] == "ready"
    assert inspection["overview"]["retained_questions"] == 2
    assert [item["chapter"] for item in inspection["chapters"]] == [1, 2]
    assert inspection["chapter_count_matches_total"] is True
    assert inspection["questions"][0]["question_id"].startswith("PFQ-")
    assert "stem" in inspection["questions"][0]
    assert len(inspection["overview"]["candidate_sha256"]) == 64


def test_validated_existing_extraction_starts_review_without_native_extraction(tmp_path, monkeypatch) -> None:
    pdf = synthetic_pdf_bytes(["unused by the validated extraction"])
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")

    monkeypatch.setattr(
        "ingestion_v2.workbench_session.extract_disposable_copy",
        lambda *_: (_ for _ in ()).throw(AssertionError("native extraction must not run")),
    )
    payload = session.start_pdf_run_from_existing_extraction(
        pdf,
        "Chapter 1: Reused\nMULTIPLE CHOICE\n1. Which?\na. First\nANS: A\nReason.",
        adapter_name="tesseract_ocr_v1",
        page_count=1,
    )

    assert payload["pipeline"]["extraction"]["adapter"] == "tesseract_ocr_v1"
    assert payload["run"]["state"] == "identity_pending"


def test_validated_source_recovery_survives_source_only_restart(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(["unused by the validated extraction"])
    primary = (
        "Chapter 1: Recovery\nMULTIPLE CHOICE\n"
        "1. The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?\n"
        "a. First\nb. Second\nANS: A\nReason."
    )
    alternate = primary.replace(
        "NfoUllRowSsIthNeGnTuBrsi.ngCprMocess", "follows the nursing process"
    )
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run_from_existing_extraction(
        pdf, primary, adapter_name="pypdf_plain_v1", page_count=1,
        corroborating_texts=(alternate,),
    )
    assert "follows the nursing process" in session._parse_batch.records[0].stem
    session.materialize_source_only({"display_name": "Recovery", "slug": "recovery", "prefix": "Recovery"})

    resumed = SyntheticWorkbenchSession.resume_source_only_run(session._lifecycle.run_directory)
    assert "follows the nursing process" in resumed.questions[0].stem
    assert (session._lifecycle.run_directory / "artifacts" / "source-recovery.json").is_file()


def test_complete_question_editor_repairs_grouped_choice_damage_and_undoes_safely() -> None:
    session = SyntheticWorkbenchSession()
    question = QuestionRecord(
        "PFQ-synthetic-000000204", 7, "multiple_choice", "Rate? a 9 bo ce 15",
        (("D", "20"),), ("B",), "Reason.", "Chapter", "PFV2-REC-000204",
    )
    session.questions = (question,)
    session.findings = (
        Finding("PFV2-FIND-PARSE-0204", question.question_id, "choices", "noncanonical_choice_sequence", FindingSeverity.BLOCKING, "Choices are incomplete."),
        Finding("PFV2-FIND-ANSWER-0204", question.question_id, "correct_answers", "correct_answer_without_choice", FindingSeverity.BLOCKING, "Answer has no choice."),
        Finding("PFV2-FIND-QA-0204", question.question_id, "choices", "choice_structure", FindingSeverity.BLOCKING, "Choice structure is incomplete."),
    )
    session.proposals = ()

    repaired = session.save_complete_question_repair(question.question_id, {
        "stem": question.stem,
        "choices": [{"label": "A", "text": "9"}, {"label": "B", "text": "11"}, {"label": "C", "text": "15"}, {"label": "D", "text": "20"}],
        "correct_answers": ["B"], "rationale": question.rationale,
    })
    group = repaired["question_groups"][0]
    assert repaired["summary"]["case_count"] == 0
    assert group["effective_question"]["choices"] == [["A", "9"], ["B", "11"], ["C", "15"], ["D", "20"]]
    assert group["effective_question"]["correct_answers"] == ["B"]

    restored = session.undo_complete_question_repair(question.question_id)
    assert restored["summary"]["case_count"] == 1
    assert restored["question_groups"][0]["original_question"] == restored["question_groups"][0]["effective_question"]


def test_complete_question_editor_allows_unflagged_stem_and_multi_answer_fields() -> None:
    session = SyntheticWorkbenchSession()
    question = QuestionRecord(
        "PFQ-synthetic-000000205", 7, "multiple_response", "Old stem",
        (("A", "one"), ("B", "two"), ("C", "three"), ("D", "four")), ("A",), "Reason.",
        "Chapter", "PFV2-REC-000205",
    )
    session.questions = (question,)
    # Only choices were flagged; stem, answer, and rationale remain editable.
    session.findings = (
        Finding("PFV2-FIND-CHOICES-0205", question.question_id, "choices", "choice_structure", FindingSeverity.BLOCKING, "Choice review."),
    )
    session.proposals = ()

    payload = session.save_complete_question_repair(question.question_id, {
        "stem": "New stem", "choices": [
            {"label": "A", "text": "9"}, {"label": "B", "text": "11"},
            {"label": "C", "text": "15"}, {"label": "D", "text": "20"},
        ], "correct_answers": ["B", "D"], "rationale": "Updated reason.",
    })
    group = payload["question_groups"][0]
    assert group["unresolved"] is False
    assert group["effective_question"]["stem"] == "New stem"
    assert group["effective_question"]["correct_answers"] == ["B", "D"]
    assert {item.field for item in session.proposals} == {"stem", "choices", "correct_answers", "rationale"}


def test_source_only_recovery_preserves_complete_unflagged_correction_and_approval(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Recovery", "MULTIPLE CHOICE", "1. Which?",
        "a. One", "b. Two", "ANS: B", "Two is correct.",
    ])
    original = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    original.start_pdf_run(pdf)
    original.materialize_source_only({"display_name": "Recovery", "slug": "recovery", "prefix": "Recovery"})
    question = original.questions[0]
    original.save_complete_question_repair(question.question_id, {
        "stem": "Which answer is best?", "choices": [
            {"label": "A", "text": "One"}, {"label": "B", "text": "Two"},
        ], "correct_answers": ["B"], "rationale": question.rationale,
    })

    resumed = SyntheticWorkbenchSession.resume_source_only_run(original._lifecycle.run_directory)
    group = resumed.view()["question_groups"][0]
    assert group["effective_question"]["stem"] == "Which answer is best?"
    assert group["status"] == "approved"
    assert any(item.action.value == "approve" for item in resumed._decisions_by_proposal.values())


def test_registered_source_metadata_allows_its_own_reserved_identity(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Medical-Surgical", "MULTIPLE CHOICE", "1. Which?",
        "a. One", "b. Two", "ANS: B", "Two is correct.",
    ])
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)

    payload = session.materialize_source_only(
        {"display_name": "Medical-Surgical", "slug": "medical_surgical", "prefix": "Med-Surg"},
        registered_preset=True,
    )

    assert payload["run"]["source_metadata"] == {
        "display_name": "Medical-Surgical",
        "slug": "medical_surgical",
        "prefix": "Med-Surg",
    }
    assert session.questions[0].question_id == "PFQ-medical_surgical-000000001"


def test_accepted_duplicate_can_be_reopened_and_excluded() -> None:
    session = SyntheticWorkbenchSession()
    first = QuestionRecord(
        "PFQ-recovery-000000001", 1, "multiple_choice", "Duplicate?",
        (("A", "One"),), ("A",), "Reason.", "Chapter", "PFV2-REC-000001",
    )
    duplicate = replace(first, question_id="PFQ-recovery-000000002", source_record_id="PFV2-REC-000002")
    finding = Finding(
        "PFV2-FIND-QA-000001", duplicate.question_id, "stem", "complete_duplicate_record",
        FindingSeverity.BLOCKING, "Duplicate.", related_question_id=first.question_id,
    )
    session.questions, session.findings, session.proposals = (first, duplicate), (finding,), ()

    session.record_disposition(finding.finding_id, "accept_as_is")
    # The review UI must be able to correct a prior keep-both decision without
    # forcing the operator to replay that decision first.
    excluded = session.record_disposition(finding.finding_id, "exclude_record")
    assert excluded["cases"][0]["status"] == "excluded_record"


def test_complete_question_repair_preserves_completion_answer_text() -> None:
    session = SyntheticWorkbenchSession()
    question = QuestionRecord(
        "PFQ-completion-000000001", 1, "completion", "The pressure is ____ footer.",
        (), ("intracranial pressure",), "Reason.", "Chapter", "PFV2-REC-000001",
    )
    session.questions = (question,)
    session.findings = ()
    session.proposals = ()

    payload = session.save_complete_question_repair(question.question_id, {
        "stem": "The pressure is ____.", "choices": [],
        "correct_answers": ["intracranial pressure"], "rationale": "Reason.",
    })

    repaired = payload["question_groups"][0]["effective_question"]
    assert repaired["stem"] == "The pressure is ____."
    assert repaired["correct_answers"] == ["intracranial pressure"]


def test_source_only_accept_as_is_persists_all_question_findings_through_recovery(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Acceptance", "MULTIPLE CHOICE", "1. Which?",
        "a. First", "b. Second", "ANS: A", "The aBcD qRsT rationale is preserved.",
    ])
    original = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    original.start_pdf_run(pdf)
    payload = original.materialize_source_only({"display_name": "Acceptance", "slug": "acceptance", "prefix": "Acceptance"})
    group = next(item for item in payload["question_groups"] if item["unresolved"])

    accepted = original.accept_question_as_is(group["question_id"])
    accepted_group = next(item for item in accepted["question_groups"] if item["question_id"] == group["question_id"])
    assert accepted_group["accepted_as_is"] is True
    assert accepted_group["has_fix"] is False
    assert accepted_group["unresolved"] is False

    resumed = SyntheticWorkbenchSession.resume_source_only_run(original._lifecycle.run_directory)
    recovered = next(item for item in resumed.view()["question_groups"] if item["question_id"] == group["question_id"])
    assert recovered["accepted_as_is"] is True
    assert recovered["unresolved"] is False


def test_chapter_edit_persists_bulk_update_and_undo_through_source_only_recovery(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Original I", "MULTIPLE CHOICE", "1. First?", "a. One", "ANS: A", "Reason.",
        "2. Second?", "a. Two", "ANS: A", "Reason.",
    ])
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.materialize_source_only({"display_name": "Chapters", "slug": "chapters", "prefix": "Chapters"})
    original = session.questions[0]
    session.questions = session.questions + (replace(session.questions[0], question_id="PFQ-chapters-000000999", chapter=2, chapter_title="Other"),)
    session.edit_chapter(original.chapter, original.chapter_title, 1, "Original")
    assert all(item.chapter_title == "Original" for item in session.questions if item.chapter == 1)
    with pytest.raises(DomainError, match="already assigned"):
        session.edit_chapter(1, "Original", 2, "Duplicate")
    resumed = SyntheticWorkbenchSession.resume_source_only_run(session._lifecycle.run_directory)
    assert all(item.chapter_title == "Original" for item in resumed.questions)
    resumed.undo_chapter_edit(original.chapter, original.chapter_title)
    assert all(item.chapter_title == original.chapter_title for item in resumed.questions)


def test_question_chapter_reassignment_persists_without_changing_question_content(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: First", "MULTIPLE CHOICE", "1. First?", "a. One", "ANS: A", "Reason.",
    ])
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.materialize_source_only({"display_name": "Chapters", "slug": "chapters", "prefix": "Chapters"})
    original = session.questions[0]
    second = replace(
        original,
        question_id="PFQ-chapters-000000999",
        chapter=2,
        chapter_title="Second",
    )
    session.questions = session.questions + (second,)

    session.reassign_question_chapter(original.question_id, 2, "Second")
    reassigned = next(item for item in session.questions if item.question_id == original.question_id)
    assert (reassigned.chapter, reassigned.chapter_title) == (2, "Second")
    assert (reassigned.stem, reassigned.choices, reassigned.correct_answers, reassigned.rationale) == (
        original.stem, original.choices, original.correct_answers, original.rationale,
    )

    resumed = SyntheticWorkbenchSession.resume_source_only_run(session._lifecycle.run_directory)
    recovered = next(item for item in resumed.questions if item.question_id == original.question_id)
    assert (recovered.chapter, recovered.chapter_title) == (2, "Second")


def test_user_proposal_rejects_unchanged_or_unexplained_values() -> None:
    session = SyntheticWorkbenchSession()
    preserved = case(session.view(), "PFV2-FIND-PARSE-000001")["preserved_value"]

    with pytest.raises(DomainError, match="explanation"):
        session.draft_user_proposal(
            "PFV2-FIND-PARSE-000001", preserved, "", requires_source_verification=False
        )
    with pytest.raises(DomainError, match="change"):
        session.draft_user_proposal(
            "PFV2-FIND-PARSE-000001",
            preserved,
            "No actual change.",
            requires_source_verification=False,
        )


def test_editing_user_proposal_replaces_prior_draft_without_authorizing_it() -> None:
    session = SyntheticWorkbenchSession()
    first = session.draft_user_proposal(
        "PFV2-FIND-PARSE-000001",
        [["A", "First"], ["B", "Second option"], ["C", "Third option"]],
        "First draft.",
        requires_source_verification=False,
    )
    first_id = case(first, "PFV2-FIND-PARSE-000001")["proposal"]["proposal_id"]

    second = session.draft_user_proposal(
        "PFV2-FIND-PARSE-000001",
        [["A", "Revised first"], ["B", "Second option"], ["C", "Third option"]],
        "Revised draft with clearer source transcription.",
        requires_source_verification=True,
    )
    second_case = case(second, "PFV2-FIND-PARSE-000001")

    assert second_case["proposal"]["proposal_id"] != first_id
    assert second_case["status"] == "awaiting_decision"
    assert len([item for item in session.proposals if item.finding_id == "PFV2-FIND-PARSE-000001"]) == 1
    assert session.build_isolated_candidate()["candidate"]["applied_proposal_ids"] == []


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
    assert payload["comparison"]["field_changes_require_review"] is True
    assert payload["comparison"]["question_context"][0]["candidate"]["correct_answer_text"]
    assert "unreviewed_comparison_field_changes" in payload["candidate"]["blocking_reasons"]
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
        "cleaner": "native_guarded_page_aware_source_neutral_v2",
        "removed_repeated_lines": 0,
        "stripped_repeated_suffixes": 0,
        "protected_repeated_structures": 13,
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
    assert "matches" not in payload["pipeline"]["identity"]
    assert payload["pipeline"]["identity"]["findings"][0]["candidate_question_ids"] == []
    assert payload["pipeline"]["identity"]["automatic_id_assignments_authorized"] is False
    identity_case = payload["pipeline"]["identity"]["review_cases"][0]
    assert identity_case["parsed_choices"] == [
        ["A", "First option"],
        ["B", "Second option"],
    ]
    assert identity_case["parsed_correct_answers"] == ["B"]

    reviewed = session.record_identity_action(
        "PFV2-REC-000001", "approve", "PFQ-test-000000001"
    )

    assert reviewed["run"]["state"] == "identity_matched"
    assert reviewed["pipeline"]["identity"]["reviewed_id_assignments_authorized"] is True
    assert reviewed["pipeline"]["identity"]["automatic_id_assignments_authorized"] is False
    assert reviewed["candidate"]["state"] == "not_built"

    materialized = session.materialize_identity_review()
    assert materialized["run"]["state"] == "review_ready"
    assert materialized["run"]["parsed_records"] == 1
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
    checkpoint = json.loads(
        (session._lifecycle.run_directory / "audit" / "checkpoint.json").read_text()
    )
    assert checkpoint["identity_actions"] == [
        {
            "action": "approve",
            "record_id": "PFV2-REC-000001",
            "target_question_id": "PFQ-test-000000001",
        }
    ]
    assert checkpoint["comparison_counts"]["candidate_questions"] == 1
    assert "Changed stem?" not in json.dumps(checkpoint)


def test_identity_source_context_includes_adjacent_pages_without_exposing_them_in_run_state(tmp_path) -> None:
    pdf = synthetic_pdf_pages_bytes(
        [
            ["Previous-page-only note."],
            [
                "Chapter 1: Context",
                "MULTIPLE CHOICE",
                "1. Changed stem?",
                "a. First option",
                "b. Second option",
                "ANS: B",
                "Rationale.",
            ],
            ["Next-page-only note."],
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
                "stem": "Original stem?",
            }
        ],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    reviewed = session.match_existing_pack(target)
    record_id = reviewed["pipeline"]["identity"]["review_cases"][0]["record_id"]

    context = session.view_identity_source_context(record_id)

    assert context["temporary"] is True
    assert context["canonical_write_available"] is False
    assert context["page_count"] == 3
    assert context["focus_page_number"] == 2
    assert [(item["page_number"], item["role"]) for item in context["pages"]] == [
        (1, "previous"),
        (2, "current"),
        (3, "next"),
    ]
    assert "Changed stem?" in context["pages"][1]["text"]
    assert "Previous-page-only note." not in json.dumps(session.view())
    assert "Next-page-only note." not in json.dumps(session.view())


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


def test_identity_exclusion_is_explicit_auditable_and_materializes_only_retained_records(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Synthetic PDF",
            "MULTIPLE CHOICE",
            "1. Exact anchor",
            "a. First",
            "b. Second",
            "ANS: A",
            "Rationale.",
            "Chapter 2: Artifacts",
            "MULTIPLE CHOICE",
            "1. Extra parser artifact?",
            "a. Artifact",
            "b. Noise",
            "ANS: A",
            "Metadata fragment.",
        ]
    )
    target = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Exact anchor"}],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    reviewed = session.match_existing_pack(target)
    extra = reviewed["pipeline"]["identity"]["review_cases"][0]["record_id"]

    resolved = session.record_identity_action(extra, "exclude_parser_debris")

    assert resolved["run"]["state"] == "identity_matched"
    assert resolved["pipeline"]["identity"]["review_cases"][0]["status"] == "exclude_parser_debris"
    materialized = session.materialize_identity_review()
    assert materialized["run"]["parsed_records"] == 1
    checkpoint = json.loads(
        (session._lifecycle.run_directory / "audit" / "checkpoint.json").read_text()
    )
    assert checkpoint["identity_actions"] == [{
        "action": "exclude_parser_debris",
        "record_id": extra,
        "target_question_id": "",
    }]


def test_identity_can_keep_source_question_missing_from_old_pack(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Existing", "MULTIPLE CHOICE", "1. Exact anchor",
        "a. First", "b. Second", "ANS: A", "Reason.",
        "Chapter 2: New Source Content", "MULTIPLE CHOICE", "1. New question?",
        "a. First", "b. Second", "ANS: B", "Reason.",
    ])
    target = {
        "format": "prepflow_pack", "pack_id": "test", "questions": [{
            "id": "PFQ-test-000000001", "chapter": 1, "chapter_title": "Existing",
            "type": "mc", "stem": "Exact anchor",
            "choices": [{"label": "A", "text": "First"}, {"label": "B", "text": "Second"}],
            "correct_answers": ["A"], "rationale": "Reason.",
        }],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    reviewed = session.match_existing_pack(target)
    extra = reviewed["pipeline"]["identity"]["review_cases"][0]

    resolved = session.record_identity_action(extra["record_id"], "retain_new_question")

    assert resolved["run"]["state"] == "identity_matched"
    new_id = resolved["pipeline"]["identity"]["review_cases"][0]["selected_target_question_id"]
    assert new_id == "PFQ-test-000000003"
    session.materialize_identity_review()
    session.build_isolated_candidate()
    compared = session.compare_isolated_candidate()
    assert compared["comparison"]["candidate_question_count"] == 2
    assert compared["comparison"]["documented_added_question_ids"] == [new_id]


def test_incomplete_identity_review_resumes_with_content_free_decisions(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: First", "MULTIPLE CHOICE", "1. Changed first?",
        "a. One", "b. Two", "ANS: A", "Reason.",
        "Chapter 2: Second", "MULTIPLE CHOICE", "1. Changed second?",
        "a. One", "b. Two", "ANS: B", "Reason.",
    ])
    target = {
        "format": "prepflow_pack", "pack_id": "test", "questions": [
            {
                "id": "PFQ-test-000000001", "chapter": 1, "stem": "Original first?",
                "choices": [{"label": "A", "text": "One"}, {"label": "A", "text": "Damaged duplicate label"}],
            },
            {"id": "PFQ-test-000000002", "chapter": 2, "stem": "Original second?"},
        ],
    }
    original = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    original.start_pdf_run(pdf)
    payload = original.match_existing_pack(target)
    first = payload["pipeline"]["identity"]["review_cases"][0]
    original.record_identity_action(
        first["record_id"], "approve", first["suggestions"][0]["target_question_id"]
    )

    resumed = SyntheticWorkbenchSession.resume_run(original._lifecycle.run_directory, target)
    view = resumed.view()

    assert view["run"]["state"] == "identity_review"
    statuses = {item["record_id"]: item["status"] for item in view["pipeline"]["identity"]["review_cases"]}
    assert statuses[first["record_id"]] == "approve"
    assert list(statuses.values()).count("pending") == 1


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
    source = session.view_source_page(qa_cases[0]["finding_id"])
    assert source["temporary"] is True
    assert "Which action is expected?" in source["text"]


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


def test_pdf_source_verification_requires_opening_temporary_page_first(tmp_path) -> None:
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
    session.match_existing_pack(target)
    payload = session.materialize_identity_review()
    qa_case = next(item for item in payload["cases"] if "interleaving" in item["damage_type"])
    drafted = session.draft_user_proposal(
        qa_case["finding_id"],
        [["A", "Source-verified choice"], ["B", "Clean choice"]],
        "Corrected from the temporary source page.",
        requires_source_verification=True,
    )
    session.record_action(qa_case["finding_id"], "approve")

    with pytest.raises(DomainError, match="Open the temporary source page"):
        session.record_verification(qa_case["finding_id"])

    source = session.view_source_page(qa_case["finding_id"])
    assert source["page_number"] == 1
    assert source["page_count"] == 1
    assert "Which action is expected?" in source["text"]
    assert source["temporary"] is True
    verified = session.record_verification(qa_case["finding_id"])
    assert case(verified, qa_case["finding_id"])["status"] == "approved"
    reopened = session.view_source_page(qa_case["finding_id"])
    assert reopened["pages"][0]["role"] == "current"
    checkpoint = json.loads(
        (session._lifecycle.run_directory / "audit" / "checkpoint.json").read_text()
    )
    assert checkpoint["verifications"][0]["verified"] is True
    assert checkpoint["proposal_fingerprints"][0]["fingerprint"]
    manifest = (session._lifecycle.run_directory / "run.json").read_text()
    assert "Which action is expected?" not in manifest
    private_proposals = session._lifecycle.run_directory / "artifacts" / "user_proposals.private.json"
    assert private_proposals.is_file()
    assert "Source-verified choice" in private_proposals.read_text()

    resumed = SyntheticWorkbenchSession.resume_run(session._lifecycle.run_directory, target)
    resumed_case = case(resumed.view(), qa_case["finding_id"])
    assert resumed_case["status"] == "approved"
    assert resumed_case["proposal"]["proposed_value"][0] == ["A", "Source-verified choice"]

    resumed.cleanup_run()
    assert resumed._source_pages == ()
    assert resumed._viewed_source_findings == set()
    assert not private_proposals.exists()


def test_source_context_uses_verified_page_range_when_whole_stem_crosses_pages() -> None:
    """A saved parsed stem need not fit within one physical source page."""
    source_pages = (
        "A nurse assesses a patient after a head injury and notes decreasing level of consciousness.",
        "The nurse recognizes these findings as increased intracranial pressure. Source metadata follows.",
    )
    parsed_stem = (
        "A nurse assesses a patient after a head injury and notes decreasing level of consciousness. "
        "The nurse recognizes these findings as increased intracranial pressure."
    )

    assert _source_context_page_indexes(parsed_stem, source_pages) == (0, 1)


def test_source_context_uses_unique_saved_opening_provenance_when_footer_is_attached() -> None:
    source_pages = (
        "A nurse assesses a patient after a head injury and notes decreasing level of consciousness. "
        "The question ends here. Rationale and source metadata follow.",
    )
    parsed_stem = (
        "A nurse assesses a patient after a head injury and notes decreasing level of consciousness. "
        "The question ends here. Powered by TCPDF (www.tcpdf.org)"
    )

    # The TCPDF footer is physically after the rationale, so a whole-stem
    # search fails.  The unique question opening is still recorded as the
    # temporary source provenance; no page is guessed.
    assert _source_context_page_indexes(parsed_stem, source_pages) == (0,)


def test_recovery_restores_empty_answer_collection_before_candidate_build() -> None:
    stored = Proposal(
        "PFV2-PROP-USER-000001", "PFV2-FIND-PARSE-000001",
        "PFQ-test-000000001", "correct_answers", [], ["C"],
        "Verified from the temporary source.", False,
    )

    restored = _restore_private_proposal_collections(stored)

    assert restored.expected_before == ()
    assert restored.proposed_after == ("C",)
    # The stored JSON form remains untouched for checkpoint fingerprinting.
    assert stored.expected_before == []


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



def test_recoverable_runs_are_ordered_by_latest_activity(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Resume", "MULTIPLE CHOICE", "1. Which?",
        "a. First", "ANS: A", "First.",
    ])
    target = {
        "format": "prepflow_pack", "pack_id": "test",
        "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "stem": "Which?"}],
    }

    first = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    first.start_pdf_run(pdf)
    first.match_existing_pack(target)
    second = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    second.start_pdf_run(pdf)
    second.match_existing_pack(target)

    os.utime(first._lifecycle.run_directory, ns=(1, 1))
    os.utime(second._lifecycle.run_directory, ns=(2, 2))

    available = list_recoverable_runs(tmp_path / "runs", {"test"})

    assert [item["run_id"] for item in available] == [
        first._lifecycle.run_directory.name,
        second._lifecycle.run_directory.name,
    ]



def test_active_compared_pdf_run_resumes_to_exact_same_candidate_and_comparison(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(
        [
            "Chapter 1: Resume Test", "MULTIPLE CHOICE",
            "1. Which option?", "a. First", "b. Second", "ANS: A", "First is correct.",
        ]
    )
    target = {
        "format": "prepflow_pack", "pack_id": "test",
        "questions": [{
            "id": "PFQ-test-000000001", "chapter": 1, "chapter_title": "Resume Test",
            "type": "mc", "stem": "Which option?",
            "choices": [{"label": "A", "text": "First"}, {"label": "B", "text": "Second"}],
            "correct_answers": ["A"], "rationale": "First is correct.",
        }],
    }
    original = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    original.start_pdf_run(pdf)
    original.match_existing_pack(target)
    original.materialize_identity_review()
    original.build_isolated_candidate()
    before = original.compare_isolated_candidate()
    run_directory = original._lifecycle.run_directory

    available = list_recoverable_runs(tmp_path / "runs", {"test"})
    assert available == ({
        "run_id": run_directory.name,
        "pack_id": "test",
        "stage": "compared",
        "parsed_records": 1,
        "finding_count": 0,
    },)

    resumed = SyntheticWorkbenchSession.resume_run(run_directory, target)
    after = resumed.view()

    assert after["run"]["state"] == "compared"
    assert after["candidate"] == before["candidate"]
    assert after["comparison"] == before["comparison"]
    assert resumed._source_pages

    resumed.complete_run()
    assert list_recoverable_runs(tmp_path / "runs", {"test"}) == ()
    assert list_completed_runs(tmp_path / "runs", {"test"}) == ({
        "run_id": run_directory.name,
        "pack_id": "test",
        "stage": "completed",
        "parsed_records": 1,
        "candidate_questions": 1,
        "field_changes": 0,
    },)


def test_resume_rejects_target_pack_mismatch(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Resume", "MULTIPLE CHOICE", "1. Which?", "a. First", "ANS: A", "First.",
    ])
    target = {
        "format": "prepflow_pack", "pack_id": "test",
        "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Which?"}],
    }
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)
    wrong = {**target, "pack_id": "wrong"}

    with pytest.raises(DomainError, match="target Pack"):
        SyntheticWorkbenchSession.resume_run(session._lifecycle.run_directory, wrong)


def test_recovered_run_retains_extraction_and_cleaning_metrics(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(["Chapter 1: Resume", "MULTIPLE CHOICE", "1. Which?", "a. First", "ANS: A", "First."])
    target = {"format": "prepflow_pack", "pack_id": "test", "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Which?"}]}
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)
    resumed = SyntheticWorkbenchSession.resume_run(session._lifecycle.run_directory, target)
    assert resumed.view()["pipeline"]["extraction"]["adapter"] == "text_pdf_pages_v1"
    assert resumed.view()["pipeline"]["cleaning"]["cleaner"] == "native_guarded_page_aware_source_neutral_v2"


def test_recovery_advances_completed_identity_actions_to_materialization(tmp_path) -> None:
    pdf = synthetic_pdf_bytes(["Chapter 1: Resume", "MULTIPLE CHOICE", "1. Changed?", "a. First", "ANS: A", "Reason."])
    target = {"format": "prepflow_pack", "pack_id": "test", "questions": [{"id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Original?"}]}
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)
    session.record_identity_action("PFV2-REC-000001", "approve", "PFQ-test-000000001")
    session._lifecycle._write_manifest({**session._lifecycle.manifest(), "stage": "identity_review", "identity_complete": False})
    resumed = SyntheticWorkbenchSession.resume_run(session._lifecycle.run_directory, target)
    assert resumed.view()["run"]["state"] == "identity_matched"
    assert resumed._identity_mapping == {"PFV2-REC-000001": "PFQ-test-000000001"}




def test_matched_identity_can_stage_a_later_verified_stem_repair(tmp_path) -> None:
    pdf = synthetic_pdf_bytes([
        "Chapter 1: Repair", "MULTIPLE CHOICE", "1. Broken stem N/A", "a. enculturation", "ANS: A", "Reason.",
    ])
    target = {"format": "prepflow_pack", "pack_id": "test", "questions": [{
        "id": "PFQ-test-000000001", "chapter": 1, "type": "mc", "stem": "Broken stem.",
    }]}
    session = SyntheticWorkbenchSession(workspace_root=tmp_path / "runs")
    session.start_pdf_run(pdf)
    session.match_existing_pack(target)
    session.record_identity_action("PFV2-REC-000001", "approve", "PFQ-test-000000001")
    staged = session.draft_identity_field_repair("PFV2-REC-000001", "stem", "Broken stem.", "Verified source metadata was not part of the question.")
    assert staged["pipeline"]["identity"]["review_cases"][0]["field_repair_staged"] is True
    materialized = session.materialize_identity_review()
    case = next(item for item in materialized["cases"] if item["field"] == "stem")
    assert case["question_id"] == "PFQ-test-000000001"
    assert {"approve", "reject", "defer"}.issubset(case["allowed_actions"])
    assert case["proposal"]["requires_source_verification"] is True
