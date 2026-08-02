import argparse
import json
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, compare_isolated_candidate
from compiler.repair import load_pack, load_repair_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare an isolated intake candidate read-only.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repairs", type=Path, required=True)
    parser.add_argument("--known-manifest", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        known_manifest = json.loads(args.known_manifest.read_text(encoding="utf-8"))
        result = compare_isolated_candidate(
            args.run_directory,
            canonical_pack=load_pack(args.canonical),
            candidate_24_pack=load_pack(args.candidate),
            repair_records=load_repair_records(args.repairs),
            known_manifest=known_manifest,
        )
    except (OSError, json.JSONDecodeError, IntakeWorkspaceError, ValueError) as error:
        raise SystemExit(f"Intake comparison stopped: {error}") from error
    print("PrepFlow isolated candidate comparison complete")
    print(f"Run: {result.run_id}")
    print(f"Repair lessons: {result.repair_lesson_counts}")
    print(f"Promotion blockers: known={result.known_blockers}, isolated={result.isolated_blockers}")
    print("Promotion ready: False")
    print("No protected Pack, repair record, snapshot, or canonical data changed.")


if __name__ == "__main__":
    main()
