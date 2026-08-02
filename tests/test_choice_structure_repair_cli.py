from pathlib import Path

import pytest

from compiler.choice_structure_repair_cli import build_parser
from compiler.choice_structure_repair_cli import parse_replacement_choices
from compiler.repair import RepairError


def test_choice_structure_cli_is_dry_run_by_default():
    args = build_parser().parse_args(
        [
            "--question-id",
            "PFQ-test-pack-000000001",
            "--remove-index",
            "4",
            "--correct-answer",
            "C",
            "--repair-id",
            "PFQA-TEST-STRUCTURE",
        ]
    )

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert not args.apply


def test_choice_structure_cli_accepts_complete_replacement_choices():
    args = build_parser().parse_args(
        [
            "--question-id",
            "PFQ-test-pack-000000001",
            "--replacement-choice",
            "A=Assessment",
            "--replacement-choice",
            "B=Planning",
            "--correct-answer",
            "A",
            "--repair-id",
            "PFQA-TEST-REPLACEMENT",
        ]
    )

    assert args.remove_index is None
    assert args.replacement_choice == ["A=Assessment", "B=Planning"]
    assert not args.apply


def test_parse_replacement_choices_preserves_approved_order_and_text():
    assert parse_replacement_choices(
        ["A=Assessment", "B=Planning and prioritization"]
    ) == (
        ("A", "Assessment"),
        ("B", "Planning and prioritization"),
    )


@pytest.mark.parametrize("value", ["Assessment", "=Assessment", "A="])
def test_parse_replacement_choices_rejects_malformed_values(value):
    with pytest.raises(RepairError):
        parse_replacement_choices([value])
