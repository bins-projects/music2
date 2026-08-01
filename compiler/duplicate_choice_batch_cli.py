import argparse
from pathlib import Path

from compiler.duplicate_choice_batch import plan_exact_duplicate_choice_blocks
from compiler.repair import (
    RepairError,
    apply_repairs,
    load_pack,
    load_repair_records,
    write_candidate_pack,
    write_repair_set,
)
from compiler.repair_cli import DEFAULT_OUTPUT, DEFAULT_PACK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove exact repeated choice blocks from a candidate Pack."
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    repair_path = args.output / "repair-records.json"
    candidate_path = args.output / "candidate.prepflow.json"
    try:
        pack = load_pack(args.pack)
        records = load_repair_records(repair_path)
        plan = plan_exact_duplicate_choice_blocks(pack, records)
        print("PrepFlow exact duplicate-choice batch")
        print(f"Approved candidates: {len(plan.proposals)}")
        for record in plan.proposals:
            print(
                f"  {record.question_id} | retain "
                f"{len(record.retained_choices)} choices | "
                "remove one exact repeated block"
            )

        if not args.apply:
            print()
            print("Dry run only. Use --apply to write candidate repairs.")
            return
        if not plan.proposals:
            print()
            print("No files changed.")
            return

        combined = records + list(plan.proposals)
        candidate = apply_repairs(pack, combined)
        write_candidate_pack(
            candidate,
            canonical_path=args.pack,
            candidate_path=candidate_path,
        )
        write_repair_set(combined, repair_path)
        print()
        print("Approved duplicate-choice batch applied to a candidate only.")
        print(f"Repairs in candidate: {len(combined)}")
        print(f"Candidate: {candidate_path}")
        print(f"Repair set: {repair_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Duplicate-choice batch stopped: {error}") from error


if __name__ == "__main__":
    main()
