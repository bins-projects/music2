import json

from compiler.noise_profile import profile_repeated_page_noise


def test_profiler_detects_repeated_edge_line_and_suffix_without_text() -> None:
    pages = []
    for index in range(10):
        suffix = "Repeated notice" if index < 6 else "Different footer"
        pages.append(
            "\n".join(
                [
                    "Repeated notice",
                    f"Question {index}?",
                    f"Educational content {index} Repeated notice",
                    suffix,
                ]
            )
        )
    report = profile_repeated_page_noise("\n\f\n".join(pages))

    assert report["line_candidates"]
    assert report["suffix_candidates"]
    serialized = json.dumps(report)
    assert "Repeated notice" not in serialized
    assert "Educational content" not in serialized
    assert report["detection_only"] is True
    assert report["text_removed"] is False


def test_profiler_does_not_select_repeated_middle_educational_line() -> None:
    pages = []
    for index in range(10):
        pages.append(
            "\n".join(
                [
                    f"Unique header {index}",
                    f"First unique line {index}",
                    f"Second unique line {index}",
                    f"Third unique line {index}",
                    f"Fourth unique line {index}",
                    f"Fifth unique line {index}",
                    "Repeated educational instruction",
                    f"Sixth unique line {index}",
                    f"Seventh unique line {index}",
                    f"Eighth unique line {index}",
                    f"Ninth unique line {index}",
                    f"Tenth unique line {index}",
                    f"Unique footer {index}",
                ]
            )
        )
    report = profile_repeated_page_noise("\n\f\n".join(pages), edge_depth=3)

    assert report["line_candidates"] == []
    assert report["suffix_candidates"] == []


def test_profiler_marks_repeated_answer_structure_ineligible_for_removal() -> None:
    pages = [f"ANS: A\nUnique content {index}" for index in range(10)]

    report = profile_repeated_page_noise("\n\f\n".join(pages))

    assert len(report["line_candidates"]) == 1
    candidate = report["line_candidates"][0]
    assert candidate["educational_structure_shape"] is True
    assert candidate["automatic_removal_eligible"] is False
    assert candidate["classification"] == "protected_repeated_educational_structure"
