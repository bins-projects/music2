from __future__ import annotations

from compiler.structural_batch import plan_embedded_middle_choices
from ingestion_v2.domain import DomainError, Finding, Proposal, QuestionRecord
from ingestion_v2.qa_adapter import questions_to_detection_pack


def draft_deterministic_proposals(
    questions: tuple[QuestionRecord, ...],
    findings: tuple[Finding, ...],
) -> tuple[Proposal, ...]:
    """Draft review-only v2 proposals from exact deterministic plans."""
    finding_by_target = {
        (item.question_id, item.field, item.damage_type): item
        for item in findings
    }
    pack = questions_to_detection_pack(questions)
    plan = plan_embedded_middle_choices(pack, [])
    proposals = []
    for index, item in enumerate(plan.proposals, start=1):
        finding = finding_by_target.get(
            (item.question_id, "choices", "embedded_choice_recovery_candidate")
        )
        if finding is None:
            raise DomainError("Deterministic proposal has no matching v2 finding")
        if item.expected_correct_answers != item.replacement_correct_answers:
            raise DomainError("Embedded-choice proposal cannot alter the answer key")
        proposals.append(
            Proposal(
                proposal_id=f"PFV2-PROP-EMBEDDED-{index:06d}",
                finding_id=finding.finding_id,
                question_id=item.question_id,
                field="choices",
                expected_before=item.expected_choices,
                proposed_after=item.replacement_choices,
                explanation=(
                    "Move the single detected missing-label text segment into its own "
                    "choice without changing wording or the answer key."
                ),
                requires_source_verification=False,
            )
        )
    return tuple(proposals)
