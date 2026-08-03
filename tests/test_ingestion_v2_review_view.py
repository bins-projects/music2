import json

from ingestion_v2.domain import Finding, FindingSeverity, Proposal, QuestionRecord
from ingestion_v2.review import build_review_queue
from ingestion_v2.review_view import review_queue_view


def test_review_view_is_source_neutral_and_explicitly_non_promoting() -> None:
    question = QuestionRecord(
        question_id="PFQ-synthetic-000000001",
        chapter=1,
        chapter_title="Source Chapter Name",
        source_record_id="PFV2-REC-000001",
        question_type="mc",
        stem="Preserved synthetic damage",
        choices=(("A", "First"), ("B", "Second")),
        correct_answers=("A",),
    )
    finding = Finding(
        finding_id="PFV2-FIND-0001",
        question_id=question.question_id,
        field="stem",
        damage_type="synthetic_damage",
        severity=FindingSeverity.BLOCKING,
        explanation="Synthetic explanation.",
    )
    proposal = Proposal(
        proposal_id="PFV2-PROP-0001",
        finding_id=finding.finding_id,
        question_id=question.question_id,
        field="stem",
        expected_before=question.stem,
        proposed_after="Reviewed synthetic value",
        explanation="Synthetic correction explanation.",
    )

    payload = review_queue_view(
        build_review_queue((question,), (finding,), (proposal,))
    )
    serialized = json.dumps(payload)

    assert payload["cases"][0]["preserved_value"] == "Preserved synthetic damage"
    assert payload["cases"][0]["status"] == "awaiting_decision"
    assert payload["cases"][0]["chapter_title"] == "Source Chapter Name"
    assert payload["cases"][0]["source_record_id"] == "PFV2-REC-000001"
    assert payload["cases"][0]["answer_choice_context"] is None
    assert payload["capabilities"]["promote_canonical"] is False
    assert "source_path" not in serialized
    assert "filename" not in serialized
    assert "page_number" not in serialized
    assert "original_document" not in serialized


def test_answer_review_includes_choice_text_for_broken_and_corrected_context() -> None:
    question = QuestionRecord(
        question_id="PFQ-synthetic-000000002",
        chapter=2,
        chapter_title="Context Chapter",
        question_type="mc",
        stem="Which finding is expected?",
        choices=(("A", "First finding"), ("C", "Correct finding")),
        correct_answers=("C", "A", "E"),
    )
    finding = Finding(
        finding_id="PFV2-FIND-ANSWER-0002",
        question_id=question.question_id,
        field="correct_answers",
        damage_type="correct_answer_without_choice",
        severity=FindingSeverity.BLOCKING,
        explanation="The parsed answer contains damaged extra labels.",
    )
    proposal = Proposal(
        proposal_id="PFV2-PROP-ANSWER-0002",
        finding_id=finding.finding_id,
        question_id=question.question_id,
        field="correct_answers",
        expected_before=question.correct_answers,
        proposed_after=("C",),
        explanation="Source verification supports C.",
    )

    item = review_queue_view(build_review_queue((question,), (finding,), (proposal,)))["cases"][0]

    assert item["preserved_value"] == ("C", "A", "E")
    assert item["proposal"]["proposed_value"] == ("C",)
    assert item["answer_choice_context"] == [["A", "First finding"], ["C", "Correct finding"]]
