import json

from ingestion_v2.domain import Finding, FindingSeverity, Proposal, QuestionRecord
from ingestion_v2.review import build_review_queue
from ingestion_v2.review_view import review_queue_view


def test_review_view_is_source_neutral_and_explicitly_non_promoting() -> None:
    question = QuestionRecord(
        question_id="PFQ-synthetic-000000001",
        chapter=1,
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
    assert payload["capabilities"]["promote_canonical"] is False
    assert "source_path" not in serialized
    assert "filename" not in serialized
    assert "page_number" not in serialized
    assert "original_document" not in serialized
