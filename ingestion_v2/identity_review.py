from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from compiler.text_repairs import normalize_extraction_typography
from ingestion_v2.domain import DomainError
from ingestion_v2.identity import IdentityReport
from ingestion_v2.parser import ParseBatch


@dataclass(frozen=True)
class IdentitySuggestion:
    target_question_id: str
    target_stem: str
    similarity: float


@dataclass(frozen=True)
class IdentityReviewCase:
    record_id: str
    parsed_stem: str
    chapter: int | None
    finding_code: str
    suggestions: tuple[IdentitySuggestion, ...]


def build_identity_review_cases(
    batch: ParseBatch,
    target_pack: dict,
    report: IdentityReport,
    *,
    limit: int = 3,
) -> tuple[IdentityReviewCase, ...]:
    if limit < 1 or limit > 10:
        raise DomainError("Identity suggestion limit must be between 1 and 10")
    records = {item.record_id: item for item in batch.records}
    targets = target_pack.get("questions")
    if not isinstance(targets, list) or target_pack.get("pack_id") != report.target_pack_id:
        raise DomainError("Identity review target does not match its assessment")
    reserved = {item.target_question_id for item in report.matches}
    cases = []
    for finding in report.findings:
        record = records.get(finding.record_id)
        if record is None:
            raise DomainError("Identity finding references an unknown parsed record")
        ranked = []
        for target in targets:
            if target.get("id") in reserved or _chapter(target.get("chapter")) != record.chapter:
                continue
            target_stem = str(target.get("stem") or "")
            ranked.append(
                IdentitySuggestion(
                    target_question_id=str(target.get("id") or ""),
                    target_stem=target_stem,
                    similarity=round(SequenceMatcher(None, _text(record.stem), _text(target_stem), autojunk=False).ratio(), 6),
                )
            )
        ranked.sort(key=lambda item: (-item.similarity, item.target_question_id))
        cases.append(
            IdentityReviewCase(
                record_id=record.record_id,
                parsed_stem=record.stem,
                chapter=record.chapter,
                finding_code=finding.finding_code,
                suggestions=tuple(ranked[:limit]),
            )
        )
    return tuple(cases)


def authorize_reviewed_identity(
    report: IdentityReport,
    cases: tuple[IdentityReviewCase, ...],
    approvals: dict[str, str],
) -> dict[str, str]:
    mapping = {item.record_id: item.target_question_id for item in report.matches}
    case_by_record = {item.record_id: item for item in cases}
    if not set(approvals).issubset(case_by_record):
        raise DomainError("Identity approval references an unknown review case")
    used = set(mapping.values())
    for record_id, target_id in approvals.items():
        allowed = {item.target_question_id for item in case_by_record[record_id].suggestions}
        if target_id not in allowed:
            raise DomainError("Identity approval must select a displayed suggestion")
        if target_id in used:
            raise DomainError("A stable question ID cannot be assigned twice")
        mapping[record_id] = target_id
        used.add(target_id)
    if len(mapping) != report.parsed_count or len(used) != report.target_count:
        raise DomainError("Identity review remains incomplete")
    return mapping


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(normalize_extraction_typography(value).text.split()).casefold()


def _chapter(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
