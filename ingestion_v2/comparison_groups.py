from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re

from ingestion_v2.comparison import ComparisonReport, compare_candidate
from ingestion_v2.domain import Candidate, DomainError, QuestionRecord, replace_question_field


GARBAGE_EVIDENCE_RE = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net)\b|marketplace)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContaminantOccurrence:
    question_id: str
    field: str
    before: object
    after: object


@dataclass(frozen=True)
class ContaminantGroup:
    group_id: str
    contaminant: str
    occurrences: tuple[ContaminantOccurrence, ...]


def detect_exact_contaminant_groups(report: ComparisonReport) -> tuple[ContaminantGroup, ...]:
    by_contaminant: dict[str, list[ContaminantOccurrence]] = {}
    for change in report.field_changes:
        contaminant = _exact_appended_contaminant(
            change.candidate_value, change.benchmark_value
        )
        if not contaminant or not GARBAGE_EVIDENCE_RE.search(contaminant):
            continue
        by_contaminant.setdefault(contaminant, []).append(
            ContaminantOccurrence(
                change.question_id,
                change.field,
                change.candidate_value,
                change.benchmark_value,
            )
        )
    groups = []
    for contaminant, occurrences in sorted(by_contaminant.items()):
        if len(occurrences) < 2:
            continue
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "contaminant": contaminant,
                    "targets": [(item.question_id, item.field) for item in occurrences],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        groups.append(
            ContaminantGroup(
                group_id=f"PFV2-GROUP-{fingerprint}",
                contaminant=contaminant,
                occurrences=tuple(occurrences),
            )
        )
    return tuple(groups)


def apply_exact_contaminant_group(
    candidate: Candidate,
    benchmark: tuple[QuestionRecord, ...],
    group_id: str,
) -> tuple[Candidate, ContaminantGroup]:
    report = compare_candidate(candidate, benchmark)
    groups = {item.group_id: item for item in detect_exact_contaminant_groups(report)}
    group = groups.get(group_id)
    if group is None:
        raise DomainError("Exact contaminant group is missing or no longer current")
    question_by_id = {item.question_id: item for item in candidate.questions}
    for occurrence in group.occurrences:
        question = question_by_id.get(occurrence.question_id)
        if question is None or getattr(question, occurrence.field) != occurrence.before:
            raise DomainError("Exact contaminant group became stale before application")
        question_by_id[occurrence.question_id] = replace_question_field(
            question, occurrence.field, occurrence.after
        )
    return (
        replace(
            candidate,
            questions=tuple(question_by_id[item.question_id] for item in candidate.questions),
            audit_events=candidate.audit_events + (
                f"{group.group_id}:exact_contaminant_group_applied_after_explicit_approval",
            ),
        ),
        group,
    )


def contaminant_group_view(group: ContaminantGroup) -> dict:
    return {
        "group_id": group.group_id,
        "contaminant": group.contaminant,
        "match_count": len(group.occurrences),
        "occurrences": [
            {
                "question_id": item.question_id,
                "field": item.field,
                "broken_value": item.before,
                "corrected_value": item.after,
            }
            for item in group.occurrences
        ],
        "scope": "exact_text_and_exact_targets_only",
        "requires_explicit_approval": True,
    }


def _exact_appended_contaminant(candidate, benchmark) -> str | None:
    if isinstance(candidate, str) and isinstance(benchmark, str):
        if candidate.startswith(benchmark) and len(candidate) > len(benchmark):
            return candidate[len(benchmark):]
        return None
    if not isinstance(candidate, (tuple, list)) or not isinstance(benchmark, (tuple, list)):
        return None
    if len(candidate) != len(benchmark):
        return None
    suffixes = []
    for candidate_item, benchmark_item in zip(candidate, benchmark):
        if candidate_item == benchmark_item:
            continue
        if (
            not isinstance(candidate_item, (tuple, list))
            or not isinstance(benchmark_item, (tuple, list))
            or len(candidate_item) != 2
            or len(benchmark_item) != 2
            or candidate_item[0] != benchmark_item[0]
            or not isinstance(candidate_item[1], str)
            or not isinstance(benchmark_item[1], str)
            or not candidate_item[1].startswith(benchmark_item[1])
        ):
            return None
        suffixes.append(candidate_item[1][len(benchmark_item[1]):])
    return suffixes[0] if suffixes and len(set(suffixes)) == 1 else None
