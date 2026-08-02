import argparse
from pathlib import Path

from compiler.repair import (
    RepairError,
    apply_repairs,
    choice_pairs,
    create_choice_structure_repair_record,
    find_question,
    load_pack,
    load_repair_records,
    write_candidate_pack,
    write_repair_set,
)


DEFAULT_PACK = Path("packs/fundamentals.prepflow.json")
DEFAULT_OUTPUT = Path("output/repair-workbench/fundamentals")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply one explicitly approved choice-structure correction "
            "to a candidate Pack only."
        )
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--question-id", required=True)
    replacement = parser.add_mutually_exclusive_group(required=True)
    replacement.add_argument("--remove-index", type=int)
    replacement.add_argument(
        "--replacement-choice",
        action="append",
        metavar="LABEL=TEXT",
        help=(
            "Provide the complete approved replacement choice set. Repeat once "
            "for each choice in the intended order."
        ),
    )
    parser.add_argument("--correct-answer", action="append", required=True)
    parser.add_argument("--repair-id", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def parse_replacement_choices(
    values: list[str],
) -> tuple[tuple[str, str], ...]:
    choices = []
    for value in values:
        if "=" not in value:
            raise RepairError(
                "Replacement choices must use the form LABEL=TEXT"
            )
        label, text = (item.strip() for item in value.split("=", 1))
        if not label or not text:
            raise RepairError(
                "Replacement choice label and text must not be empty"
            )
        choices.append((label, text))
    if not choices:
        raise RepairError("At least one replacement choice is required")
    return tuple(choices)


def main() -> None:
    args = build_parser().parse_args()
    repair_path = args.output / "repair-records.json"
    candidate_path = args.output / "candidate.prepflow.json"
    try:
        pack = load_pack(args.pack)
        records = load_repair_records(repair_path)
        current = apply_repairs(pack, records)
        question = find_question(current, args.question_id)
        before_choices = choice_pairs(question)
        removed = None
        if args.replacement_choice:
            after_choices = parse_replacement_choices(
                args.replacement_choice
            )
        else:
            if (
                args.remove_index < 0
                or args.remove_index >= len(before_choices)
            ):
                raise RepairError(
                    f"Choice removal index is out of range: "
                    f"{args.remove_index}"
                )
            removed = before_choices[args.remove_index]
            after_choices = tuple(
                choice
                for index, choice in enumerate(before_choices)
                if index != args.remove_index
            )
        record = create_choice_structure_repair_record(
            current,
            question_id=args.question_id,
            repair_id=args.repair_id,
            replacement_choices=after_choices,
            replacement_correct_answers=tuple(args.correct_answer),
            damage_type="choice structure: approved atomic replacement",
            disposition="one_question",
        )

        print("PrepFlow approved choice-structure correction")
        print(f"Question: {record.question_id}")
        print("Before choices:")
        for label, text in record.expected_choices:
            print(f"  {label}: {text}")
        print("Before correct answer: " + ", ".join(
            record.expected_correct_answers
        ))
        if removed is not None:
            print(f"Removed choice: {removed[0]}: {removed[1]}")
        print("After choices:")
        for label, text in record.replacement_choices:
            print(f"  {label}: {text}")
        print("After correct answer: " + ", ".join(
            record.replacement_correct_answers
        ))

        if not args.apply:
            print()
            print("Dry run only. No files changed.")
            return
        if any(item.repair_id == record.repair_id for item in records):
            raise RepairError(f"Repair is already recorded: {record.repair_id}")

        combined = records + [record]
        candidate = apply_repairs(pack, combined)
        write_candidate_pack(
            candidate,
            canonical_path=args.pack,
            candidate_path=candidate_path,
        )
        write_repair_set(combined, repair_path)
        print()
        print("Approved correction applied to candidate only.")
        print(f"Repairs in candidate: {len(combined)}")
        print(f"Candidate: {candidate_path}")
        print(f"Repair set: {repair_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Choice-structure repair stopped: {error}") from error


if __name__ == "__main__":
    main()
