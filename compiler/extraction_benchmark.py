from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from compiler.source_audit import audit_private_source


Extractor = Callable[[Path], tuple[str, ...]]


def _joined_pages(pages: tuple[str, ...]) -> str:
    return "\n\f\n".join(pages)


def _pypdf_plain_pages(source_path: Path) -> tuple[str, ...]:
    reader = PdfReader(source_path)
    return tuple(page.extract_text() or "" for page in reader.pages)


def _pypdf_layout_pages(source_path: Path) -> tuple[str, ...]:
    reader = PdfReader(source_path)
    return tuple(
        page.extract_text(extraction_mode="layout") or ""
        for page in reader.pages
    )


def _pymupdf_sorted_pages(source_path: Path) -> tuple[str, ...]:
    import fitz

    document = fitz.open(source_path)
    try:
        return tuple(page.get_text("text", sort=True) for page in document)
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
) -> dict[str, Any]:
    """
    Compare private PDF text extraction strategies without mutating any Pack.

    A missing optional extractor is recorded as unavailable rather than being
    installed or silently substituted.
    """

    source = Path(source_path)
    source_bytes = source.read_bytes()
    extractors: tuple[tuple[str, Extractor], ...] = (
        ("pypdf_plain_v1", _pypdf_plain_pages),
        ("pypdf_layout_v1", _pypdf_layout_pages),
        ("pymupdf_sorted_v1", _pymupdf_sorted_pages),
    )
    candidates: dict[str, dict[str, Any]] = {}

    for name, extractor in extractors:
        try:
            pages = extractor(source)
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
        audit = audit_private_source(raw_text, target_pack)
        candidates[name] = {
            "status": "completed",
            "raw_text": raw_text,
            "audit": audit,
            "summary": _audit_summary(audit),
        }

    return {
        "format": "prepflow_private_extraction_benchmark",
        "version": "1.0",
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
) -> dict[str, Any]:
    source = Path(source_path)
    pack = json.loads(Path(target_pack_path).read_text(encoding="utf-8"))
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)

    benchmark = run_extraction_benchmark(source, pack)
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
