import copy

import pytest

from compiler.candidate import build_candidate
from compiler.duplicate_choice_batch import (
    finding_id_for_duplicate_choice_block,
)
from compiler.repair import (
    RepairError,
    apply_repair,
    create_duplicate_choice_block_record,
    load_repair_records,
    write_repair_set,
)


def duplicated_pack() -> dict:
    block = [
        {"label": "A", "text": "First response"},
        {"label": "B", "text": "Second response"},
        {"label": "C", "text": "Third response"},
        {"label": "D", "text": "Fourth response"},
    ]
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Safety",
                "type": "mc",
                "stem": "Which response is appropriate?",
                "choices": block + [dict(choice) for choice in block],
                "correct_answers": ["D"],
                "rationale": "The fourth response is appropriate.",
            }
        ],
    }


def record_for(pack: dict):
    question_id = "PFQ-test-pack-000000001"
    return create_duplicate_choice_block_record(
        pack,
        question_id=question_id,
        repair_id=finding_id_for_duplicate_choice_block(question_id),
    )


def test_duplicate_choice_repair_is_atomic_and_candidate_only() -> None:
    canonical = duplicated_pack()
    record = record_for(canonical)

    candidate = apply_repair(canonical, record)

    assert len(canonical["questions"][0]["choices"]) == 8
    assert len(candidate["questions"][0]["choices"]) == 4
    assert candidate["questions"][0]["correct_answers"] == ["D"]


def test_duplicate_choice_repair_rejects_stale_choice_shape() -> None:
    canonical = duplicated_pack()
    record = record_for(canonical)
    changed = copy.deepcopy(canonical)
    changed["questions"][0]["choices"][4]["text"] = "Changed response"

    with pytest.raises(RepairError, match="no longer matches"):
        apply_repair(changed, record)


def test_duplicate_choice_repair_round_trips_in_repair_set(tmp_path) -> None:
    canonical = duplicated_pack()
    record = record_for(canonical)
    path = write_repair_set([record], tmp_path / "repair-records.json")

    loaded = load_repair_records(path)

    assert loaded == [record]


def test_candidate_reports_duplicate_choice_rule_as_importer_knowledge() -> None:
    canonical = duplicated_pack()
    result = build_candidate(canonical, [record_for(canonical)])

    assert result.manual_repair_lessons == (
        ("exact_duplicate_choice_block_removed", 1),
    )
