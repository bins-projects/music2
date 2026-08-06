import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.parser import ExistingParserAdapter
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.review import ReviewStatus, build_review_queue


SYNTHETIC_TEXT = """Chapter 1: Synthetic Safety
MULTIPLE CHOICE
1. Which synthetic option is expected?
a. First option
b. Second option
c. Third option
ANS: B
The second option is expected.
DIF: Synthetic

2. Which record has a deliberately missing first choice? Recovered-looking text
b. Second option
c. Third option
ANS: A
This remains damaged rather than being silently reconstructed.
DIF: Synthetic
"""


def test_adapter_parses_structure_but_performs_no_automatic_repairs() -> None:
    batch = ExistingParserAdapter().parse(SYNTHETIC_TEXT)

    assert len(batch.records) == 2
    assert batch.automatic_repairs == 0
    assert [label for label, _ in batch.records[1].choices] == ["B", "C"]
    assert batch.records[1].stem.endswith("Recovered-looking text")
    assert {finding.damage_type for finding in batch.findings} == {
        "noncanonical_choice_sequence",
        "correct_answer_without_choice",
    }


def test_parser_findings_reach_real_review_queue_after_separate_id_match() -> None:
    batch = ExistingParserAdapter().parse(SYNTHETIC_TEXT)
    questions, findings = materialize_matched_batch(
        batch,
        {
            "PFV2-REC-000001": "PFQ-synthetic-000000001",
            "PFV2-REC-000002": "PFQ-synthetic-000000002",
        },
    )

    queue = build_review_queue(questions, findings)

    assert len(queue.cases) == 2
    assert all(case.question.question_id == "PFQ-synthetic-000000002" for case in queue.cases)
    assert all(case.status is ReviewStatus.NEEDS_PROPOSAL for case in queue.cases)
    assert all(case.question.stem.endswith("Recovered-looking text") for case in queue.cases)
    assert queue.blocking_case_count == 2


def test_stable_id_mapping_must_cover_every_record_exactly() -> None:
    batch = ExistingParserAdapter().parse(SYNTHETIC_TEXT)

    with pytest.raises(DomainError, match="exactly"):
        materialize_matched_batch(
            batch,
            {"PFV2-REC-000001": "PFQ-synthetic-000000001"},
        )


def test_parser_rejects_empty_input() -> None:
    with pytest.raises(DomainError, match="non-empty"):
        ExistingParserAdapter().parse("\n\n")


def test_adapter_reassembles_a_question_split_across_pdf_pages() -> None:
    text = """Chapter 1: Nursing Theory
MULTIPLE CHOICE
8. The student nurse is planning care for a patient who believes that Western
medicine is effective but not always accurate and recognizes which nursing theory
would best explain the patient's health practices?
a. Nursing: Human Science and Human Care
b. Theory of Cultural Care Diversity and Universality
Document shared on https://example.invalid/source
\f
c. Theory of Nursing as Caring
d. Five caring processes
ANS: B
Leininger describes patient care and its relationship to cultural diversity.
Swanson's five caring processes include maintaining belief, knowing, being with,
doing for, and enabling.
DIF: Understanding OBJ: 2.4 TOP: Diagnosis

9. The nurse identifies which nursing theorist describes the nurse-patient relationship?
a. First choice
b. Second choice
c. Third choice
d. Fourth choice
ANS: A
The rationale for question nine.
"""

    batch = ExistingParserAdapter().parse(text)

    assert len(batch.records) == 2
    question_eight = batch.records[0]
    assert question_eight.source_question_number == 8
    assert question_eight.choices == (
        ("A", "Nursing: Human Science and Human Care"),
        ("B", "Theory of Cultural Care Diversity and Universality Document shared on https://example.invalid/source"),
        ("C", "Theory of Nursing as Caring"),
        ("D", "Five caring processes"),
    )
    assert question_eight.correct_answers == ("B",)
    assert "Leininger describes patient care" in question_eight.rationale
    assert batch.records[1].source_question_number == 9
