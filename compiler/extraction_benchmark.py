from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from compiler.source_audit import audit_private_source


ProgressReporter = Callable[[str], None]
Extractor = Callable[[Path, ProgressReporter | None], tuple[str, ...]]
EXTRACTOR_NAMES = (
    "pypdf_plain_v1",
    "pypdf_layout_v1",
    "pymupdf_sorted_v1",
)


def _joined_pages(pages: tuple[str, ...]) -> str:
    return "\n\f\n".join(pages)


def _report_page_progress(
    reporter: ProgressReporter | None,
    name: str,
    current: int,
    total: int,
) -> None:
    if reporter and (current == 1 or current % 25 == 0 or current == total):
        reporter(f"{name}: extracting page {current}/{total}")


def _pypdf_plain_pages(
    source_path: Path,
    reporter: ProgressReporter | None = None,
) -> tuple[str, ...]:
    reader = PdfReader(source_path)
    pages: list[str] = []
    total = len(reader.pages)

    for page_number, page in enumerate(reader.pages, start=1):
        _report_page_progress(reporter, "pypdf_plain_v1", page_number, total)
        pages.append(page.extract_text() or "")

    return tuple(pages)


def _pypdf_layout_pages(
    source_path: Path,
    reporter: ProgressReporter | None = None,
) -> tuple[str, ...]:
    reader = PdfReader(source_path)
    pages: list[str] = []
    total = len(reader.pages)

    for page_number, page in enumerate(reader.pages, start=1):
        _report_page_progress(reporter, "pypdf_layout_v1", page_number, total)
        pages.append(page.extract_text(extraction_mode="layout") or "")

    return tuple(pages)


def _pymupdf_sorted_pages(
    source_path: Path,
    reporter: ProgressReporter | None = None,
) -> tuple[str, ...]:
    import fitz

    document = fitz.open(source_path)
    try:
        pages: list[str] = []
        total = len(document)

        for page_number, page in enumerate(document, start=1):
            _report_page_progress(
                reporter,
                "pymupdf_sorted_v1",
                page_number,
                total,
            )
            pages.append(page.get_text("text", sort=True))

        return tuple(pages)
    finally:
        document.close()


def _audit_summary(report: dict[str, Any]) -> dict[str, int]:
    return {
        "page_count": report["source"]["page_count"],
        "raw_characters": report["source"]["raw_characters"],
        "parsed_records": report["parse"]["parsed_records"],
        "parser_findings": report["parse"]["parser_finding_count"],
        "exact_pack_matches": report["identity"]["exact_matches"],
        "source_review_required": report["identity"]["source_review_required"],
        "pack_only_records": report["identity"]["pack_only_records"],
    }


def run_extraction_benchmark(
    source_path: str | Path,
    target_pack: dict[str, Any],
    *,
    strategies: tuple[str, ...] = EXTRACTOR_NAMES,
    reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """
    Compare private PDF text extraction strategies without mutating any Pack.

    A missing optional extractor is recorded as unavailable rather than being
    installed or silently substituted.
    """

    unknown = set(strategies).difference(EXTRACTOR_NAMES)
    if unknown:
        raise ValueError(
            f"Unknown extraction strategy: {', '.join(sorted(unknown))}"
        )

    source = Path(source_path)
    source_bytes = source.read_bytes()
    available_extractors: dict[str, Extractor] = {
        "pypdf_plain_v1": _pypdf_plain_pages,
        "pypdf_layout_v1": _pypdf_layout_pages,
        "pymupdf_sorted_v1": _pymupdf_sorted_pages,
    }
    candidates: dict[str, dict[str, Any]] = {}

    for name in strategies:
        extractor = available_extractors[name]
        if reporter:
            reporter(f"{name}: starting")

        try:
            pages = extractor(source, reporter)
        except ModuleNotFoundError as error:
            candidates[name] = {
                "status": "unavailable",
                "reason": f"Optional module is unavailable: {error.name}",
            }
            continue
        except Exception as error:
            candidates[name] = {
                "status": "failed",
                "reason": f"{type(error).__name__}: {error}",
            }
            continue

        raw_text = _joined_pages(pages)
        if reporter:
            reporter(f"{name}: auditing extracted text")
        audit = audit_private_source(raw_text, target_pack)
        candidates[name] = {
            "status": "completed",
            "raw_text": raw_text,
            "audit": audit,
            "summary": _audit_summary(audit),
        }

    return {
        "format": "prepflow_private_extraction_benchmark",
        "version": "1.1",
        "safety": {
            "source_private_only": True,
            "pack_write_available": False,
            "automatic_repairs_applied": 0,
        },
        "source_pdf": {
            "filename": source.name,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "bytes": len(source_bytes),
        },
        "candidates": candidates,
    }


def write_extraction_benchmark(
    source_path: str | Path,
    target_pack_path: str | Path,
    output_directory: str | Path,
    *,
    strategies: tuple[str, ...] = EXTRACTOR_NAMES,
    reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    source = Path(source_path)
    pack = json.loads(Path(target_pack_path).read_text(encoding="utf-8"))
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)

    benchmark = run_extraction_benchmark(
        source,
        pack,
        strategies=strategies,
        reporter=reporter,
    )
    manifest_candidates: dict[str, dict[str, Any]] = {}

    for name, candidate in benchmark["candidates"].items():
        manifest_candidate = {
            key: value
            for key, value in candidate.items()
            if key not in {"raw_text", "audit"}
        }

        if candidate["status"] == "completed":
            text_path = output / f"{name}.txt"
            audit_path = output / f"{name}.audit.json"
            text_path.write_text(candidate["raw_text"], encoding="utf-8")
            audit_path.write_text(
                json.dumps(candidate["audit"], indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_candidate["raw_text_file"] = text_path.name
            manifest_candidate["audit_file"] = audit_path.name

        manifest_candidates[name] = manifest_candidate

    manifest = {
        **{
            key: value
            for key, value in benchmark.items()
            if key != "candidates"
        },
        "candidates": manifest_candidates,
    }
    manifest_path = output / "extraction-benchmark.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
