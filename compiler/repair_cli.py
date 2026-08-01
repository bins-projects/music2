import argparse
import textwrap
from pathlib import Path

from compiler.artifact_profile import (
    ARTIFACT_EVIDENCE_LEVELS,
    artifact_evidence_findings,
)
from compiler.pack_qa import (
    INTERLEAVING_SEVERITIES,
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


def unrecorded_findings(findings: list[Finding], records: list) -> list[Finding]:
    recorded_ids = {item.repair_id for item in records}
    return [
        item for item in findings
        if item.finding_id not in recorded_ids
    ]


def add_or_amend_record(records: list, record, *, amend: bool):
    matching_indexes = [
        index
        for index, item in enumerate(records)
        if item.repair_id == record.repair_id
    ]
    if matching_indexes and not amend:
        raise RepairError(f"Repair is already recorded: {record.repair_id}")
    if amend:
        if not matching_indexes:
            raise RepairError(
                f"Repair is not recorded and cannot be amended: "
                f"{record.repair_id}"
            )
        updated = list(records)
        updated[matching_indexes[0]] = record
        return updated, "amended"

    return [*records, record], "recorded"


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
    print("Include the field's own final punctuation in the replacement.")
    print("Then finish with a separate line containing only a period.")

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
    selection.add_argument(
        "--next-interleaving",
        choices=INTERLEAVING_SEVERITIES,
        help="Open the next Pack-wide interleaving finding in this tier.",
    )
    selection.add_argument(
        "--next-artifact",
        choices=ARTIFACT_EVIDENCE_LEVELS,
        help="Open the next unresolved field in an artifact-evidence tier.",
    )
    parser.add_argument("--width", type=int, default=88)
    parser.add_argument(
        "--disposition",
        choices=sorted(REPAIR_DISPOSITIONS),
        default="one_question",
        help="Classify what this repair teaches the ingestion pipeline.",
    )
    parser.add_argument(
        "--amend-existing",
        action="store_true",
        help="Replace an existing repair record with a corrected decision.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        pack = load_pack(args.pack)
        candidate_path = args.output / "candidate.prepflow.json"
        legacy_record_path = args.output / "repair-record.json"
        record_set_path = args.output / "repair-records.json"
        existing_record_path = (
            record_set_path
            if record_set_path.exists()
            else legacy_record_path
        )
        records = load_repair_records(existing_record_path)
        findings = load_findings(args.ledger)
        findings.extend(typography_repair_findings(pack))
        findings.extend(interleaving_repair_findings(pack))
        if args.next_artifact:
            queue = artifact_evidence_findings(
                pack,
                records,
                args.next_artifact,
            )
            if not queue:
                raise RepairError(
                    "No findings remain in artifact evidence tier: "
                    + args.next_artifact
                )
            finding = queue[0]
        elif args.next_interleaving:
            queue = interleaving_repair_findings(
                pack,
                severity=args.next_interleaving,
            )
            queue = unrecorded_findings(queue, records)
            if not queue:
                raise RepairError(
                    "No findings remain in interleaving tier: "
                    + args.next_interleaving
                )
            finding = queue[0]
        else:
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
        records, action_label = add_or_amend_record(
            records,
            record,
            amend=args.amend_existing,
        )
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
        print(
            f"Repair {action_label} and applied to a candidate only."
        )
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
