from pathlib import Path

from compiler.structural_batch_cli import build_parser


def test_structural_batch_cli_is_dry_run_by_default() -> None:
    args = build_parser().parse_args([])

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert not args.apply
