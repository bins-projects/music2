import argparse
from pathlib import Path

from compiler.intake_workspace import (
    IntakeWorkspaceError,
    build_isolated_comparison_candidate,
)
from compiler.repair import load_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a non-promotable isolated intake comparison candidate."
    )
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = build_isolated_comparison_candidate(
            args.run_directory,
            canonical_pack=load_pack(args.canonical),
        )
    except (OSError, IntakeWorkspaceError, ValueError) as error:
        raise SystemExit(f"Candidate construction stopped: {error}") from error
    print("PrepFlow isolated comparison candidate built")
    print(f"Run: {result.run_id}")
    print(f"Questions: {result.question_count}")
    print(f"Boundary findings retained: {result.boundary_findings}")
    print("Repairs applied: 0")
    print(f"Promotion ready: {result.promotion_ready}")
    print("Canonical Pack unchanged; no promotion operation is available here.")


if __name__ == "__main__":
    main()
