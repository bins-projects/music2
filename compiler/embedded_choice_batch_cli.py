import argparse
from pathlib import Path

from compiler.repair import (
    RepairError,
    apply_repairs,
    load_pack,
    load_repair_records,
    write_candidate_pack,
    write_repair_set,
)
from compiler.structural_batch import plan_embedded_middle_choices


DEFAULT_PACK = Path("packs/fundamentals.prepflow.json")
DEFAULT_OUTPUT = Path("output/repair-workbench/fundamentals")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply exact missing middle choices embedded in the "
            "immediately preceding choice."
        )
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
        plan = plan_embedded_middle_choices(pack, records)

        print("PrepFlow exact embedded-choice batch")
        print(f"Approved candidates: {len(plan.proposals)}")
        for record in plan.proposals:
            added = next(
                label
                for label, _ in record.replacement_choices
                if label not in {item[0] for item in record.expected_choices}
            )
            print(f"  {record.question_id} | restore {added}")
            print("    Before:")
            for label, text in record.expected_choices:
                print(f"      {label}: {text}")
            print("    After:")
            for label, text in record.replacement_choices:
                print(f"      {label}: {text}")

        print(f"Ambiguous shapes left for review: {len(plan.review_question_ids)}")
        for question_id in plan.review_question_ids:
            print(f"  {question_id}")

        if not args.apply:
            print()
            print("Dry run only. No files changed.")
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
        print("Approved embedded-choice batch applied to candidate only.")
        print(f"Repairs in candidate: {len(combined)}")
        print(f"Candidate: {candidate_path}")
        print(f"Repair set: {repair_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Embedded-choice batch stopped: {error}") from error


if __name__ == "__main__":
    main()
