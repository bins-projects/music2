from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compiler.text_repairs import normalize_extraction_typography
from ingestion_v2.domain import DomainError, QUESTION_ID_RE
from ingestion_v2.parser import ParseBatch, ParsedRecord


@dataclass(frozen=True)
class IdentityMatch:
    record_id: str
    target_question_id: str
    classification: str = "exact_unique_stem_same_chapter"


@dataclass(frozen=True)
class IdentityFinding:
    record_id: str
    finding_code: str
    candidate_question_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityReport:
    target_pack_id: str
    parsed_count: int
    target_count: int
    matches: tuple[IdentityMatch, ...]
    findings: tuple[IdentityFinding, ...]
    target_only_question_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return (
            not self.findings
            and not self.target_only_question_ids
            and len(self.matches) == self.parsed_count == self.target_count
        )

    @property
    def stable_id_by_record_id(self) -> dict[str, str]:
        if not self.complete:
            raise DomainError("Stable IDs cannot be authorized while identity findings remain")
        return {item.record_id: item.target_question_id for item in self.matches}

    def view(self) -> dict[str, Any]:
        return {
            "state": "complete" if self.complete else "review_required",
            "strategy": "existing_pack_exact_unique_stem_same_chapter",
            "target_pack_id": self.target_pack_id,
            "parsed_count": self.parsed_count,
            "target_count": self.target_count,
            "matched_count": len(self.matches),
            "finding_count": len(self.findings),
            "target_only_count": len(self.target_only_question_ids),
            "automatic_id_assignments_authorized": self.complete,
            "matches": [item.__dict__ for item in self.matches],
            "findings": [
                {
                    "record_id": item.record_id,
                    "finding_code": item.finding_code,
                    "candidate_question_ids": list(item.candidate_question_ids),
                }
                for item in self.findings
            ],
            "target_only_question_ids": list(self.target_only_question_ids),
        }


def match_existing_pack_identity(batch: ParseBatch, target_pack: dict) -> IdentityReport:
    """Find conservative existing-Pack identities without changing either input."""
    pack_id, targets = _validate_target_pack(target_pack)
    by_key: dict[tuple[int | None, str], list[dict]] = {}
    for target in targets:
        by_key.setdefault((_chapter(target.get("chapter")), _text(target.get("stem"))), []).append(target)

    matches: list[IdentityMatch] = []
    findings: list[IdentityFinding] = []
    assigned: set[str] = set()
    for record in batch.records:
        key = (record.chapter, _text(record.stem))
        candidates = by_key.get(key, []) if key[1] else []
        available = [item for item in candidates if item["id"] not in assigned]
        if len(candidates) == 1 and len(available) == 1:
            question_id = available[0]["id"]
            assigned.add(question_id)
            matches.append(IdentityMatch(record.record_id, question_id))
        elif candidates:
            findings.append(
                IdentityFinding(
                    record_id=record.record_id,
                    finding_code="ambiguous_exact_identity",
                    candidate_question_ids=tuple(sorted(item["id"] for item in candidates)),
                )
            )
        else:
            findings.append(
                IdentityFinding(
                    record_id=record.record_id,
                    finding_code="changed_or_unmatched_identity",
                )
            )

    target_only = tuple(sorted(item["id"] for item in targets if item["id"] not in assigned))
    return IdentityReport(
        target_pack_id=pack_id,
        parsed_count=len(batch.records),
        target_count=len(targets),
        matches=tuple(matches),
        findings=tuple(findings),
        target_only_question_ids=target_only,
    )


def _validate_target_pack(pack: dict) -> tuple[str, list[dict]]:
    if not isinstance(pack, dict) or pack.get("format") != "prepflow_pack":
        raise DomainError("Identity target must be a PrepFlow Pack")
    pack_id = pack.get("pack_id")
    questions = pack.get("questions")
    if not isinstance(pack_id, str) or not pack_id or not isinstance(questions, list):
        raise DomainError("Identity target Pack metadata is malformed")
    ids = []
    for question in questions:
        if not isinstance(question, dict) or not QUESTION_ID_RE.fullmatch(str(question.get("id") or "")):
            raise DomainError("Identity target contains an invalid stable question ID")
        ids.append(question["id"])
    if len(ids) != len(set(ids)):
        raise DomainError("Identity target contains duplicate stable question IDs")
    return pack_id, questions


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(normalize_extraction_typography(value).text.split()).casefold()


def _chapter(value: object) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
