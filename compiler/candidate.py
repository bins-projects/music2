import json
from dataclasses import asdict, dataclass
from pathlib import Path

from compiler.pack_qa import (
    audit_typography,
    finding_id_for_typography,
    interleaving_repair_findings,
    iter_question_text,
)
from compiler.repair import (
    Finding,
    RepairRecord,
    apply_repairs,
    set_text_field,
)
from compiler.text_repairs import normalize_extraction_typography


@dataclass(frozen=True)
class CandidateBuildResult:
    candidate: dict
    manual_repairs: int
    typography_fields_changed: int
    opening_marks_replaced: int
    closing_marks_replaced: int
    promotion_blockers: tuple[Finding, ...]


def build_candidate(
    pack: dict,
    records: list[RepairRecord],
) -> CandidateBuildResult:
    candidate = apply_repairs(pack, records)
    typography = audit_typography(candidate)
    unbalanced = [item for item in typography if not item.balanced_after]

    opening_marks = 0
    closing_marks = 0
    for question in candidate["questions"]:
        for field, text in tuple(iter_question_text(question)):
            normalized = normalize_extraction_typography(text)
            if not (
                normalized.opening_marks_replaced
                or normalized.closing_marks_replaced
            ):
                continue

            set_text_field(question, field, normalized.text)
            opening_marks += normalized.opening_marks_replaced
            closing_marks += normalized.closing_marks_replaced

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
        typography_fields_changed=len(typography),
        opening_marks_replaced=opening_marks,
        closing_marks_replaced=closing_marks,
        promotion_blockers=tuple(blocker_by_field.values()),
    )


def candidate_manifest(result: CandidateBuildResult) -> dict:
    return {
        "format": "prepflow_candidate_manifest",
        "version": "1.0",
        "pack_id": result.candidate["pack_id"],
        "transformations": {
            "manual_repairs": result.manual_repairs,
            "typography_normalization": {
                "fields_changed": result.typography_fields_changed,
                "opening_marks_replaced": result.opening_marks_replaced,
                "closing_marks_replaced": result.closing_marks_replaced,
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
