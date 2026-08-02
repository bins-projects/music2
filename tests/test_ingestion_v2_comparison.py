import pytest

from ingestion_v2.comparison import compare_candidate, comparison_view
from ingestion_v2.domain import Candidate, DomainError, QuestionRecord


def question(number: int, *, answer: str = "A") -> QuestionRecord:
    return QuestionRecord(
        question_id=f"PFQ-synthetic-{number:09d}",
        chapter=1,
        question_type="mc",
        stem=f"Synthetic stem {number}",
        choices=(("A", "First"), ("B", "Second")),
        correct_answers=(answer,),
    )


def test_comparison_reports_stably_ordered_field_changes() -> None:
    benchmark = (question(2), question(1))
    candidate = Candidate((question(2, answer="B"), question(1, answer="B")))

    report = compare_candidate(candidate, benchmark)

    assert [(item.question_id, item.field) for item in report.field_changes] == [
        ("PFQ-synthetic-000000001", "correct_answers"),
        ("PFQ-synthetic-000000002", "correct_answers"),
    ]
    assert comparison_view(report)["field_change_count"] == 2


def test_comparison_requires_exact_stable_id_set() -> None:
    candidate = Candidate((question(1),))

    with pytest.raises(DomainError, match="stable ID sets differ"):
        compare_candidate(candidate, (question(1), question(2)))


def test_unchanged_candidate_completes_with_zero_differences() -> None:
    benchmark = (question(1), question(2))

    report = compare_candidate(Candidate(benchmark), benchmark)

    assert report.complete is True
    assert report.stable_ids_exact is True
    assert report.field_changes == ()
