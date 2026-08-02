import copy

import pytest

from compiler.repair import (
    RepairError,
    apply_repair,
    create_question_correction_record,
    load_repair_records,
    write_repair_set,
)


def sample_pack() -> dict:
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
                "stem": "Damaged stem a. First action",
                "choices": [
                    {"label": "B", "text": "Second action"},
                    {"label": "C", "text": "Third action"},
                ],
                "correct_answers": ["B"],
                "rationale": "Damaged rationale fragment",
            }
        ],
    }


def approved_record(pack: dict):
    return create_question_correction_record(
        pack,
        question_id="PFQ-test-pack-000000001",
        repair_id="PFQA-APPROVED-FULL-QUESTION",
        replacement_stem="Clean stem?",
        replacement_choices=(
            ("A", "First action"),
            ("B", "Second action"),
            ("C", "Third action"),
        ),
        replacement_correct_answers=("B",),
        replacement_rationale="Clean rationale.",
        damage_type="approved multi-field extraction correction",
    )


def test_full_question_correction_is_atomic_and_candidate_only() -> None:
    canonical = sample_pack()

    candidate = apply_repair(canonical, approved_record(canonical))

    assert canonical["questions"][0]["stem"] == "Damaged stem a. First action"
    assert candidate["questions"][0]["stem"] == "Clean stem?"
    assert [
        choice["label"] for choice in candidate["questions"][0]["choices"]
    ] == ["A", "B", "C"]
    assert candidate["questions"][0]["rationale"] == "Clean rationale."


@pytest.mark.parametrize("field", ["stem", "rationale"])
def test_full_question_correction_rejects_stale_text(field) -> None:
    canonical = sample_pack()
    record = approved_record(canonical)
    changed = copy.deepcopy(canonical)
    changed["questions"][0][field] = "Changed after approval"

    with pytest.raises(RepairError, match="current full shape"):
        apply_repair(changed, record)


def test_full_question_correction_round_trips(tmp_path) -> None:
    canonical = sample_pack()
    record = approved_record(canonical)
    path = write_repair_set([record], tmp_path / "repair-records.json")

    assert load_repair_records(path) == [record]
