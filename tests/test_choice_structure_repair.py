import copy

import pytest

from compiler.repair import (
    RepairError,
    apply_repair,
    create_choice_structure_repair_record,
    load_repair_records,
    write_repair_set,
)


def damaged_pack() -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Assessment",
                "type": "mc",
                "stem": "Which classification is correct?",
                "choices": [
                    {"label": "A", "text": "First classification"},
                    {"label": "B", "text": "Second classification"},
                    {"label": "C", "text": "Third classification"},
                    {"label": "D", "text": "Fourth classification"},
                    {"label": "D", "text": "Leaked neighboring choice"},
                ],
                "correct_answers": ["A"],
                "rationale": "The third classification is correct.",
            }
        ],
    }


def approved_record(pack: dict):
    question = pack["questions"][0]
    retained = tuple(
        (choice["label"], choice["text"])
        for choice in question["choices"][:4]
    )
    return create_choice_structure_repair_record(
        pack,
        question_id=question["id"],
        repair_id="PFQA-TEST-APPROVED-STRUCTURE",
        replacement_choices=retained,
        replacement_correct_answers=("C",),
        damage_type="approved source-neutral structural correction",
    )


def test_approved_choice_and_answer_correction_is_atomic_and_candidate_only():
    canonical = damaged_pack()

    candidate = apply_repair(canonical, approved_record(canonical))

    assert len(canonical["questions"][0]["choices"]) == 5
    assert canonical["questions"][0]["correct_answers"] == ["A"]
    assert len(candidate["questions"][0]["choices"]) == 4
    assert candidate["questions"][0]["correct_answers"] == ["C"]


def test_choice_structure_correction_rejects_stale_choices():
    canonical = damaged_pack()
    record = approved_record(canonical)
    changed = copy.deepcopy(canonical)
    changed["questions"][0]["choices"][4]["text"] = "Changed text"

    with pytest.raises(RepairError, match="no longer matches current choices"):
        apply_repair(changed, record)


def test_choice_structure_correction_rejects_stale_answers():
    canonical = damaged_pack()
    record = approved_record(canonical)
    changed = copy.deepcopy(canonical)
    changed["questions"][0]["correct_answers"] = ["B"]

    with pytest.raises(RepairError, match="no longer matches current answers"):
        apply_repair(changed, record)


def test_choice_structure_record_round_trips(tmp_path):
    canonical = damaged_pack()
    record = approved_record(canonical)
    path = write_repair_set([record], tmp_path / "repair-records.json")

    assert load_repair_records(path) == [record]


def test_choice_structure_correction_rejects_answer_without_retained_choice():
    canonical = damaged_pack()
    question = canonical["questions"][0]
    retained = tuple(
        (choice["label"], choice["text"])
        for choice in question["choices"][:4]
    )

    with pytest.raises(RepairError, match="missing choice"):
        create_choice_structure_repair_record(
            canonical,
            question_id=question["id"],
            repair_id="PFQA-TEST-INVALID-ANSWER",
            replacement_choices=retained,
            replacement_correct_answers=("E",),
            damage_type="invalid test proposal",
        )
