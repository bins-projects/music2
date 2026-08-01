import json
from pathlib import Path

import pytest

from compiler.repair import (
    Finding,
    RepairError,
    StemChoiceSplitRecord,
    apply_repair,
    create_stem_choice_split_record,
    load_repair_records,
    write_repair_set,
)
from tests.test_repair import sample_pack


def damaged_pack() -> dict:
    pack = sample_pack()
    question = pack["questions"][0]
    question["stem"] = "Which action? a. First action"
    question["choices"] = [
        {"label": "B", "text": "Second action"},
        {"label": "C", "text": "Third action"},
    ]
    question["correct_answers"] = ["C"]
    return pack


def structural_record(pack: dict) -> StemChoiceSplitRecord:
    return create_stem_choice_split_record(
        pack,
        Finding("STRUCT-1", "PFQ-test-pack-000000001", "stem", "absorbed choice"),
        "Which action?",
        insert_label="A",
        insert_text="First action",
    )


def test_stem_choice_split_is_atomic_and_candidate_only() -> None:
    canonical = damaged_pack()
    candidate = apply_repair(canonical, structural_record(canonical))

    assert canonical["questions"][0]["stem"].endswith("First action")
    question = candidate["questions"][0]
    assert question["stem"] == "Which action?"
    assert [choice["label"] for choice in question["choices"]] == ["A", "B", "C"]
    assert question["choices"][0]["text"] == "First action"


def test_structural_repair_rejects_stale_choice_shape() -> None:
    pack = damaged_pack()
    record = structural_record(pack)
    pack["questions"][0]["choices"].append(
        {"label": "D", "text": "Changed elsewhere"}
    )

    with pytest.raises(RepairError, match="current choices"):
        apply_repair(pack, record)


def test_structural_repair_round_trips_in_repair_set(tmp_path: Path) -> None:
    pack = damaged_pack()
    record = structural_record(pack)
    path = write_repair_set([record], tmp_path / "repairs.json")

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["repairs"][0]["format"] == (
        "prepflow_stem_choice_split_record"
    )
    assert load_repair_records(path) == [record]
