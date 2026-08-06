from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler.repair import load_pack
from compiler.source_audit import audit_private_source_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit one private PrepFlow source against a protected Pack."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = audit_private_source_file(args.source, load_pack(args.pack))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("PrepFlow private source audit complete")
    print(f"Parsed records: {report['parse']['parsed_records']}")
    print(f"Parser findings: {report['parse']['parser_finding_count']}")
    print(f"Exact Pack matches: {report['identity']['exact_matches']}")
    print(f"Source review required: {report['identity']['source_review_required']}")
    print(f"Pack-only records: {report['identity']['pack_only_records']}")
    print(f"Report: {args.output}")
    print("No Pack, candidate, or source text was modified.")


if __name__ == "__main__":
    main()
