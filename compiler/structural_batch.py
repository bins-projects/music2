import re
from dataclasses import dataclass

from compiler.artifact_profile import learn_overlay_signature
from compiler.pack_qa import audit_choice_structure, finding_id_for_choice_structure
from compiler.repair import (
    ChoiceStructureRepairRecord,
    Finding,
    RepairEntry,
    StemChoiceSplitRecord,
    apply_repairs,
    choice_pairs,
    create_choice_structure_repair_record,
    create_stem_choice_split_record,
    find_question,
)
from compiler.text_repairs import interleaving_blockers


ABSORBED_MARKER_RE = re.compile(
    r"(?:^|\s)([A-Z])\s*[.):]\s+",
    flags=re.IGNORECASE,
)
EMBEDDED_CHOICE_MARKER_RE = re.compile(
    r"(?:^|\s)([a-z])\s*[.):]\s+(?=[A-Z])"
)


@dataclass(frozen=True)
class StructuralBatchPlan:
    proposals: tuple[StemChoiceSplitRecord, ...]
    review_question_ids: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddedChoiceBatchPlan:
    proposals: tuple[ChoiceStructureRepairRecord, ...]
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


def plan_embedded_middle_choices(
    pack: dict,
    records: list[RepairEntry],
) -> EmbeddedChoiceBatchPlan:
    """Plan exact missing-label splits found inside the preceding choice.

    This operation moves existing text only. It requires one missing internal
    label, one matching marker, canonical surviving order, and an unchanged
    answer map. Ambiguous or stale shapes remain in the review queue.
    """
    candidate = apply_repairs(pack, records)
    proposals = []
    review = []

    for result in audit_choice_structure(candidate):
        if len(result.missing_labels) != 1:
            continue
        missing = result.missing_labels[0]
        if missing == "A" or len(result.labels) < 2:
            continue
        expected_without_missing = tuple(
            chr(value)
            for value in range(ord("A"), ord(result.labels[-1]) + 1)
            if chr(value) != missing
        )
        if result.labels != expected_without_missing:
            review.append(result.question_id)
            continue

        question = find_question(candidate, result.question_id)
        before_choices = choice_pairs(question)
        previous_label = chr(ord(missing) - 1)
        previous_indexes = [
            index
            for index, (label, _) in enumerate(before_choices)
            if label.upper() == previous_label
        ]
        if len(previous_indexes) != 1:
            review.append(result.question_id)
            continue

        previous_index = previous_indexes[0]
        previous_text = before_choices[previous_index][1]
        markers = [
            match
            for match in EMBEDDED_CHOICE_MARKER_RE.finditer(previous_text)
            if match.group(1).upper() == missing
        ]
        if len(markers) != 1:
            review.append(result.question_id)
            continue

        marker = markers[0]
        retained_text = previous_text[:marker.start()].strip()
        inserted_text = previous_text[marker.end():].strip()
        if not retained_text or not inserted_text:
            review.append(result.question_id)
            continue

        replacement = list(before_choices)
        replacement[previous_index] = (
            before_choices[previous_index][0],
            retained_text,
        )
        replacement.insert(previous_index + 1, (missing, inserted_text))
        answers = question.get("correct_answers")
        if not isinstance(answers, list) or not answers:
            review.append(result.question_id)
            continue

        repair_id = (
            "PFQA-EMBEDDED-CHOICE-"
            + re.sub(r"[^A-Za-z0-9]+", "-", result.question_id).upper()
            + f"-{missing}"
        )
        proposals.append(
            create_choice_structure_repair_record(
                candidate,
                question_id=result.question_id,
                repair_id=repair_id,
                replacement_choices=tuple(replacement),
                replacement_correct_answers=tuple(str(item) for item in answers),
                damage_type=(
                    "choice structure: exact embedded missing-label split"
                ),
                disposition="parser_candidate",
            )
        )

    return EmbeddedChoiceBatchPlan(
        proposals=tuple(proposals),
        review_question_ids=tuple(dict.fromkeys(review)),
    )
