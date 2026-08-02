import argparse
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, match_isolated_run
from compiler.repair import load_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Match isolated records against protected Packs.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = match_isolated_run(
            args.run_directory,
            canonical_pack=load_pack(args.canonical),
            candidate_pack=load_pack(args.candidate),
        )
    except (OSError, IntakeWorkspaceError, ValueError) as error:
        raise SystemExit(f"Record matching stopped: {error}") from error
    print("PrepFlow isolated record matching complete")
    print(f"Run: {result.run_id}")
    print(f"Canonical matched: {result.canonical_matched}")
    print(f"24-repair candidate matched: {result.candidate_matched}")
    print(f"Parsed-only records: {result.parsed_only}")
    print(f"Target-only records: {result.target_only}")
    print("No IDs assigned, Pack built, repair applied, or promotion performed.")


if __name__ == "__main__":
    main()
