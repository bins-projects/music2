from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_v2.domain import Candidate, DomainError, QuestionRecord


COMPARISON_FIELDS = (
    "chapter",
    "chapter_title",
    "question_type",
    "stem",
    "choices",
    "correct_answers",
    "rationale",
)


@dataclass(frozen=True)
class FieldChange:
    question_id: str
    field: str
    benchmark_value: Any
    candidate_value: Any


@dataclass(frozen=True)
class ComparisonReport:
    benchmark_question_count: int
    candidate_question_count: int
    stable_ids_exact: bool
    field_changes: tuple[FieldChange, ...]
    complete: bool


def compare_candidate(
    candidate: Candidate,
    benchmark_questions: tuple[QuestionRecord, ...],
) -> ComparisonReport:
    """Compare one isolated candidate with an immutable, stable-ID benchmark."""
    candidate_map = _question_map(candidate.questions, "candidate")
    benchmark_map = _question_map(benchmark_questions, "benchmark")
    if set(candidate_map) != set(benchmark_map):
        missing = len(set(benchmark_map) - set(candidate_map))
        added = len(set(candidate_map) - set(benchmark_map))
        raise DomainError(
            f"Comparison stopped: stable ID sets differ (missing={missing}, added={added})"
        )

    changes = []
    for question_id in sorted(candidate_map):
        candidate_question = candidate_map[question_id]
        benchmark_question = benchmark_map[question_id]
        for field in COMPARISON_FIELDS:
            candidate_value = getattr(candidate_question, field)
            benchmark_value = getattr(benchmark_question, field)
            if candidate_value != benchmark_value:
                changes.append(
                    FieldChange(
                        question_id=question_id,
                        field=field,
                        benchmark_value=benchmark_value,
                        candidate_value=candidate_value,
                    )
                )
    return ComparisonReport(
        benchmark_question_count=len(benchmark_map),
        candidate_question_count=len(candidate_map),
        stable_ids_exact=True,
        field_changes=tuple(changes),
        complete=True,
    )


def comparison_view(report: ComparisonReport) -> dict:
    return {
        "state": "complete" if report.complete else "incomplete",
        "benchmark_question_count": report.benchmark_question_count,
        "candidate_question_count": report.candidate_question_count,
        "stable_ids_exact": report.stable_ids_exact,
        "field_change_count": len(report.field_changes),
        "field_changes": [
            {
                "question_id": change.question_id,
                "field": change.field,
                "benchmark_value": change.benchmark_value,
                "candidate_value": change.candidate_value,
            }
            for change in report.field_changes
        ],
    }


def _question_map(questions: tuple[QuestionRecord, ...], label: str) -> dict[str, QuestionRecord]:
    result = {}
    for question in questions:
        if question.question_id in result:
            raise DomainError(f"{label.capitalize()} contains duplicate stable IDs")
        result[question.question_id] = question
    return result
