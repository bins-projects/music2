from pathlib import Path

from compiler.choice_structure_repair_cli import build_parser


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
