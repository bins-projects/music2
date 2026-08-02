from __future__ import annotations

from dataclasses import dataclass

from compiler.pack_qa import (
    audit_choice_structure,
    audit_interleaving,
    audit_merged_questions,
    audit_typography,
)
from compiler.structural_batch import plan_embedded_middle_choices
from ingestion_v2.domain import Finding, FindingSeverity, QuestionRecord


@dataclass(frozen=True)
class QaResult:
    findings: tuple[Finding, ...]
    detector_counts: tuple[tuple[str, int], ...]
    automatic_repairs: int = 0
    proposals_created: int = 0


def detect_candidate_damage(questions: tuple[QuestionRecord, ...]) -> QaResult:
    """Run proven detectors and emit findings only; never apply a repair."""
    pack = questions_to_detection_pack(questions)
    raw: list[tuple[str, str, str, str]] = []

    typography = [item for item in audit_typography(pack) if not item.balanced_after]
    raw.extend(
        (
            item.question_id,
            _field(item.field),
            "unbalanced_quotation_marks",
            "Directional quotation marks remain unbalanced after safe typography normalization.",
        )
        for item in typography
    )

    interleaving = audit_interleaving(pack)
    raw.extend(
        (
            item.question_id,
            _field(item.field),
            item.severity + "__" + "__".join(item.blocker_codes),
            f"{item.severity.replace('_', ' ')} detected: {', '.join(item.blocker_codes)}.",
        )
        for item in interleaving
    )

    choice_structure = audit_choice_structure(pack)
    raw.extend(
        (
            item.question_id,
            "choices",
            "choice_structure__" + "__".join(item.issue_codes),
            "Choice structure requires review: " + ", ".join(item.issue_codes) + ".",
        )
        for item in choice_structure
    )

    merged = audit_merged_questions(pack)
    raw.extend(
        (
            item.question_id,
            "stem",
            "possible_merged_question",
            "Combined structural signals indicate a possible merged question.",
        )
        for item in merged
    )

    embedded = plan_embedded_middle_choices(pack, [])
    proposal_question_ids = {item.question_id for item in embedded.proposals}
    review_question_ids = set(embedded.review_question_ids)
    raw.extend(
        (
            question_id,
            "choices",
            "embedded_choice_recovery_candidate",
            "A possible embedded choice was detected. Recovery requires a reviewable proposal and explicit approval.",
        )
        for question_id in sorted(proposal_question_ids)
    )
    raw.extend(
        (
            question_id,
            "choices",
            "ambiguous_embedded_choice",
            "Possible embedded-choice evidence is ambiguous and remains blocked for review.",
        )
        for question_id in sorted(review_question_ids - proposal_question_ids)
    )

    findings = tuple(
        Finding(
            finding_id=f"PFV2-FIND-QA-{index:06d}",
            question_id=question_id,
            field=field,
            damage_type=damage_type,
            severity=FindingSeverity.BLOCKING,
            explanation=explanation,
        )
        for index, (question_id, field, damage_type, explanation) in enumerate(raw, start=1)
    )
    counts = (
        ("typography", len(typography)),
        ("interleaving", len(interleaving)),
        ("choice_structure", len(choice_structure)),
        ("merged_question", len(merged)),
        ("embedded_choice", len(proposal_question_ids | review_question_ids)),
    )
    return QaResult(findings=findings, detector_counts=counts)


def questions_to_detection_pack(questions: tuple[QuestionRecord, ...]) -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "v2_isolated_detection",
        "questions": [
            {
                "id": item.question_id,
                "chapter": item.chapter,
                "chapter_title": item.chapter_title,
                "type": _pack_type(item.question_type),
                "stem": item.stem,
                "choices": [
                    {"label": label, "text": text} for label, text in item.choices
                ],
                "correct_answers": list(item.correct_answers),
                "rationale": item.rationale,
            }
            for item in questions
        ],
    }


def _pack_type(value: str) -> str:
    return "mc" if value == "multiple_choice" else value


def _field(value: str) -> str:
    return "choices" if value.startswith("choices[") else value
