import argparse
import json
import sys
from pathlib import Path

from compiler.repair import (
    QuestionCorrectionRecord,
    RepairError,
    RepairEntry,
    apply_repairs,
    create_question_correction_record,
    load_pack,
    load_repair_records,
    write_candidate_pack,
    write_repair_set,
)


DEFAULT_PACK = Path("packs/fundamentals.prepflow.json")
DEFAULT_OUTPUT = Path("output/repair-workbench/fundamentals")
PLAN_FIELDS = {"format", "version", "pack_id", "corrections"}
CORRECTION_FIELDS = {
    "repair_id",
    "question_id",
    "replacement_stem",
    "replacement_choices",
    "replacement_correct_answers",
    "replacement_rationale",
    "damage_type",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply an explicitly approved, stale-guarded batch of "
            "full-question candidate corrections."
        )
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--plan",
        required=True,
        help="Approved JSON plan path, or - to read the plan from standard input.",
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def load_plan(path: str) -> dict:
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            with Path(path).open("r", encoding="utf-8") as file:
                value = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RepairError(f"Could not read approved batch plan: {error}") from error

    if not isinstance(value, dict) or set(value) != PLAN_FIELDS:
        raise RepairError("Approved batch plan fields do not match the schema")
    if value.get("format") != "prepflow_question_correction_plan":
        raise RepairError("Unsupported approved batch plan format")
    if value.get("version") != "1.0":
        raise RepairError("Unsupported approved batch plan version")
    if not isinstance(value.get("pack_id"), str) or not value["pack_id"]:
        raise RepairError("Approved batch plan is missing pack_id")
    if not isinstance(value.get("corrections"), list) or not value["corrections"]:
        raise RepairError("Approved batch plan must contain corrections")
    return value


def parse_choices(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise RepairError("Replacement choices must be a non-empty list")
    choices = []
    for choice in value:
        if not isinstance(choice, dict) or set(choice) != {"label", "text"}:
            raise RepairError("Replacement choice fields do not match the schema")
        label = choice.get("label")
        text = choice.get("text")
        if not isinstance(label, str) or not isinstance(text, str):
            raise RepairError("Replacement choice label and text must be text")
        choices.append((label, text))
    return tuple(choices)


def parse_answers(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise RepairError("Replacement correct answers must be a non-empty list")
    return tuple(value)


def create_records_from_plan(
    pack: dict,
    existing: list[RepairEntry],
    plan: dict,
) -> tuple[QuestionCorrectionRecord, ...]:
    if plan.get("pack_id") != pack.get("pack_id"):
        raise RepairError("Approved batch plan belongs to a different Pack")
    candidate = apply_repairs(pack, existing)
    records = []
    seen_questions = set()
    seen_repairs = {record.repair_id for record in existing}
    for value in plan["corrections"]:
        if not isinstance(value, dict) or set(value) != CORRECTION_FIELDS:
            raise RepairError("Approved correction fields do not match the schema")
        repair_id = value.get("repair_id")
        question_id = value.get("question_id")
        if not isinstance(repair_id, str) or not repair_id:
            raise RepairError("Approved correction is missing repair_id")
        if not isinstance(question_id, str) or not question_id:
            raise RepairError("Approved correction is missing question_id")
        if repair_id in seen_repairs:
            raise RepairError(f"Repair is already recorded: {repair_id}")
        if question_id in seen_questions:
            raise RepairError(
                f"Approved batch repeats question: {question_id}"
            )
        seen_repairs.add(repair_id)
        seen_questions.add(question_id)

        replacement_stem = value.get("replacement_stem")
        replacement_rationale = value.get("replacement_rationale")
        damage_type = value.get("damage_type")
        if not all(
            isinstance(item, str)
            for item in (
                replacement_stem,
                replacement_rationale,
                damage_type,
            )
        ):
            raise RepairError("Approved correction text fields must be text")

        records.append(
            create_question_correction_record(
                candidate,
                question_id=question_id,
                repair_id=repair_id,
                replacement_stem=replacement_stem,
                replacement_choices=parse_choices(
                    value.get("replacement_choices")
                ),
                replacement_correct_answers=parse_answers(
                    value.get("replacement_correct_answers")
                ),
                replacement_rationale=replacement_rationale,
                damage_type=damage_type,
                disposition="one_question",
            )
        )
    return tuple(records)


def print_record(record: QuestionCorrectionRecord) -> None:
    print(record.question_id)
    print(f"  Stem before: {record.expected_stem}")
    print(f"  Stem after:  {record.replacement_stem}")
    print("  Choices before:")
    for label, text in record.expected_choices:
        print(f"    {label}: {text}")
    print("  Choices after:")
    for label, text in record.replacement_choices:
        print(f"    {label}: {text}")
    print(
        "  Answers: "
        + ", ".join(record.expected_correct_answers)
        + " -> "
        + ", ".join(record.replacement_correct_answers)
    )
    if record.expected_rationale != record.replacement_rationale:
        print(f"  Rationale before: {record.expected_rationale}")
        print(f"  Rationale after:  {record.replacement_rationale}")


def main() -> None:
    args = build_parser().parse_args()
    repair_path = args.output / "repair-records.json"
    candidate_path = args.output / "candidate.prepflow.json"
    try:
        pack = load_pack(args.pack)
        existing = load_repair_records(repair_path)
        plan = load_plan(args.plan)
        proposals = create_records_from_plan(pack, existing, plan)

        print("PrepFlow approved full-question batch")
        print(f"Approved corrections: {len(proposals)}")
        for record in proposals:
            print_record(record)

        if not args.apply:
            print()
            print("Dry run only. No files changed.")
            return

        combined = existing + list(proposals)
        candidate = apply_repairs(pack, combined)
        write_candidate_pack(
            candidate,
            canonical_path=args.pack,
            candidate_path=candidate_path,
        )
        write_repair_set(combined, repair_path)
        print()
        print("Approved full-question batch applied to candidate only.")
        print(f"Repairs in candidate: {len(combined)}")
        print(f"Candidate: {candidate_path}")
        print(f"Repair set: {repair_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Approved question batch stopped: {error}") from error


if __name__ == "__main__":
    main()
