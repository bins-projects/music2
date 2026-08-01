from pathlib import Path

from compiler.artifact_profile_cli import build_parser


def test_artifact_profile_cli_uses_temporary_workbench_defaults() -> None:
    args = build_parser().parse_args([])

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert args.output == Path("output/repair-workbench/fundamentals")
