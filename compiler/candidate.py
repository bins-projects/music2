import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from compiler.pack_qa import (
    audit_typography,
    choice_structure_repair_findings,
    finding_id_for_typography,
    interleaving_repair_findings,
    iter_question_text,
)
from compiler.repair import (
    DuplicateChoiceBlockRecord,
    Finding,
    RepairRecord,
    StemChoiceSplitRecord,
    analyze_repair_delta,
    apply_repairs,
    set_text_field,
)
from compiler.text_repairs import (
    apply_approved_text_repairs,
    normalize_extraction_typography,
)


@dataclass(frozen=True)
class CandidateBuildResult:
    candidate: dict
    manual_repairs: int
    manual_repair_lessons: tuple[tuple[str, int], ...]
    approved_text_fields_changed: int
    approved_text_rule_fields: tuple[tuple[str, int], ...]
    typography_fields_changed: int
    opening_marks_replaced: int
    closing_marks_replaced: int
    apostrophes_replaced: int
    promotion_blockers: tuple[Finding, ...]


def build_candidate(
    pack: dict,
    records: list[
        RepairRecord | StemChoiceSplitRecord | DuplicateChoiceBlockRecord
    ],
) -> CandidateBuildResult:
    candidate = apply_repairs(pack, records)
    manual_repair_lessons = Counter()
    for record in records:
        if isinstance(record, StemChoiceSplitRecord):
            manual_repair_lessons["stem_choice_split"] += 1
        elif isinstance(record, DuplicateChoiceBlockRecord):
            manual_repair_lessons["exact_duplicate_choice_block_removed"] += 1
        else:
            lesson = analyze_repair_delta(
                record.before,
                record.after,
            ).classification
            manual_repair_lessons[lesson] += 1
    approved_fields_changed = 0
    approved_rule_fields = Counter()
    for question in candidate["questions"]:
        for field, text in tuple(iter_question_text(question)):
            repaired = apply_approved_text_repairs(text)
            if repaired.text == text:
                continue
            set_text_field(question, field, repaired.text)
            approved_fields_changed += 1
            approved_rule_fields.update(repaired.applied_rule_ids)

    typography = audit_typography(candidate)
    unbalanced = [item for item in typography if not item.balanced_after]

    opening_marks = 0
    closing_marks = 0
    apostrophes = 0
    for question in candidate["questions"]:
        for field, text in tuple(iter_question_text(question)):
            normalized = normalize_extraction_typography(text)
            if not (
                normalized.opening_marks_replaced
                or normalized.closing_marks_replaced
                or normalized.apostrophes_replaced
            ):
                continue

            set_text_field(question, field, normalized.text)
            opening_marks += normalized.opening_marks_replaced
            closing_marks += normalized.closing_marks_replaced
            apostrophes += normalized.apostrophes_replaced

    typography_blockers = tuple(
        Finding(
            finding_id=finding_id_for_typography(item),
            question_id=item.question_id,
            field=item.field,
            damage_type="unbalanced directional quotation marks",
        )
        for item in unbalanced
    )
    blocker_by_field = {
        (item.question_id, item.field): item
        for item in interleaving_repair_findings(candidate)
    }
    for item in choice_structure_repair_findings(candidate):
        key = (item.question_id, item.field)
        existing = blocker_by_field.get(key)
        if existing is None:
            blocker_by_field[key] = item
        else:
            blocker_by_field[key] = Finding(
                finding_id=existing.finding_id,
                question_id=existing.question_id,
                field=existing.field,
                damage_type=existing.damage_type + "; " + item.damage_type,
            )
    for item in typography_blockers:
        key = (item.question_id, item.field)
        existing = blocker_by_field.get(key)
        if existing is None:
            blocker_by_field[key] = item
        else:
            blocker_by_field[key] = Finding(
                finding_id=existing.finding_id,
                question_id=existing.question_id,
                field=existing.field,
                damage_type=(
                    existing.damage_type
                    + "; unbalanced directional quotation marks"
                ),
            )

    return CandidateBuildResult(
        candidate=candidate,
        manual_repairs=len(records),
        manual_repair_lessons=tuple(sorted(manual_repair_lessons.items())),
        approved_text_fields_changed=approved_fields_changed,
        approved_text_rule_fields=tuple(sorted(approved_rule_fields.items())),
        typography_fields_changed=len(typography),
        opening_marks_replaced=opening_marks,
        closing_marks_replaced=closing_marks,
        apostrophes_replaced=apostrophes,
        promotion_blockers=tuple(blocker_by_field.values()),
    )


def candidate_manifest(result: CandidateBuildResult) -> dict:
    return {
        "format": "prepflow_candidate_manifest",
        "version": "1.0",
        "pack_id": result.candidate["pack_id"],
        "transformations": {
            "manual_repairs": result.manual_repairs,
            "manual_repair_lessons": dict(result.manual_repair_lessons),
            "approved_text_repairs": {
                "fields_changed": result.approved_text_fields_changed,
                "rule_fields": dict(result.approved_text_rule_fields),
            },
            "typography_normalization": {
                "fields_changed": result.typography_fields_changed,
                "opening_marks_replaced": result.opening_marks_replaced,
                "closing_marks_replaced": result.closing_marks_replaced,
                "apostrophes_replaced": result.apostrophes_replaced,
            },
        },
        "promotion_blockers": [
            asdict(item) for item in result.promotion_blockers
        ],
    }


def write_candidate_manifest(
    result: CandidateBuildResult,
    path: str | Path,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(candidate_manifest(result), file, indent=2, ensure_ascii=False)
        file.write("\n")
    temporary.replace(destination)
    return destination
