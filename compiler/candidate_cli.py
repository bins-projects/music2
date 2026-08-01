import argparse
from pathlib import Path

from compiler.candidate import build_candidate, write_candidate_manifest
from compiler.repair import (
    RepairError,
    load_pack,
    load_repair_records,
    write_candidate_pack,
)
from compiler.repair_cli import DEFAULT_OUTPUT, DEFAULT_PACK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a disposable candidate from approved repairs and "
            "deterministic normalizations."
        )
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    repair_path = args.output / "repair-records.json"
    candidate_path = args.output / "candidate.prepflow.json"
    manifest_path = args.output / "candidate-manifest.json"

    try:
        pack = load_pack(args.pack)
        records = load_repair_records(repair_path)
        result = build_candidate(pack, records)
        write_candidate_pack(
            result.candidate,
            canonical_path=args.pack,
            candidate_path=candidate_path,
        )
        write_candidate_manifest(result, manifest_path)
    except (OSError, RepairError) as error:
        raise SystemExit(f"Candidate build stopped: {error}") from error

    print("PrepFlow candidate rebuilt")
    print(f"Approved manual repairs: {result.manual_repairs}")
    print(
        "Typography normalization: "
        f"{result.typography_fields_changed} fields, "
        f"{result.opening_marks_replaced} opening marks, "
        f"{result.closing_marks_replaced} closing marks"
    )
    print(f"Promotion blockers: {len(result.promotion_blockers)}")
    for blocker in result.promotion_blockers:
        print(
            f"  {blocker.finding_id} | {blocker.question_id} | "
            f"{blocker.field}"
        )
    print(f"Candidate: {candidate_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Canonical Pack unchanged: {args.pack}")


if __name__ == "__main__":
    main()
