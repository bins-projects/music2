from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from ingestion_v2.domain import (
    DomainError,
    Finding,
    Proposal,
    QuestionRecord,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
)


class ReviewStatus(str, Enum):
    NEEDS_PROPOSAL = "needs_proposal"
    AWAITING_DECISION = "awaiting_decision"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    AWAITING_SOURCE_VERIFICATION = "awaiting_source_verification"
    APPROVED = "approved"


@dataclass(frozen=True)
class ReviewCase:
    finding: Finding
    question: QuestionRecord
    proposal: Proposal | None
    decision: ReviewDecision | None
    verification: SourceVerification | None
    status: ReviewStatus
    allowed_actions: tuple[str, ...]


@dataclass(frozen=True)
class ReviewQueue:
    cases: tuple[ReviewCase, ...]
    status_counts: tuple[tuple[str, int], ...]
    blocking_case_count: int


def build_review_queue(
    questions: tuple[QuestionRecord, ...],
    findings: tuple[Finding, ...],
    proposals: tuple[Proposal, ...] = (),
    decisions: tuple[ReviewDecision, ...] = (),
    verifications: tuple[SourceVerification, ...] = (),
) -> ReviewQueue:
    """Project immutable engine records into a deterministic UI review queue."""
    question_map = _unique_by(questions, "question_id")
    proposal_by_finding = _unique_by(proposals, "finding_id")
    decision_by_proposal = _unique_by(decisions, "proposal_id")
    verification_by_proposal = _unique_by(verifications, "proposal_id")
    finding_ids = {finding.finding_id for finding in findings}
    proposal_ids = {proposal.proposal_id for proposal in proposals}

    if any(proposal.finding_id not in finding_ids for proposal in proposals):
        raise DomainError("Review proposal references an unknown finding")
    if any(decision.proposal_id not in proposal_ids for decision in decisions):
        raise DomainError("Review decision references an unknown proposal")
    if any(item.proposal_id not in proposal_ids for item in verifications):
        raise DomainError("Source verification references an unknown proposal")

    cases = []
    for finding in sorted(
        findings,
        key=lambda item: (item.question_id, item.field, item.finding_id),
    ):
        question = question_map.get(finding.question_id)
        if question is None:
            raise DomainError("Finding references an unknown question")
        proposal = proposal_by_finding.get(finding.finding_id)
        if proposal is not None and (
            proposal.question_id != finding.question_id or proposal.field != finding.field
        ):
            raise DomainError("Review proposal and finding targets must match")
        decision = decision_by_proposal.get(proposal.proposal_id) if proposal else None
        verification = (
            verification_by_proposal.get(proposal.proposal_id) if proposal else None
        )
        status, actions = _review_state(proposal, decision, verification)
        cases.append(
            ReviewCase(
                finding=finding,
                question=question,
                proposal=proposal,
                decision=decision,
                verification=verification,
                status=status,
                allowed_actions=actions,
            )
        )

    counts = Counter(case.status.value for case in cases)
    return ReviewQueue(
        cases=tuple(cases),
        status_counts=tuple(sorted(counts.items())),
        blocking_case_count=sum(
            case.finding.severity.value == "blocking"
            and case.status is not ReviewStatus.APPROVED
            for case in cases
        ),
    )


def _review_state(
    proposal: Proposal | None,
    decision: ReviewDecision | None,
    verification: SourceVerification | None,
) -> tuple[ReviewStatus, tuple[str, ...]]:
    if proposal is None:
        return ReviewStatus.NEEDS_PROPOSAL, ("leave_blocked", "create_proposal")
    if decision is None:
        return ReviewStatus.AWAITING_DECISION, (
            "approve",
            "reject",
            "defer",
            "edit_as_new_proposal",
        )
    if decision.action is ReviewAction.REJECT:
        return ReviewStatus.REJECTED, ("leave_blocked", "create_new_proposal")
    if decision.action is ReviewAction.DEFER:
        return ReviewStatus.DEFERRED, (
            "leave_blocked",
            "approve",
            "reject",
            "edit_as_new_proposal",
        )
    if proposal.requires_source_verification and (
        verification is None or not verification.verified
    ):
        return ReviewStatus.AWAITING_SOURCE_VERIFICATION, (
            "verify_against_source",
            "leave_blocked",
            "reject",
        )
    return ReviewStatus.APPROVED, ("build_candidate",)


def _unique_by(items, attribute: str) -> dict:
    result = {}
    for item in items:
        key = getattr(item, attribute)
        if key in result:
            raise DomainError(f"Review queue contains duplicate {attribute}: {key}")
        result[key] = item
    return result
