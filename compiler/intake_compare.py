from dataclasses import asdict
from collections import Counter

from compiler.candidate import build_candidate
from compiler.repair import (
    ChoiceStructureRepairRecord,
    DuplicateChoiceBlockRecord,
    QuestionCorrectionRecord,
    RepairRecord,
    StemChoiceSplitRecord,
)


class IntakeComparisonError(ValueError):
    """Raised when protected comparison inputs do not align safely."""


def _question_map(pack: dict) -> dict[str, dict]:
    questions = pack.get("questions")
    if not isinstance(questions, list):
        raise IntakeComparisonError("Pack questions must be a list")
    result = {}
    for question in questions:
        question_id = question.get("id") if isinstance(question, dict) else None
        if not isinstance(question_id, str) or question_id in result:
            raise IntakeComparisonError("Pack contains invalid or duplicate IDs")
        result[question_id] = question
    return result


def _field_value(question: dict, field: str):
    if field.startswith("choices[") and field.endswith("].text"):
        index = int(field[len("choices[") : field.index("]")])
        return question.get("choices", [])[index].get("text")
    return question.get(field)


def _repair_fields(record) -> tuple[str, ...]:
    if isinstance(record, RepairRecord):
        return (record.field,)
    if isinstance(record, StemChoiceSplitRecord):
        return ("stem", "choices")
    if isinstance(record, DuplicateChoiceBlockRecord):
        return ("choices",)
    if isinstance(record, ChoiceStructureRepairRecord):
        return ("choices", "correct_answers")
    if isinstance(record, QuestionCorrectionRecord):
        return ("stem", "choices", "correct_answers", "rationale")
    raise IntakeComparisonError("Unsupported repair record type")


def _blocker_map(blockers) -> dict[tuple[str, str], dict]:
    result = {}
    for blocker in blockers:
        value = asdict(blocker) if not isinstance(blocker, dict) else blocker
        key = (value["question_id"], value["field"])
        if key in result:
            raise IntakeComparisonError(f"Duplicate blocker key: {key}")
        result[key] = value
    return result


def compare_intake_candidate(
    isolated_pack: dict,
    canonical_pack: dict,
    candidate_24_pack: dict,
    repair_records: list,
    known_blockers: list[dict],
) -> tuple[dict, dict]:
    """Return an evaluated candidate and source-neutral comparison report."""
    evaluated_result = build_candidate(isolated_pack, [])
    evaluated = evaluated_result.candidate
    isolated_map = _question_map(evaluated)
    canonical_map = _question_map(canonical_pack)
    candidate_map = _question_map(candidate_24_pack)
    if set(isolated_map) != set(canonical_map) or set(canonical_map) != set(candidate_map):
        raise IntakeComparisonError("Candidate ID sets do not exactly match")

    fields = ("chapter", "chapter_title", "type", "stem", "choices", "correct_answers", "rationale")
    field_outcomes = []
    counts = {
        "all_equal": 0,
        "matches_candidate_24": 0,
        "matches_canonical": 0,
        "differs_from_both": 0,
    }
    for question_id in sorted(isolated_map):
        for field in fields:
            isolated_value = isolated_map[question_id].get(field)
            canonical_value = canonical_map[question_id].get(field)
            candidate_value = candidate_map[question_id].get(field)
            if isolated_value == canonical_value == candidate_value:
                counts["all_equal"] += 1
                continue
            if isolated_value == candidate_value and candidate_value != canonical_value:
                classification = "matches_candidate_24"
            elif isolated_value == canonical_value and canonical_value != candidate_value:
                classification = "matches_canonical"
            else:
                classification = "differs_from_both"
            counts[classification] += 1
            field_outcomes.append(
                {
                    "question_id": question_id,
                    "field": field,
                    "classification": classification,
                    "canonical_equals_candidate_24": canonical_value == candidate_value,
                }
            )

    lessons = []
    for record in repair_records:
        question_id = record.question_id
        if question_id not in isolated_map:
            raise IntakeComparisonError(f"Repair question is missing: {question_id}")
        record_fields = _repair_fields(record)
        isolated_values = tuple(_field_value(isolated_map[question_id], field) for field in record_fields)
        canonical_values = tuple(_field_value(canonical_map[question_id], field) for field in record_fields)
        candidate_values = tuple(_field_value(candidate_map[question_id], field) for field in record_fields)
        if isolated_values == candidate_values:
            classification = "reproduced"
        elif isolated_values == canonical_values:
            classification = "not_reproduced"
        else:
            classification = "different_result"
        lessons.append(
            {
                "repair_id": record.repair_id,
                "question_id": question_id,
                "fields": list(record_fields),
                "classification": classification,
            }
        )

    current_blockers = _blocker_map(evaluated_result.promotion_blockers)
    baseline_blockers = _blocker_map(known_blockers)
    current_keys = set(current_blockers)
    baseline_keys = set(baseline_blockers)
    reclassified = []
    for key in sorted(current_keys & baseline_keys):
        if current_blockers[key] != baseline_blockers[key]:
            reclassified.append(
                {"known": baseline_blockers[key], "isolated": current_blockers[key]}
            )
    report = {
        "format": "prepflow_intake_candidate_comparison",
        "version": "1.0",
        "pack_id": isolated_pack.get("pack_id"),
        "question_count": len(isolated_map),
        "deterministic_normalization": {
            "manual_repairs": 0,
            "approved_text_fields_changed": evaluated_result.approved_text_fields_changed,
            "typography_fields_changed": evaluated_result.typography_fields_changed,
        },
        "field_outcome_counts": counts,
        "field_outcomes": field_outcomes,
        "repair_lesson_counts": dict(
            sorted(
                Counter(
                    item["classification"] for item in lessons
                ).items()
            )
        ),
        "repair_lessons": lessons,
        "blockers": {
            "known_count": len(baseline_blockers),
            "isolated_count": len(current_blockers),
            "retained_keys": len(current_keys & baseline_keys),
            "removed": [baseline_blockers[key] for key in sorted(baseline_keys - current_keys)],
            "added": [current_blockers[key] for key in sorted(current_keys - baseline_keys)],
            "reclassified": reclassified,
        },
        "promotion_ready": False,
    }
    return evaluated, report
