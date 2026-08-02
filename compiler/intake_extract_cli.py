import argparse
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, extract_pdf_in_isolated_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract a PDF through an isolated disposable intake copy."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("output/intake-runs"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = extract_pdf_in_isolated_run(
            args.source,
            workspace_root=args.workspace_root,
        )
    except IntakeWorkspaceError as error:
        raise SystemExit(str(error)) from error

    print("PrepFlow isolated PDF extraction complete")
    print(f"Run: {result.run_id}")
    print(f"Extracted characters: {result.extracted_characters}")
    print(f"Disposable source deleted: {result.staged_source_deleted}")
    print(f"Run workspace: {result.run_directory}")
    print("No cleaning, parsing, candidate build, repair, or promotion performed.")


if __name__ == "__main__":
    main()
