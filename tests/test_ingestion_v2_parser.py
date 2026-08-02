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
