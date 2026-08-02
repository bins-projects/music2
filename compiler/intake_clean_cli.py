import argparse
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, clean_isolated_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply generalized cleaning to an isolated PrepFlow run."
    )
    parser.add_argument("run_directory", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = clean_isolated_run(args.run_directory)
    except IntakeWorkspaceError as error:
        raise SystemExit(str(error)) from error
    print("PrepFlow generalized cleaning complete")
    print(f"Run: {result.run_id}")
    print(f"Characters: {result.raw_characters} -> {result.cleaned_characters}")
    print(f"Detected chapters: {result.chapter_count}")
    print(f"Detected numbered questions: {result.question_count}")
    print("Legacy source-specific rules: not used")
    print("No parsing, candidate build, repair, or promotion performed.")


if __name__ == "__main__":
    main()
