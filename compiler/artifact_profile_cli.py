import argparse
from pathlib import Path

from compiler.artifact_profile import profile_pack_artifacts
from compiler.repair import RepairError, load_pack, load_repair_records
from compiler.repair_cli import DEFAULT_OUTPUT, DEFAULT_PACK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Learn an in-memory artifact signature from approved repairs and "
            "score unresolved fields without rewriting them."
        )
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        pack = load_pack(args.pack)
        records = load_repair_records(args.output / "repair-records.json")
        result = profile_pack_artifacts(pack, records)
    except (OSError, RepairError) as error:
        raise SystemExit(f"Artifact profile stopped: {error}") from error

    print("PrepFlow temporary artifact-profile dry run")
    print(f"Approved overlay repairs learned from: {result.training_repairs}")
    print(f"In-memory signature length: {result.signature_length}")
    print(f"Unresolved fields scored: {result.unresolved_fields}")
    for classification, count in result.evidence_counts:
        print(f"{classification}: {count}")
    print()
    print("The learned signature was not printed or stored.")
    print("Dry run only. No Pack, candidate, or repair record was written.")


if __name__ == "__main__":
    main()
