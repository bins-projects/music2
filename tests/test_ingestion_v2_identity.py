from copy import deepcopy
import json

import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.identity import match_existing_pack_identity
from ingestion_v2.parser import ParseBatch, ParsedRecord


def record(record_id: str, stem: str, *, chapter: int = 1) -> ParsedRecord:
    return ParsedRecord(
        record_id=record_id,
        chapter=chapter,
        chapter_title="Chapter",
        source_question_number=1,
        question_type="multiple_choice",
        stem=stem,
        choices=(("A", "Choice"),),
        correct_answers=("A",),
        rationale="Rationale",
    )


def batch(*records: ParsedRecord) -> ParseBatch:
    return ParseBatch(tuple(records), (), "test")


def question(number: int, stem: str, *, chapter: int = 1) -> dict:
    return {
        "id": f"PFQ-test-00000000{number}",
        "chapter": chapter,
        "type": "mc",
        "stem": stem,
        "choices": [{"label": "A", "text": "Choice"}],
        "correct_answers": ["A"],
        "rationale": "Rationale",
    }


def pack(*questions: dict) -> dict:
    return {"format": "prepflow_pack", "version": "1.0", "pack_id": "test", "questions": list(questions)}


def test_unique_exact_normalized_stems_authorize_complete_identity() -> None:
    parsed = batch(record("PFV2-REC-000001", "Vitamin B-complex?"), record("PFV2-REC-000002", "Second   stem"))
    target = pack(question(1, "vitamin b-complex?"), question(2, "second stem"))

    report = match_existing_pack_identity(parsed, target)

    assert report.complete is True
    assert report.stable_id_by_record_id == {
        "PFV2-REC-000001": "PFQ-test-000000001",
        "PFV2-REC-000002": "PFQ-test-000000002",
    }
    assert report.view()["automatic_id_assignments_authorized"] is True


def test_changed_stem_is_not_paired_by_position_or_question_number() -> None:
    parsed = batch(record("PFV2-REC-000001", "Changed text"))
    target = pack(question(1, "Original text"))

    report = match_existing_pack_identity(parsed, target)

    assert report.complete is False
    assert report.matches == ()
    assert report.findings[0].finding_code == "changed_or_unmatched_identity"
    with pytest.raises(DomainError, match="cannot be authorized"):
        _ = report.stable_id_by_record_id


def test_duplicate_exact_stems_are_ambiguous_and_disclose_no_text() -> None:
    parsed = batch(record("PFV2-REC-000001", "Repeated stem"))
    target = pack(question(1, "Repeated stem"), question(2, "Repeated stem"))

    report = match_existing_pack_identity(parsed, target)
    encoded = json.dumps(report.view())

    assert report.findings[0].finding_code == "ambiguous_exact_identity"
    assert report.findings[0].candidate_question_ids == (
        "PFQ-test-000000001",
        "PFQ-test-000000002",
    )
    assert "Repeated stem" not in encoded


def test_same_stem_in_different_chapter_does_not_cross_assign() -> None:
    parsed = batch(record("PFV2-REC-000001", "Shared stem", chapter=2))
    target = pack(question(1, "Shared stem", chapter=1))

    report = match_existing_pack_identity(parsed, target)

    assert report.matches == ()
    assert report.target_only_question_ids == ("PFQ-test-000000001",)


def test_matcher_is_deterministic_and_does_not_mutate_inputs() -> None:
    parsed = batch(record("PFV2-REC-000002", "Second"), record("PFV2-REC-000001", "First"))
    target = pack(question(1, "First"), question(2, "Second"))
    before = deepcopy(target)

    first = match_existing_pack_identity(parsed, target)
    second = match_existing_pack_identity(parsed, target)

    assert first == second
    assert target == before
    assert [item.record_id for item in first.matches] == ["PFV2-REC-000002", "PFV2-REC-000001"]


@pytest.mark.parametrize(
    "target",
    [
        {},
        {"format": "wrong", "pack_id": "test", "questions": []},
        {"format": "prepflow_pack", "pack_id": "test", "questions": [{}]},
        pack(question(1, "One"), question(1, "Duplicate ID")),
    ],
)
def test_malformed_identity_targets_are_rejected(target: dict) -> None:
    with pytest.raises(DomainError):
        match_existing_pack_identity(batch(), target)
