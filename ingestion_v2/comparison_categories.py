from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json

from ingestion_v2.comparison import ComparisonReport, FieldChange
from ingestion_v2.comparison_groups import GARBAGE_EVIDENCE_RE
from ingestion_v2.domain import Candidate, DomainError, QuestionRecord, replace_question_field
from dataclasses import replace


@dataclass(frozen=True)
class ComparisonCategory:
    category_id: str
    classification: str
    explanation: str
    changes: tuple[FieldChange, ...]


def categorize_comparison_changes(report: ComparisonReport) -> tuple[ComparisonCategory, ...]:
    repeated_metadata: dict[tuple, list[FieldChange]] = defaultdict(list)
    remaining = []
    for change in report.field_changes:
        if change.field == "chapter_title":
            repeated_metadata[
                (_jsonable(change.benchmark_value), _jsonable(change.candidate_value))
            ].append(change)
        else:
            remaining.append(change)

    categories = []
    for changes in repeated_metadata.values():
        if len(changes) >= 2:
            categories.append(
                _category(
                    "repeated_metadata_difference",
                    "The same chapter metadata difference repeats across a contiguous question set; review it as one source-title decision.",
                    changes,
                )
            )
        else:
            remaining.extend(changes)

    for change in remaining:
        suffix = _appended_suffix(change.candidate_value, change.benchmark_value)
        if suffix and GARBAGE_EVIDENCE_RE.search(suffix):
            classification = "probable_single_contaminant"
            explanation = "One candidate value contains an appended URL, domain, or marketplace fragment requiring individual approval."
        elif suffix:
            classification = "appended_text_review"
            explanation = "One candidate value contains appended text that must be checked against its source context."
        else:
            classification = "content_difference_review"
            explanation = "Candidate and protected-Pack content differ without a safe mechanical classification."
        categories.append(_category(classification, explanation, [change]))

    return tuple(
        sorted(categories, key=lambda item: (item.classification, item.category_id))
    )


def comparison_category_view(category: ComparisonCategory) -> dict:
    return {
        "category_id": category.category_id,
        "classification": category.classification,
        "explanation": category.explanation,
        "change_count": len(category.changes),
        "changes": [
            {"question_id": item.question_id, "field": item.field}
            for item in category.changes
        ],
    }


def apply_category_reference_values(
    candidate: Candidate,
    category: ComparisonCategory,
) -> Candidate:
    question_by_id = {item.question_id: item for item in candidate.questions}
    for change in category.changes:
        question = question_by_id.get(change.question_id)
        if question is None or getattr(question, change.field) != change.candidate_value:
            raise DomainError("Comparison category became stale before correction")
        question_by_id[change.question_id] = replace_question_field(
            question, change.field, change.benchmark_value
        )
    return replace(
        candidate,
        questions=tuple(question_by_id[item.question_id] for item in candidate.questions),
        audit_events=candidate.audit_events + (
            f"{category.category_id}:reference_values_applied_after_explicit_approval",
        ),
    )


def _category(classification: str, explanation: str, changes) -> ComparisonCategory:
    ordered = tuple(sorted(changes, key=lambda item: (item.question_id, item.field)))
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "classification": classification,
                "changes": [
                    (
                        item.question_id,
                        item.field,
                        _jsonable(item.benchmark_value),
                        _jsonable(item.candidate_value),
                    )
                    for item in ordered
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return ComparisonCategory(
        f"PFV2-CATEGORY-{fingerprint}", classification, explanation, ordered
    )


def _appended_suffix(candidate, benchmark) -> str | None:
    if (
        isinstance(candidate, str)
        and isinstance(benchmark, str)
        and candidate.startswith(benchmark)
        and len(candidate) > len(benchmark)
    ):
        return candidate[len(benchmark):]
    return None


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
