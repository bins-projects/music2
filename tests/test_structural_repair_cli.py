from pathlib import Path

from compiler.structural_repair_cli import build_parser


def test_structural_cli_requires_explicit_finding_and_choice() -> None:
    args = build_parser().parse_args(
        [
            "--finding-id",
            "PFQA-INTERLEAVE-Q1-STEM",
            "--insert-label",
            "A",
        ]
    )

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert args.insert_label == "A"
    assert args.insert_index == 0
