import pytest

from ingestion_v2.comparison import compare_candidate
from ingestion_v2.comparison_groups import (
    apply_exact_contaminant_group,
    detect_exact_contaminant_groups,
)
from ingestion_v2.domain import Candidate, DomainError, QuestionRecord


GARBAGE = "Stuvia.com - The Marketplace to Buy and Sell your Study Material"


def question(number: int, *, stem: str, choices=None) -> QuestionRecord:
    return QuestionRecord(
        question_id=f"PFQ-test-{number:09d}",
        chapter=1,
        chapter_title="Clinical Chapter",
        question_type="mc",
        stem=stem,
        choices=choices or (("A", "First"), ("C", "Correct choice")),
        correct_answers=("C",),
        rationale="Rationale.",
    )


def test_exact_garbage_suffix_groups_across_stems_and_choices() -> None:
    benchmark = (
        question(1, stem="First stem"),
        question(2, stem="Second stem"),
    )
    candidate = Candidate(
        (
            question(1, stem="First stem" + GARBAGE),
            question(
                2,
                stem="Second stem",
                choices=(("A", "First" + GARBAGE), ("C", "Correct choice")),
            ),
        )
    )

    groups = detect_exact_contaminant_groups(compare_candidate(candidate, benchmark))

    assert len(groups) == 1
    assert groups[0].contaminant == GARBAGE
    assert {(item.question_id, item.field) for item in groups[0].occurrences} == {
        ("PFQ-test-000000001", "stem"),
        ("PFQ-test-000000002", "choices"),
    }


def test_group_approval_changes_only_exact_targets_and_recomparison_is_clean() -> None:
    benchmark = (question(1, stem="First stem"), question(2, stem="Second stem"))
    candidate = Candidate(
        (question(1, stem="First stem" + GARBAGE), question(2, stem="Second stem" + GARBAGE))
    )
    group = detect_exact_contaminant_groups(compare_candidate(candidate, benchmark))[0]

    repaired, applied = apply_exact_contaminant_group(candidate, benchmark, group.group_id)

    assert applied == group
    assert compare_candidate(repaired, benchmark).field_changes == ()
    assert any(group.group_id in event for event in repaired.audit_events)


def test_repeated_legitimate_suffix_and_single_garbage_occurrence_do_not_group() -> None:
    benchmark = (question(1, stem="First"), question(2, stem="Second"))
    legitimate = Candidate((question(1, stem="First Disorders"), question(2, stem="Second Disorders")))
    single = Candidate((question(1, stem="First" + GARBAGE), benchmark[1]))

    assert detect_exact_contaminant_groups(compare_candidate(legitimate, benchmark)) == ()
    assert detect_exact_contaminant_groups(compare_candidate(single, benchmark)) == ()


def test_group_application_refuses_unknown_or_stale_scope() -> None:
    benchmark = (question(1, stem="First"), question(2, stem="Second"))
    candidate = Candidate((question(1, stem="First" + GARBAGE), question(2, stem="Second" + GARBAGE)))

    with pytest.raises(DomainError, match="missing or no longer current"):
        apply_exact_contaminant_group(candidate, benchmark, "PFV2-GROUP-unknown")
