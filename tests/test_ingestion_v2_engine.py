import pytest

from ingestion_v2.domain import (
    DomainError,
    Finding,
    FindingSeverity,
    FindingDisposition,
    DispositionAction,
    Proposal,
    QuestionRecord,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
)
from ingestion_v2.engine import build_candidate, promotion_readiness


def question(stem: str = "Preserved damaged stem") -> QuestionRecord:
    return QuestionRecord(
        question_id="PFQ-synthetic-000000001",
        chapter=1,
        question_type="mc",
        stem=stem,
        choices=(("A", "First"), ("B", "Second")),
        correct_answers=("A",),
        rationale="Synthetic rationale",
    )


def finding(severity: FindingSeverity = FindingSeverity.BLOCKING) -> Finding:
    return Finding(
        finding_id="PFV2-FIND-0001",
        question_id="PFQ-synthetic-000000001",
        field="stem",
        damage_type="synthetic_interleaving",
        severity=severity,
        explanation="The stem contains a synthetic damaged fragment.",
    )


def proposal(*, verify: bool = False) -> Proposal:
    return Proposal(
        proposal_id="PFV2-PROP-0001",
        finding_id="PFV2-FIND-0001",
        question_id="PFQ-synthetic-000000001",
        field="stem",
        expected_before="Preserved damaged stem",
        proposed_after="Reviewed synthetic stem",
        explanation="Remove only the synthetic damaged fragment.",
        requires_source_verification=verify,
    )


def decision(action: ReviewAction) -> ReviewDecision:
    return ReviewDecision(
        decision_id="PFV2-DEC-0001",
        proposal_id="PFV2-PROP-0001",
        action=action,
    )


@pytest.mark.parametrize("action", [None, ReviewAction.REJECT, ReviewAction.DEFER])
def test_unapproved_proposal_preserves_damaged_record(action) -> None:
    decisions = () if action is None else (decision(action),)

    candidate = build_candidate((question(),), (finding(),), (proposal(),), decisions)

    assert candidate.questions[0].stem == "Preserved damaged stem"
    assert candidate.applied_proposal_ids == ()
    assert candidate.unresolved_finding_ids == ("PFV2-FIND-0001",)


def test_explicit_approval_applies_current_proposal_to_candidate_only() -> None:
    original = question()

    candidate = build_candidate(
        (original,), (finding(),), (proposal(),), (decision(ReviewAction.APPROVE),)
    )

    assert original.stem == "Preserved damaged stem"
    assert candidate.questions[0].stem == "Reviewed synthetic stem"
    assert candidate.applied_proposal_ids == ("PFV2-PROP-0001",)
    assert candidate.unresolved_finding_ids == ()


def test_approved_complete_question_correction_resolves_all_grouped_findings() -> None:
    original = question()
    sibling = Finding(
        "PFV2-FIND-0002", original.question_id, "rationale", "synthetic_sibling",
        FindingSeverity.BLOCKING, "Sibling detector finding.",
    )
    complete = Proposal(
        "PFV2-PROP-0002", "PFV2-FIND-0001", original.question_id, "stem",
        original.stem, "Reviewed synthetic stem", "Operator complete-question correction.",
    )
    approved = ReviewDecision("PFV2-DEC-0002", complete.proposal_id, ReviewAction.APPROVE)

    candidate = build_candidate((original,), (finding(), sibling), (complete,), (approved,))
    assert candidate.unresolved_finding_ids == ()


def test_stale_expected_value_blocks_application() -> None:
    with pytest.raises(DomainError, match="stale"):
        build_candidate(
            (question("Different current stem"),),
            (finding(),),
            (proposal(),),
            (decision(ReviewAction.APPROVE),),
        )


def test_source_verification_is_separate_from_approval() -> None:
    held = build_candidate(
        (question(),),
        (finding(),),
        (proposal(verify=True),),
        (decision(ReviewAction.APPROVE),),
    )
    verified = build_candidate(
        (question(),),
        (finding(),),
        (proposal(verify=True),),
        (decision(ReviewAction.APPROVE),),
        (
            SourceVerification(
                verification_id="PFV2-VERIFY-0001",
                proposal_id="PFV2-PROP-0001",
                verified=True,
                reviewer_note="Checked against the temporary source view.",
            ),
        ),
    )

    assert held.questions[0].stem == "Preserved damaged stem"
    assert held.unresolved_finding_ids == ("PFV2-FIND-0001",)
    assert verified.questions[0].stem == "Reviewed synthetic stem"


def test_promotion_readiness_reports_blockers_holds_and_comparison() -> None:
    candidate = build_candidate((question(),), (finding(),))

    report = promotion_readiness(
        candidate,
        (finding(),),
        comparison_complete=False,
        unresolved_hold_ids=("PFV2-HOLD-0108",),
    )

    assert report.ready is False
    assert report.blocking_reasons == (
        "unresolved_finding:PFV2-FIND-0001",
        "candidate_comparison_incomplete",
        "unresolved_hold:PFV2-HOLD-0108",
    )


def test_advisory_only_compared_candidate_can_be_ready_but_is_not_promoted() -> None:
    advisory = finding(FindingSeverity.ADVISORY)
    candidate = build_candidate((question(),), (advisory,))

    report = promotion_readiness(candidate, (advisory,), comparison_complete=True)

    assert report.ready is True
    assert report.blocking_reasons == ()
    assert not hasattr(report, "promote")


def test_source_neutral_ids_and_fields_are_enforced() -> None:
    with pytest.raises(DomainError, match="stable PrepFlow ID"):
        QuestionRecord(
            question_id="page-12-question-1",
            chapter=1,
            question_type="mc",
            stem="Synthetic stem",
        )


def test_incomplete_damaged_record_can_be_preserved_for_blocking_review() -> None:
    damaged = QuestionRecord(
        question_id="PFQ-synthetic-000000002",
        chapter=None,
        question_type="",
        stem="",
    )

    assert damaged.stem == ""
    assert damaged.question_type == ""


def test_documented_record_exclusion_is_atomic_and_auditable() -> None:
    original = question()
    disposition = FindingDisposition(
        disposition_id="PFV2-DISP-0001",
        finding_id="PFV2-FIND-0001",
        question_id=original.question_id,
        action=DispositionAction.EXCLUDE_RECORD,
        reviewer_note="Synthetic record is unusable and explicitly excluded.",
    )

    candidate = build_candidate(
        (original,),
        (finding(),),
        dispositions=(disposition,),
    )

    assert candidate.questions == ()
    assert candidate.excluded_question_ids == (original.question_id,)
    assert candidate.unresolved_finding_ids == ()
    assert candidate.audit_events == (
        f"{original.question_id}:excluded_by_documented_disposition",
    )
    with pytest.raises(DomainError, match="source-neutral"):
        Finding(
            finding_id="PFV2-FIND-0001",
            question_id="PFQ-synthetic-000000001",
            field="source_page",
            damage_type="synthetic",
            severity=FindingSeverity.BLOCKING,
            explanation="Synthetic explanation",
        )
