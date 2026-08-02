from pathlib import Path

from compiler.embedded_choice_batch_cli import build_parser


def test_embedded_choice_batch_is_dry_run_by_default() -> None:
    args = build_parser().parse_args([])

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert args.output == Path("output/repair-workbench/fundamentals")
    assert not args.apply
