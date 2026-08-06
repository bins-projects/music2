import pytest

from ingestion_v2.cleaning import GuardedPageAwareCleaner
from ingestion_v2.domain import DomainError


def test_cleaner_removes_repeated_noise_and_preserves_educational_structure() -> None:
    pages = [
        "\n".join(
            (
                "Repeated source notice",
                "ANS: A",
                f"{index + 1}. Synthetic question {index}?",
                f"a. Synthetic answer {index} Repeated source notice",
            )
        )
        for index in range(10)
    ]
    source = "\n\f\n".join(pages)

    result = GuardedPageAwareCleaner().clean(source)

    assert "Repeated source notice" not in result.text
    assert result.text.count("ANS: A") == 10
    assert result.text.count("Synthetic question") == 10
    assert result.removed_repeated_lines == 10
    assert result.stripped_repeated_suffixes == 10
    assert result.protected_repeated_structures >= 1
    assert result.meaning_repairs == 0
    assert result.source_specific_rules == 0


def test_cleaner_is_source_neutral_and_idempotent_for_clean_synthetic_text() -> None:
    source = "Chapter 1: Synthetic\n1. Question?\na. First\nANS: A\nRationale.\n"
    cleaner = GuardedPageAwareCleaner()

    first = cleaner.clean(source)
    second = cleaner.clean(first.text)

    assert first.text == second.text
    assert first.removed_repeated_lines == 0
    assert first.stripped_repeated_suffixes == 0


def test_cleaner_rejects_empty_input() -> None:
    with pytest.raises(DomainError, match="non-empty"):
        GuardedPageAwareCleaner().clean("\n")

def test_cleaner_removes_only_repeated_non_educational_page_edge_lines() -> None:
    source = "\n\f\n".join(
        (
            f"Question body {index}.",
            "This sentence is repeated in the middle of every page.",
            "Shared non-educational footer",
        )
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert "Shared non-educational footer" not in result.text
    assert result.text.count("This sentence is repeated in the middle of every page.") == 3
    assert result.removed_repeated_lines == 3


def test_cleaner_preserves_repeated_answer_shapes_even_at_page_edges() -> None:
    source = "\n\f\n".join(
        (
            "ANS: D",
            f"{index + 1}. Question {index}?",
            "a. First choice",
            "b. Second choice",
        )
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert result.text.count("ANS: D") == 3
    assert result.removed_repeated_lines == 0
    assert result.protected_repeated_structures >= 1


def test_cleaner_preserves_a_rationale_across_a_page_break() -> None:
    source = (
        "1. Question?\n"
        "a. First\n"
        "b. Second\n"
        "ANS: A\n"
        "The rationale begins on this page"
        "\n\f\n"
        "and continues on the next page."
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert "The rationale begins on this page\n\f\nand continues on the next page." in result.text
    assert result.removed_repeated_lines == 0
    assert result.stripped_repeated_suffixes == 0
