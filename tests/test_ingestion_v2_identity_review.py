import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.identity import match_existing_pack_identity
from ingestion_v2.identity_review import authorize_reviewed_identity, build_identity_review_cases
from ingestion_v2.parser import ParseBatch, ParsedRecord


def record(record_id: str, stem: str, chapter: int = 1) -> ParsedRecord:
    return ParsedRecord(record_id, chapter, "Chapter", 1, "multiple_choice", stem, (), (), "")


def question(number: int, stem: str, chapter: int = 1) -> dict:
    return {"id": f"PFQ-test-00000000{number}", "chapter": chapter, "type": "mc", "stem": stem}


def setup_review():
    batch = ParseBatch(
        (record("PFV2-REC-000001", "Exact anchor"), record("PFV2-REC-000002", "Changed beta wording")),
        (),
        "test",
    )
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [question(1, "Exact anchor"), question(2, "Original beta wording"), question(3, "Unrelated")],
    }
    report = match_existing_pack_identity(batch, pack)
    return batch, pack, report


def test_review_suggestions_are_ranked_but_not_authorized() -> None:
    batch, pack, report = setup_review()

    cases = build_identity_review_cases(batch, pack, report)

    assert cases[0].record_id == "PFV2-REC-000002"
    assert cases[0].suggestions[0].target_question_id == "PFQ-test-000000002"
    assert cases[0].suggestions[0].similarity > cases[0].suggestions[1].similarity
    assert report.matches == (report.matches[0],)
    with pytest.raises(DomainError, match="incomplete"):
        authorize_reviewed_identity(report, cases, {})


def test_approval_can_authorize_only_displayed_unique_suggestion() -> None:
    batch, pack, report = setup_review()
    # Remove the unrelated target so complete one-to-one accounting is possible.
    pack["questions"].pop()
    report = match_existing_pack_identity(batch, pack)
    cases = build_identity_review_cases(batch, pack, report)

    mapping = authorize_reviewed_identity(
        report, cases, {"PFV2-REC-000002": "PFQ-test-000000002"}
    )

    assert mapping == {
        "PFV2-REC-000001": "PFQ-test-000000001",
        "PFV2-REC-000002": "PFQ-test-000000002",
    }
    with pytest.raises(DomainError, match="displayed suggestion"):
        authorize_reviewed_identity(report, cases, {"PFV2-REC-000002": "PFQ-test-999999999"})


def test_suggestions_never_cross_chapters_and_order_is_stable() -> None:
    batch = ParseBatch((record("PFV2-REC-000001", "Changed", chapter=2),), (), "test")
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [question(1, "Changed", chapter=1), question(2, "Candidate B", chapter=2), question(3, "Candidate A", chapter=2)],
    }
    report = match_existing_pack_identity(batch, pack)

    cases = build_identity_review_cases(batch, pack, report)

    assert [item.target_question_id for item in cases[0].suggestions] == [
        "PFQ-test-000000002",
        "PFQ-test-000000003",
    ]


def test_explicit_exclusion_can_complete_extra_parsed_record_accounting() -> None:
    batch = ParseBatch(
        (
            record("PFV2-REC-000001", "Exact anchor"),
            record("PFV2-REC-000002", "DIF:"),
        ),
        (),
        "test",
    )
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [question(1, "Exact anchor")],
    }
    report = match_existing_pack_identity(batch, pack)
    cases = build_identity_review_cases(batch, pack, report)

    mapping = authorize_reviewed_identity(
        report, cases, {}, {"PFV2-REC-000002"}
    )

    assert mapping == {"PFV2-REC-000001": "PFQ-test-000000001"}
    with pytest.raises(DomainError, match="incomplete"):
        authorize_reviewed_identity(report, cases, {}, set())


def test_explicit_new_identity_preserves_question_missing_from_old_pack() -> None:
    batch = ParseBatch(
        (
            record("PFV2-REC-000001", "Exact anchor"),
            record("PFV2-REC-000002", "Legitimate new source question"),
        ),
        (), "test",
    )
    pack = {
        "format": "prepflow_pack", "pack_id": "test",
        "questions": [question(1, "Exact anchor")],
    }
    report = match_existing_pack_identity(batch, pack)
    cases = build_identity_review_cases(batch, pack, report)

    mapping = authorize_reviewed_identity(
        report, cases, {}, set(),
        {"PFV2-REC-000002": "PFQ-test-000000004"},
    )

    assert mapping["PFV2-REC-000002"] == "PFQ-test-000000004"
