import argparse
import json
from pathlib import Path

from compiler.intake_workspace import IntakeWorkspaceError, attribute_isolated_drift
from compiler.repair import load_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attribute isolated intake drift by pipeline stage.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--known-manifest", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        known = json.loads(args.known_manifest.read_text(encoding="utf-8"))
        result = attribute_isolated_drift(
            args.run_directory,
            canonical_pack=load_pack(args.canonical),
            candidate_24_pack=load_pack(args.candidate),
            known_manifest=known,
        )
    except (OSError, json.JSONDecodeError, IntakeWorkspaceError, ValueError) as error:
        raise SystemExit(f"Drift attribution stopped: {error}") from error
    print("PrepFlow isolated drift attribution complete")
    print(f"Run: {result.run_id}")
    print(f"Field categories: {result.field_category_counts}")
    print(f"Blocker attribution: {result.blocker_attribution}")
    print("Legacy cleaner was diagnostic-only; default intake artifacts were not changed.")


if __name__ == "__main__":
    main()
