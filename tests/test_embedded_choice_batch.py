import copy

import pytest

from compiler.repair import RepairError, apply_repair
from compiler.structural_batch import plan_embedded_middle_choices


def pack_with_choices(choices: list[tuple[str, str]]) -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Test Chapter",
                "type": "mc",
                "stem": "Which action is appropriate?",
                "choices": [
                    {"label": label, "text": text}
                    for label, text in choices
                ],
                "correct_answers": ["D"],
                "rationale": "The fourth action is appropriate.",
            }
        ],
    }


@pytest.mark.parametrize(
    ("choices", "missing", "expected"),
    [
        (
            [
                ("A", "First action b. Second action"),
                ("C", "Third action"),
                ("D", "Fourth action"),
            ],
            "B",
            (
                ("A", "First action"),
                ("B", "Second action"),
                ("C", "Third action"),
                ("D", "Fourth action"),
            ),
        ),
        (
            [
                ("A", "First action"),
                ("B", "Second action c) Third action"),
                ("D", "Fourth action"),
            ],
            "C",
            (
                ("A", "First action"),
                ("B", "Second action"),
                ("C", "Third action"),
                ("D", "Fourth action"),
            ),
        ),
    ],
)
def test_exact_embedded_middle_choice_is_planned(
    choices,
    missing,
    expected,
) -> None:
    pack = pack_with_choices(choices)

    plan = plan_embedded_middle_choices(pack, [])

    assert len(plan.proposals) == 1
    assert plan.proposals[0].replacement_choices == expected
    assert plan.proposals[0].replacement_correct_answers == ("D",)
    assert plan.proposals[0].repair_id.endswith(f"-{missing}")
    assert pack["questions"][0]["choices"][0]["text"] == choices[0][1]


def test_marker_without_a_missing_label_is_not_a_repair() -> None:
    pack = pack_with_choices(
        [
            ("A", "Ask the patient about plan b. before discharge."),
            ("B", "Second action"),
            ("C", "Third action"),
            ("D", "Fourth action"),
        ]
    )

    plan = plan_embedded_middle_choices(pack, [])

    assert plan.proposals == ()
    assert plan.review_question_ids == ()


def test_uppercase_prose_marker_is_not_treated_as_embedded_choice() -> None:
    pack = pack_with_choices(
        [
            ("A", "The classification B. Complex is discussed"),
            ("C", "Third action"),
            ("D", "Fourth action"),
        ]
    )

    plan = plan_embedded_middle_choices(pack, [])

    assert plan.proposals == ()
    assert plan.review_question_ids == ("PFQ-test-pack-000000001",)


def test_multiple_matching_markers_stay_in_review() -> None:
    pack = pack_with_choices(
        [
            ("A", "First action b. Possible split b. Another split"),
            ("C", "Third action"),
            ("D", "Fourth action"),
        ]
    )

    plan = plan_embedded_middle_choices(pack, [])

    assert plan.proposals == ()
    assert plan.review_question_ids == ("PFQ-test-pack-000000001",)


def test_planned_repair_rejects_stale_choice_text() -> None:
    pack = pack_with_choices(
        [
            ("A", "First action b. Second action"),
            ("C", "Third action"),
            ("D", "Fourth action"),
        ]
    )
    record = plan_embedded_middle_choices(pack, []).proposals[0]
    changed = copy.deepcopy(pack)
    changed["questions"][0]["choices"][0]["text"] = "Changed text"

    with pytest.raises(RepairError, match="no longer matches current choices"):
        apply_repair(changed, record)
