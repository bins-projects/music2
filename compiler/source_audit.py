from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ingestion_v2.cleaning import GuardedPageAwareCleaner
from ingestion_v2.identity import match_existing_pack_identity
from ingestion_v2.parser import ExistingParserAdapter, ParsedRecord


def _record_view(record: ParsedRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "chapter": record.chapter,
        "chapter_title": record.chapter_title,
        "source_question_number": record.source_question_number,
        "question_type": record.question_type,
        "stem": record.stem,
        "choices": [list(choice) for choice in record.choices],
        "correct_answers": list(record.correct_answers),
        "rationale_present": bool(record.rationale),
    }


def _chapter_views(
    batch,
) -> list[dict[str, Any]]:
    records = {record.record_id: record for record in batch.records}
    record_counts: Counter[tuple[int | None, str]] = Counter(
        (record.chapter, record.chapter_title)
        for record in batch.records
    )
    finding_counts: Counter[tuple[int | None, str]] = Counter(
        (
            records[finding.record_id].chapter,
            records[finding.record_id].chapter_title,
        )
        for finding in batch.findings
    )

    return [
        {
            "chapter": chapter,
            "chapter_title": chapter_title,
            "parsed_records": record_counts[(chapter, chapter_title)],
            "parser_findings": finding_counts[(chapter, chapter_title)],
        }
        for chapter, chapter_title in sorted(
            record_counts,
            key=lambda item: (
                item[0] is None,
                item[0] if item[0] is not None else 0,
                item[1].casefold(),
            ),
        )
    ]


def audit_private_source(
    raw_text: str,
    target_pack: dict | None = None,
) -> dict[str, Any]:
    """Inspect a private source read-only and return a reviewable benchmark."""

    cleaning = GuardedPageAwareCleaner().clean(raw_text)
    batch = ExistingParserAdapter().parse(cleaning.text)
    records = {record.record_id: record for record in batch.records}

    parser_by_record: dict[str, list[dict[str, str]]] = defaultdict(list)
    parser_counts: Counter[str] = Counter()
    for finding in batch.findings:
        parser_counts[finding.damage_type] += 1
        parser_by_record[finding.record_id].append(
            {
                "finding_id": finding.finding_id,
                "field": finding.field,
                "damage_type": finding.damage_type,
                "explanation": finding.explanation,
            }
        )

    page_count = len(raw_text.split("\f"))
    share_footer_count = sum(
        1
        for line in raw_text.splitlines()
        if line.strip().casefold().startswith("document shared on")
    )
    watermark_line_count = sum(
        1
        for line in raw_text.splitlines()
        if "nursingtb.com" in line.casefold()
    )

    identity_view = None
    if target_pack is not None:
        identity = match_existing_pack_identity(batch, target_pack)
        identity_counts = Counter(
            item.finding_code
            for item in identity.findings
        )
        identity_view = {
            "target_pack_id": identity.target_pack_id,
            "target_records": identity.target_count,
            "exact_matches": len(identity.matches),
            "source_review_required": len(identity.findings),
            "pack_only_records": len(identity.target_only_question_ids),
            "findings_by_type": dict(sorted(identity_counts.items())),
            "source_records_requiring_review": [
                {
                    **_record_view(records[item.record_id]),
                    "finding_code": item.finding_code,
                    "candidate_question_ids": list(item.candidate_question_ids),
                }
                for item in identity.findings
            ],
            "pack_only_question_ids": list(identity.target_only_question_ids),
        }

    return {
        "format": "prepflow_private_source_audit",
        "version": "1.1",
        "mode": (
            "existing_pack_comparison"
            if target_pack is not None
            else "source_only"
        ),
        "safety": {
            "source_private_only": True,
            "pack_write_available": False,
            "target_pack_supplied": target_pack is not None,
            "automatic_repairs_applied": 0,
        },
        "source": {
            "raw_characters": len(raw_text),
            "page_count": page_count,
            "document_share_footer_lines": share_footer_count,
            "watermark_lines": watermark_line_count,
        },
        "cleaning": {
            "cleaner": cleaning.cleaner_name,
            "removed_repeated_lines": cleaning.removed_repeated_lines,
            "stripped_repeated_suffixes": cleaning.stripped_repeated_suffixes,
            "protected_repeated_structures": cleaning.protected_repeated_structures,
        },
        "parse": {
            "parser": batch.parser_name,
            "parsed_records": len(batch.records),
            "parser_finding_count": len(batch.findings),
            "parser_findings_by_type": dict(sorted(parser_counts.items())),
            "chapters": _chapter_views(batch),
            "records_with_parser_findings": [
                {
                    **_record_view(records[record_id]),
                    "findings": findings,
                }
                for record_id, findings in sorted(parser_by_record.items())
            ],
        },
        "identity": identity_view,
    }


def audit_private_source_file(
    source_path: str | Path,
    target_pack: dict | None = None,
) -> dict[str, Any]:
    return audit_private_source(
        Path(source_path).read_text(encoding="utf-8"),
        target_pack,
    )
