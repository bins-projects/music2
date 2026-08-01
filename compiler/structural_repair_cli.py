import argparse
from pathlib import Path

from compiler.pack_qa import (
    choice_structure_repair_findings,
    interleaving_repair_findings,
)
from compiler.repair import (
    REPAIR_DISPOSITIONS,
    RepairError,
    apply_repairs,
    create_stem_choice_split_record,
    find_question,
    load_pack,
    load_repair_records,
    select_finding,
    write_candidate_pack,
    write_repair_set,
)
from compiler.repair_cli import (
    DEFAULT_OUTPUT,
    DEFAULT_PACK,
    add_or_amend_record,
    read_multiline_replacement,
    render_question,
    wrapped,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Repair a choice absorbed into a question stem without modifying "
            "the canonical Pack."
        )
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--finding-id", required=True)
    parser.add_argument("--insert-label", required=True)
    parser.add_argument("--insert-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=88)
    parser.add_argument(
        "--disposition",
        choices=sorted(REPAIR_DISPOSITIONS),
        default="parser_candidate",
    )
    parser.add_argument("--amend-existing", action="store_true")
    return parser


def structural_findings(pack: dict):
    """Return both structural QA findings and legacy interleaving findings."""
    return choice_structure_repair_findings(pack) + interleaving_repair_findings(
        pack
    )


def main() -> None:
    args = build_parser().parse_args()
    try:
        pack = load_pack(args.pack)
        findings = structural_findings(pack)
        finding = select_finding(findings, finding_id=args.finding_id)
        if finding.field != "stem":
            raise RepairError("Structural stem-choice repair requires a stem finding")
        question = find_question(pack, finding.question_id)

        print()
        print(render_question(question, finding, width=args.width))
        print()
        action = input("Action [repair/quit]: ").strip().lower()
        if action != "repair":
            print("No files changed.")
            return

        print()
        print("Corrected stem:")
        corrected_stem = read_multiline_replacement()
        print()
        print(f"Inserted choice {args.insert_label} text:")
        choice_text = read_multiline_replacement()

        record = create_stem_choice_split_record(
            pack,
            finding,
            corrected_stem,
            insert_label=args.insert_label,
            insert_text=choice_text,
            insert_index=args.insert_index,
            disposition=args.disposition,
        )

        candidate_path = args.output / "candidate.prepflow.json"
        record_set_path = args.output / "repair-records.json"
        legacy_record_path = args.output / "repair-record.json"
        existing_path = (
            record_set_path if record_set_path.exists() else legacy_record_path
        )
        records = load_repair_records(existing_path)
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
            f"Structural repair {action_label} and applied to a candidate only."
        )
        print(wrapped("Before stem", record.before_stem, args.width))
        print(wrapped("After stem", record.after_stem, args.width))
        print(
            f"Inserted choice: {record.insert_label}: {record.insert_text}"
        )
        print(f"Pipeline classification: {record.disposition}")
        print(f"Candidate: {candidate_path}")
        print(f"Repairs in candidate: {len(records)}")
        print(f"Repair set: {record_set_path}")
        print(f"Canonical Pack unchanged: {args.pack}")
    except (OSError, RepairError) as error:
        raise SystemExit(f"Structural repair stopped: {error}") from error


if __name__ == "__main__":
    main()
