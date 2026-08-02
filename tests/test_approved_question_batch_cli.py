import copy

import pytest

from compiler.approved_question_batch_cli import (
    build_parser,
    create_records_from_plan,
)
from compiler.repair import RepairError
from tests.test_question_correction import sample_pack


def approved_plan() -> dict:
    return {
        "format": "prepflow_question_correction_plan",
        "version": "1.0",
        "pack_id": "test-pack",
        "corrections": [
            {
                "repair_id": "PFQA-BATCH-ONE",
                "question_id": "PFQ-test-pack-000000001",
                "replacement_stem": "Clean stem?",
                "replacement_choices": [
                    {"label": "A", "text": "First action"},
                    {"label": "B", "text": "Second action"},
                    {"label": "C", "text": "Third action"},
                ],
                "replacement_correct_answers": ["B"],
                "replacement_rationale": "Clean rationale.",
                "damage_type": "approved extraction correction",
            }
        ],
    }


def test_approved_question_batch_is_dry_run_by_default() -> None:
    args = build_parser().parse_args(["--plan", "approved.json"])

    assert not args.apply


def test_approved_plan_creates_stale_guarded_records() -> None:
    records = create_records_from_plan(sample_pack(), [], approved_plan())

    assert len(records) == 1
    assert records[0].expected_stem == "Damaged stem a. First action"
    assert records[0].replacement_stem == "Clean stem?"


def test_approved_plan_rejects_wrong_pack() -> None:
    plan = copy.deepcopy(approved_plan())
    plan["pack_id"] = "different-pack"

    with pytest.raises(RepairError, match="different Pack"):
        create_records_from_plan(sample_pack(), [], plan)


def test_approved_plan_rejects_duplicate_question() -> None:
    plan = approved_plan()
    second = copy.deepcopy(plan["corrections"][0])
    second["repair_id"] = "PFQA-BATCH-TWO"
    plan["corrections"].append(second)

    with pytest.raises(RepairError, match="repeats question"):
        create_records_from_plan(sample_pack(), [], plan)
