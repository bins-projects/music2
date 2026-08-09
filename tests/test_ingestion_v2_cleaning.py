import pytest

from ingestion_v2.cleaning import GuardedPageAwareCleaner, _clean_page
from ingestion_v2.domain import DomainError
from ingestion_v2.parser import ExistingParserAdapter


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
        "\n".join(
            (
                f"Question body {index}.",
                "This sentence is repeated in the middle of every page.",
                "Shared non-educational footer",
            )
        )
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert "Shared non-educational footer" not in result.text
    assert result.text.count("This sentence is repeated in the middle of every page.") == 3
    assert result.removed_repeated_lines == 3


def test_cleaner_preserves_repeated_answer_shapes_even_at_page_edges() -> None:
    source = "\n\f\n".join(
        "\n".join(
            (
                "ANS: D",
                f"{index + 1}. Question {index}?",
                "a. First choice",
                "b. Second choice",
            )
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


def test_cleaner_strips_repeated_marketplace_attribution_inside_choices() -> None:
    watermark = (
        "Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
        "Downloaded by: learner@example.com | learner@example.com\n"
        "Distribution of this document is illegal\n"
        "Want to earn $1.236\n"
        "extra per year?\n"
    )
    source = "\n\f\n".join(
        (
            f"{index + 1}. Question {index}?\n"
            "A. First choice\n"
            f"B {watermark}"
            "Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
            ". Second choice\n"
            "C. Third choice"
        )
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert "Downloaded by:" not in result.text
    assert "Distribution of this document is illegal" not in result.text
    assert "Want to earn" not in result.text
    assert "extra per year?" not in result.text
    assert "A. First choice" in result.text
    assert "B\n. Second choice" in result.text
    assert result.removed_repeated_lines > 0


def test_cleaner_keeps_answer_keys_after_marketplace_attribution() -> None:
    watermark = (
        "Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
        "Downloaded by: learner@example.com | learner@example.com\n"
        "Distribution of this document is illegal\n"
        "Want to earn $1.236\n"
        "extra per year?\n"
    )
    source = "\n\f\n".join(
        (
            f"{index + 1}. Question {index}?\n"
            "A. First choice\n"
            f"B {watermark}"
            "Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
            ". Second choice\n"
            "C. Third choice\n"
            "ANS: B\n"
            "The rationale."
        )
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert result.text.count("ANS: B") == 3
    assert result.text.count("The rationale.") == 3
    assert "Downloaded by:" not in result.text


@pytest.mark.parametrize("label", ("A", "B", "D", "H", "A.", "B)"))
def test_cleaner_preserves_standalone_choice_labels_at_page_edges(label: str) -> None:
    source = "\n\f\n".join(
        f"{label}\nUnique educational content {index}."
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert sum(line == label for line in result.text.splitlines()) == 3
    assert result.removed_repeated_lines == 0
    assert result.protected_repeated_structures >= 1


def test_suffix_cleanup_cannot_remove_answer_key_payloads() -> None:
    page = (
        "ANS: B",
        "ANS: D",
        "ANS: B, D",
        "ANSWER: C",
        "CORRECT ANSWER: A",
        "Ordinary repeated footer B",
    )

    cleaned, removed, stripped = _clean_page(page, {"B", "D"})

    assert cleaned == (
        "ANS: B",
        "ANS: D",
        "ANS: B, D",
        "ANSWER: C",
        "CORRECT ANSWER: A",
        "Ordinary repeated footer",
    )
    assert removed == 0
    assert stripped == 1


def test_marketplace_cleanup_preserves_complete_records_through_parser() -> None:
    pages = []
    for index in range(3):
        heading = (
            "Chapter 1: Synthetic Safety\nMULTIPLE CHOICE\n"
            if index == 0
            else ""
        )
        pages.append(
            heading
            + f"{index + 1}. Which synthetic option is expected?\n"
            + "A. First choice"
        )
        pages.append(
            "B Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
            "Downloaded by: learner@example.com | learner@example.com\n"
            "Distribution of this document is illegal\n"
            "Want to earn $1.236\n"
            "extra per year?\n"
            "Stuvia.com - The Marketplace to Buy and Sell your Study Material\n"
            ". Second choice\n"
            "C. Third choice\n"
            "D. Fourth choice\n"
            "ANS: B\n"
            "The second choice is expected.\n"
            "DIF: Synthetic"
        )

    cleaned = GuardedPageAwareCleaner().clean("\n\f\n".join(pages))
    batch = ExistingParserAdapter().parse(cleaned.text)

    assert "Downloaded by:" not in cleaned.text
    assert cleaned.text.count("ANS: B") == 3
    assert len(batch.records) == 3
    assert batch.findings == ()
    for record in batch.records:
        assert record.choices == (
            ("A", "First choice"),
            ("B", "Second choice"),
            ("C", "Third choice"),
            ("D", "Fourth choice"),
        )
        assert record.correct_answers == ("B",)
        assert record.rationale == "The second choice is expected."


@pytest.mark.parametrize(
    "header",
    ("MULTIPLE CHOICE", "MULTIPLE RESPONSE", "COMPLETION", "ORDERING"),
)
def test_cleaner_preserves_parser_section_headers_at_page_edges(header: str) -> None:
    source = "\n\f\n".join(
        f"{header}\nUnique educational content {index}."
        for index in range(3)
    )

    result = GuardedPageAwareCleaner().clean(source)

    assert sum(line == header for line in result.text.splitlines()) == 3
    assert result.removed_repeated_lines == 0
    assert result.protected_repeated_structures >= 1


def test_completion_section_headers_survive_cleaning_and_control_parser_type() -> None:
    question_pages = "\n\f\n".join(
        (
            "Completion\n"
            f"{index + 1}. What is the calculated dose? _____\n"
            f"ANS: {index + 1}\n"
            "The calculated dose is expected.\n"
            "DIF: Synthetic"
        )
        for index in range(3)
    )
    source = "Chapter 4: Dosage Calculation\n\f\n" + question_pages

    cleaned = GuardedPageAwareCleaner().clean(source)
    batch = ExistingParserAdapter().parse(cleaned.text)

    assert cleaned.text.count("Completion") == 3
    assert len(batch.records) == 3
    assert batch.findings == ()
    assert all(record.question_type == "completion" for record in batch.records)
    assert [record.correct_answers for record in batch.records] == [
        ("1",),
        ("2",),
        ("3",),
    ]
    assert all(not record.choices for record in batch.records)
