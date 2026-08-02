import argparse
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, validate_isolated_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize and validate an isolated PrepFlow intake run."
    )
    parser.add_argument("run_directory", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = validate_isolated_run(args.run_directory)
    except IntakeWorkspaceError as error:
        raise SystemExit(str(error)) from error
    print("PrepFlow isolated validation complete")
    print(f"Run: {result.run_id}")
    print(f"Normalized questions: {result.normalized_questions}")
    print(f"Eligible questions: {result.eligible_questions}")
    print(f"Skipped questions: {result.skipped_questions}")
    print(f"Diagnostics by severity: {result.diagnostics_by_severity}")
    print(f"Diagnostics by code: {result.diagnostics_by_code}")
    print("No stable IDs, Pack export, repair, comparison, or promotion performed.")


if __name__ == "__main__":
    main()
