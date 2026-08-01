import argparse
import textwrap
from pathlib import Path

from compiler.pack_qa import (
    interleaving_repair_findings,
    typography_repair_findings,
)
from compiler.repair import (
    REPAIR_DISPOSITIONS,
    Finding,
    RepairError,
    apply_repairs,
    create_repair_record,
    find_question,
    get_text_field,
    load_findings,
    load_pack,
    load_repair_records,
    select_finding,
    write_candidate_pack,
    write_repair_set,
)


DEFAULT_PACK = Path("packs/fundamentals.prepflow.json")
DEFAULT_LEDGER = Path(
    "content-qa/reports/fundamentals-damage-ledger.json"
)
DEFAULT_OUTPUT = Path("output/repair-workbench/fundamentals")


def wrapped(label: str, value: object, width: int) -> str:
    text = str(value)
    prefix = f"{label}: "
    return textwrap.fill(
        text,
        width=width,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
    )


def render_question(
    question: dict,
    finding: Finding,
    *,
    width: int = 88,
) -> str:
    lines = [
        wrapped("Question", question["id"], width),
        wrapped(
            "Chapter",
            f"{question.get('chapter', '')} — "
            f"{question.get('chapter_title', '')}",
            width,
        ),
        wrapped("Type", question.get("type", ""), width),
        wrapped("Finding", finding.damage_type, width),
        wrapped("Flagged field", finding.field, width),
        "",
        wrapped("Stem", question.get("stem", ""), width),
        "",
        "Choices:",
    ]

    choices = question.get("choices")
    if isinstance(choices, list) and choices:
        for choice in choices:
            lines.append(
                wrapped(
                    f"  {choice.get('label', '?')}",
                    choice.get("text", ""),
                    width,
                )
            )
    else:
        lines.append("  None")

    lines.extend(
        [
            "",
            wrapped(
                "Correct",
                ", ".join(str(item) for item in question.get(
                    "correct_answers", []
                )),
                width,
            ),
            "",
            wrapped("Rationale", question.get("rationale", ""), width),
        ]
    )
    return "\n".join(lines)


def read_multiline_replacement() -> str:
    print()
    print("Enter the complete replacement for the flagged field.")
    print("Finish with a line containing only a period.")

    lines = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review one PrepFlow QA finding without modifying a canonical Pack."
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--finding-id")
    selection.add_argument("--question-id")
    parser.add_argument("--width", type=int, default=88)
    parser.add_argument(
        "--disposition",
        choices=sorted(REPAIR_DISPOSITIONS),
        default="one_question",
        help="Classify what this repair teaches the ingestion pipeline.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        pack = load_pack(args.pack)
        findings = load_findings(args.ledger)
        findings.extend(typography_repair_findings(pack))
        findings.extend(interleaving_repair_findings(pack))
        finding = select_finding(
            findings,
            finding_id=args.finding_id,
            question_id=args.question_id,
        )
        question = find_question(pack, finding.question_id)

        print()
        print(render_question(question, finding, width=args.width))
        print()
        print(wrapped("Current flagged value", get_text_field(
            question, finding.field
        ), args.width))
        print()
        action = input("Action [repair/quit]: ").strip().lower()
        if action != "repair":
            print("No files changed.")
            return

        replacement = read_multiline_replacement()
        record = create_repair_record(
            pack,
            finding,
            replacement,
            disposition=args.disposition,
        )
        candidate_path = args.output / "candidate.prepflow.json"
        legacy_record_path = args.output / "repair-record.json"
        record_set_path = args.output / "repair-records.json"
        existing_record_path = (
            record_set_path
            if record_set_path.exists()
            else legacy_record_path
        )
        records = load_repair_records(existing_record_path)
        if any(item.repair_id == record.repair_id for item in records):
            raise RepairError(
                f"Repair is already recorded: {record.repair_id}"
            )
        records.append(record)
        candidate = apply_repairs(pack, records)

        write_candidate_pack(
            candidate,
            canonical_path=args.pack,
            candidate_path=candidate_path,
        )
        write_repair_set(records, record_set_path)
        if legacy_record_path.exists():
            legacy_record_path.unlink()

        print()
        print("Repair recorded and applied to a candidate only.")
        print(wrapped("Before", record.before, args.width))
        print(wrapped("After", record.after, args.width))
        print(f"Pipeline classification: {record.disposition}")
        print(f"Candidate: {candidate_path}")
        print(f"Repairs in candidate: {len(records)}")
        print(f"Repair set: {record_set_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Repair workbench stopped: {error}") from error


if __name__ == "__main__":
    main()
