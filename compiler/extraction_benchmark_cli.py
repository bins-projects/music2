from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler.extraction_benchmark import write_extraction_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare private PDF text extraction strategies without changing "
            "the source or canonical Pack."
        )
    )
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument(
        "--pack",
        type=Path,
        help=(
            "Optional existing PrepFlow Pack for identity comparison. "
            "Omit for a source-only structural audit."
        ),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=None,
        help=(
            "One or more extraction strategies to run. Defaults to the "
            "three text-layer strategies; rendered OCR runs only when "
            "tesseract_ocr_v1 is named explicitly."
        ),
    )
    args = parser.parse_args()

    manifest = write_extraction_benchmark(
        args.source_pdf,
        args.pack,
        args.output_dir,
        strategies=tuple(args.strategies) if args.strategies else (
            "pypdf_plain_v1",
            "pypdf_layout_v1",
            "pymupdf_sorted_v1",
        ),
        reporter=print,
    )

    print("PrepFlow private extraction benchmark complete")
    print(f"Source SHA-256: {manifest['source_pdf']['sha256']}")
    for name, candidate in manifest["candidates"].items():
        if candidate["status"] == "completed":
            summary = candidate["summary"]
            if "exact_pack_matches" in summary:
                print(
                    f"{name}: {summary['parser_findings']} parser findings; "
                    f"{summary['exact_pack_matches']} exact Pack matches; "
                    f"{summary['source_review_required']} source review required"
                )
            else:
                print(
                    f"{name}: {summary['parsed_records']} parsed records; "
                    f"{summary['parser_findings']} parser findings; "
                    f"{summary['chapter_count']} chapters"
                )
        else:
            print(f"{name}: {candidate['status']} ({candidate['reason']})")

    print(f"Report: {args.output_dir / 'extraction-benchmark.json'}")
    print("No Pack, candidate, source PDF, or canonical source was modified.")
    if args.pack is None:
        print("Source-only audit: no identity comparison or Pack creation was attempted.")


if __name__ == "__main__":
    main()
