from ingestion_v2.comparison import ComparisonReport, FieldChange
from ingestion_v2.comparison_categories import categorize_comparison_changes


def report(*changes) -> ComparisonReport:
    return ComparisonReport(3, 3, True, True, (), tuple(changes), True)


def test_repeated_chapter_title_difference_is_one_metadata_category() -> None:
    changes = tuple(
        FieldChange(
            f"PFQ-test-{number:09d}", "chapter_title",
            "Liver, Gallbladder, and Pancreatic",
            "Liver, Gallbladder, and Pancreatic Disorders",
        )
        for number in range(1, 4)
    )

    categories = categorize_comparison_changes(report(*changes))

    assert len(categories) == 1
    assert categories[0].classification == "repeated_metadata_difference"
    assert len(categories[0].changes) == 3


def test_one_off_url_footer_and_plain_suffix_receive_different_categories() -> None:
    categories = categorize_comparison_changes(
        report(
            FieldChange("PFQ-test-000000001", "stem", "Question?", "Question? Powered by TCPDF (www.tcpdf.org)"),
            FieldChange("PFQ-test-000000002", "stem", "Completion ____.", "Completion ____. N/A"),
        )
    )

    assert {item.classification for item in categories} == {
        "probable_single_contaminant",
        "appended_text_review",
    }


def test_category_ids_are_deterministic_and_content_changes_are_not_invented() -> None:
    change = FieldChange("PFQ-test-000000001", "rationale", "Original", "Different")

    first = categorize_comparison_changes(report(change))
    second = categorize_comparison_changes(report(change))

    assert first == second
    assert first[0].classification == "content_difference_review"
