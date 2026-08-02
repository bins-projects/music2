import pytest

from ingestion_v2.domain import (
    DomainError,
    Finding,
    FindingSeverity,
    Proposal,
    QuestionRecord,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
)
from ingestion_v2.review import ReviewStatus, build_review_queue


def question(number: int = 1) -> QuestionRecord:
    return QuestionRecord(
        question_id=f"PFQ-synthetic-{number:09d}",
        chapter=1,
        question_type="mc",
        stem=f"Synthetic stem {number}",
        choices=(("A", "First"), ("B", "Second")),
        correct_answers=("A",),
    )


def finding(number: int = 1, field: str = "stem") -> Finding:
    return Finding(
        finding_id=f"PFV2-FIND-{number:04d}",
        question_id=f"PFQ-synthetic-{number:09d}",
        field=field,
        damage_type="synthetic_damage",
        severity=FindingSeverity.BLOCKING,
        explanation="Synthetic finding explanation.",
    )


def proposal(number: int = 1, *, verify: bool = False) -> Proposal:
    return Proposal(
        proposal_id=f"PFV2-PROP-{number:04d}",
        finding_id=f"PFV2-FIND-{number:04d}",
        question_id=f"PFQ-synthetic-{number:09d}",
        field="stem",
        expected_before=f"Synthetic stem {number}",
        proposed_after=f"Reviewed stem {number}",
        explanation="Synthetic proposal explanation.",
        requires_source_verification=verify,
    )


def decision(number: int, action: ReviewAction) -> ReviewDecision:
    return ReviewDecision(
        decision_id=f"PFV2-DEC-{number:04d}",
        proposal_id=f"PFV2-PROP-{number:04d}",
        action=action,
    )


def test_queue_exposes_finding_without_inventing_a_proposal() -> None:
    queue = build_review_queue((question(),), (finding(),))

    case = queue.cases[0]
    assert case.question.stem == "Synthetic stem 1"
    assert case.proposal is None
    assert case.status is ReviewStatus.NEEDS_PROPOSAL
    assert case.allowed_actions == ("leave_blocked", "create_proposal")
    assert queue.blocking_case_count == 1


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (None, ReviewStatus.AWAITING_DECISION),
        (ReviewAction.REJECT, ReviewStatus.REJECTED),
        (ReviewAction.DEFER, ReviewStatus.DEFERRED),
        (ReviewAction.APPROVE, ReviewStatus.APPROVED),
    ],
)
def test_queue_projects_review_decision_status(action, status) -> None:
    decisions = () if action is None else (decision(1, action),)

    queue = build_review_queue(
        (question(),), (finding(),), (proposal(),), decisions
    )

    assert queue.cases[0].status is status


def test_approval_that_requires_verification_remains_blocked() -> None:
    queue = build_review_queue(
        (question(),),
        (finding(),),
        (proposal(verify=True),),
        (decision(1, ReviewAction.APPROVE),),
    )

    assert queue.cases[0].status is ReviewStatus.AWAITING_SOURCE_VERIFICATION
    assert "verify_against_source" in queue.cases[0].allowed_actions
    assert queue.blocking_case_count == 1


def test_recorded_verification_completes_review_without_promoting() -> None:
    queue = build_review_queue(
        (question(),),
        (finding(),),
        (proposal(verify=True),),
        (decision(1, ReviewAction.APPROVE),),
        (
            SourceVerification(
                verification_id="PFV2-VERIFY-0001",
                proposal_id="PFV2-PROP-0001",
                verified=True,
                reviewer_note="Verified in temporary source view.",
            ),
        ),
    )

    assert queue.cases[0].status is ReviewStatus.APPROVED
    assert queue.cases[0].allowed_actions == ("build_candidate",)
    assert queue.blocking_case_count == 0
    assert not hasattr(queue, "promote")


def test_queue_order_and_summary_are_stable() -> None:
    queue = build_review_queue(
        (question(2), question(1)),
        (finding(2), finding(1)),
        (proposal(2),),
    )

    assert [case.question.question_id for case in queue.cases] == [
        "PFQ-synthetic-000000001",
        "PFQ-synthetic-000000002",
    ]
    assert queue.status_counts == (
        ("awaiting_decision", 1),
        ("needs_proposal", 1),
    )


def test_queue_rejects_orphaned_or_mismatched_records() -> None:
    with pytest.raises(DomainError, match="unknown finding"):
        build_review_queue((question(),), (), (proposal(),))

    mismatched = Proposal(
        proposal_id="PFV2-PROP-0001",
        finding_id="PFV2-FIND-0001",
        question_id="PFQ-synthetic-000000001",
        field="rationale",
        expected_before="",
        proposed_after="Reviewed rationale",
        explanation="Synthetic mismatch.",
    )
    with pytest.raises(DomainError, match="targets must match"):
        build_review_queue((question(),), (finding(),), (mismatched,))
