import argparse
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, parse_isolated_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse one generalized-cleaned isolated PrepFlow run."
    )
    parser.add_argument("run_directory", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = parse_isolated_run(args.run_directory)
    except IntakeWorkspaceError as error:
        raise SystemExit(str(error)) from error
    print("PrepFlow isolated parsing complete")
    print(f"Run: {result.run_id}")
    print(f"Parsed questions: {result.parsed_questions}")
    print(f"Question types: {result.question_types}")
    print(f"Missing chapter: {result.missing_chapter}")
    print(f"Missing answers: {result.missing_answers}")
    print(f"Choice-sequence findings: {result.choice_sequence_findings}")
    print("Broad missing-A recovery: not used")
    print("No stable IDs, candidate build, repair, comparison, or promotion performed.")


if __name__ == "__main__":
    main()
