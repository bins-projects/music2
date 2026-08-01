import re
from dataclasses import dataclass

from compiler.artifact_profile import learn_overlay_signature
from compiler.pack_qa import audit_choice_structure, finding_id_for_choice_structure
from compiler.repair import (
    Finding,
    RepairEntry,
    StemChoiceSplitRecord,
    apply_repairs,
    create_stem_choice_split_record,
    find_question,
)
from compiler.text_repairs import interleaving_blockers


ABSORBED_MARKER_RE = re.compile(
    r"(?:^|\s)([A-Z])\s*[.):]\s+",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuralBatchPlan:
    proposals: tuple[StemChoiceSplitRecord, ...]
    review_question_ids: tuple[str, ...]


def remove_near_contiguous_signature(
    text: str,
    signature: str,
    *,
    maximum_extra_span: int = 3,
) -> str | None:
    """Remove one tightly grouped learned overlay signature as a subsequence."""
    best_positions = None
    best_span = None
    for start, character in enumerate(text):
        if character != signature[0]:
            continue
        positions = [start]
        cursor = start + 1
        for target in signature[1:]:
            while cursor < len(text) and text[cursor] != target:
                cursor += 1
            if cursor == len(text):
                break
            positions.append(cursor)
            cursor += 1
        if len(positions) != len(signature):
            continue
        span = positions[-1] - positions[0] + 1
        if best_span is None or span < best_span:
            best_positions = positions
            best_span = span

    if best_positions is None:
        return None
    if best_span > len(signature) + maximum_extra_span:
        return None

    removed = set(best_positions)
    return "".join(
        character
        for index, character in enumerate(text)
        if index not in removed
    ).strip()


def plan_clear_absorbed_choices(
    pack: dict,
    records: list[RepairEntry],
) -> StructuralBatchPlan:
    candidate = apply_repairs(pack, records)
    try:
        signature, _ = learn_overlay_signature(records)
    except ValueError:
        signature = ""

    proposals = []
    review = []
    for result in audit_choice_structure(candidate):
        if (
            result.missing_labels != ("A",)
            or result.absorbed_markers != ("A",)
        ):
            review.append(result.question_id)
            continue

        question = find_question(candidate, result.question_id)
        stem = question.get("stem")
        if not isinstance(stem, str):
            review.append(result.question_id)
            continue
        matches = [
            match
            for match in ABSORBED_MARKER_RE.finditer(stem)
            if match.group(1).upper() == "A"
        ]
        if len(matches) != 1:
            review.append(result.question_id)
            continue

        marker = matches[0]
        corrected_stem = stem[:marker.start()].strip()
        choice_text = stem[marker.end():].strip()
        signature_cleanup = (
            remove_near_contiguous_signature(corrected_stem, signature)
            if signature
            else None
        )
        if signature_cleanup is not None:
            corrected_stem = signature_cleanup
        elif interleaving_blockers(corrected_stem):
            corrected_stem = None
        if (
            not corrected_stem
            or not choice_text
            or not corrected_stem.endswith("?")
            or interleaving_blockers(corrected_stem)
            or interleaving_blockers(choice_text)
        ):
            review.append(result.question_id)
            continue

        finding = Finding(
            finding_id=finding_id_for_choice_structure(result),
            question_id=result.question_id,
            field="stem",
            damage_type=(
                "choice structure: high-confidence absorbed leading choice"
            ),
        )
        proposals.append(
            create_stem_choice_split_record(
                pack,
                finding,
                corrected_stem,
                insert_label="A",
                insert_text=choice_text,
                insert_index=0,
                disposition="parser_candidate",
            )
        )

    return StructuralBatchPlan(
        proposals=tuple(proposals),
        review_question_ids=tuple(review),
    )
