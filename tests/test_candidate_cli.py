from pathlib import Path

from compiler.candidate_cli import build_parser


def test_candidate_cli_defaults_to_fundamentals_workbench() -> None:
    args = build_parser().parse_args([])

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert args.output == Path("output/repair-workbench/fundamentals")
