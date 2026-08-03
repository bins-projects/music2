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


def draft_benchmark_answer_proposals(
    questions: tuple[QuestionRecord, ...],
    benchmark: tuple[QuestionRecord, ...],
    findings: tuple[Finding, ...],
) -> tuple[Proposal, ...]:
    """Use a valid benchmark answer only as a source-verification-required draft."""
    question_by_id = {item.question_id: item for item in questions}
    benchmark_by_id = {item.question_id: item for item in benchmark}
    proposals = []
    eligible = [item for item in findings if item.damage_type == "correct_answer_without_choice"]
    for index, finding in enumerate(eligible, start=1):
        question = question_by_id[finding.question_id]
        reference = benchmark_by_id.get(finding.question_id)
        labels = {label for label, _ in question.choices}
        if (
            reference is None
            or not reference.correct_answers
            or any(answer not in labels for answer in reference.correct_answers)
            or reference.correct_answers == question.correct_answers
        ):
            continue
        proposals.append(
            Proposal(
                proposal_id=f"PFV2-PROP-ANSWER-{index:06d}",
                finding_id=finding.finding_id,
                question_id=finding.question_id,
                field="correct_answers",
                expected_before=question.correct_answers,
                proposed_after=reference.correct_answers,
                explanation="The protected benchmark supplies a structurally valid answer candidate; temporary source-page verification is required.",
                requires_source_verification=True,
            )
        )
    return tuple(proposals)
