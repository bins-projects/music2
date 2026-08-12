from __future__ import annotations

from ingestion_v2.domain import (
    Candidate,
    DomainError,
    Finding,
    FindingDisposition,
    DispositionAction,
    FindingSeverity,
    PromotionReadiness,
    Proposal,
    QuestionRecord,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
    replace_question_field,
)


def build_candidate(
    questions: tuple[QuestionRecord, ...],
    findings: tuple[Finding, ...],
    proposals: tuple[Proposal, ...] = (),
    decisions: tuple[ReviewDecision, ...] = (),
    verifications: tuple[SourceVerification, ...] = (),
    dispositions: tuple[FindingDisposition, ...] = (),
) -> Candidate:
    """Apply only explicitly approved, current, sufficiently verified proposals."""
    question_map = _unique_by(questions, "question_id")
    finding_map = _unique_by(findings, "finding_id")
    proposal_map = _unique_by(proposals, "proposal_id")
    decision_map = _unique_by(decisions, "proposal_id")
    verification_map = _unique_by(verifications, "proposal_id")
    disposition_map = _unique_by(dispositions, "finding_id")

    for disposition in dispositions:
        finding = finding_map.get(disposition.finding_id)
        if finding is None:
            raise DomainError("Disposition must reference an existing finding")
        if disposition.question_id not in {finding.question_id, finding.related_question_id}:
            raise DomainError("Disposition and finding question IDs must match")

    for proposal in proposals:
        finding = finding_map.get(proposal.finding_id)
        if finding is None:
            raise DomainError("Proposal must reference an existing finding")
        if (finding.question_id, finding.field) != (proposal.question_id, proposal.field):
            raise DomainError("Proposal and finding targets must match")

    applied = []
    resolved_findings = set()
    complete_repair_question_ids = set()
    structural_repair_question_ids = set()
    audit_events = []
    for proposal_id in sorted(proposal_map):
        proposal = proposal_map[proposal_id]
        decision = decision_map.get(proposal_id)
        if decision is None or decision.action is not ReviewAction.APPROVE:
            continue
        verification = verification_map.get(proposal_id)
        if proposal.requires_source_verification and (
            verification is None or not verification.verified
        ):
            audit_events.append(f"{proposal_id}:approval_blocked_pending_source_verification")
            continue
        question = question_map.get(proposal.question_id)
        if question is None:
            raise DomainError("Proposal references an unknown question")
        current = getattr(question, proposal.field)
        if current != proposal.expected_before:
            raise DomainError("Proposal is stale; preserved candidate value has changed")
        question_map[proposal.question_id] = replace_question_field(
            question, proposal.field, proposal.proposed_after
        )
        applied.append(proposal_id)
        resolved_findings.add(proposal.finding_id)
        if proposal.explanation == "Operator complete-question correction.":
            complete_repair_question_ids.add(proposal.question_id)
        if proposal.field == "choices" and _choice_structure_is_complete(question_map[proposal.question_id]):
            structural_repair_question_ids.add(proposal.question_id)
        audit_events.append(f"{proposal_id}:applied_after_explicit_approval")

    excluded_question_ids = tuple(sorted({
        disposition.question_id
        for disposition in dispositions
        if disposition.action is DispositionAction.EXCLUDE_RECORD
    }))
    excluded_set = set(excluded_question_ids)
    resolved_findings.update(
        disposition.finding_id
        for disposition in dispositions
        if disposition.action in {
            DispositionAction.EXCLUDE_RECORD,
            DispositionAction.ACCEPT_AS_IS,
        }
    )
    resolved_findings.update(
        finding.finding_id for finding in findings
        if finding.question_id in structural_repair_question_ids
        and finding.field in {"choices", "correct_answers"}
    )
    for question_id in excluded_question_ids:
        audit_events.append(f"{question_id}:excluded_by_documented_disposition")

    # A complete editor save is one explicit operator decision for the whole
    # source question.  Its fields are still applied independently above for
    # auditability, but sibling detector findings must not demand duplicate
    # repairs of the same corrected question.
    resolved_findings.update(
        finding.finding_id for finding in findings
        if finding.question_id in complete_repair_question_ids
    )

    unresolved = tuple(
        finding.finding_id
        for finding in sorted(findings, key=lambda item: item.finding_id)
        if finding.finding_id not in resolved_findings
        and finding.question_id not in excluded_set
    )
    return Candidate(
        questions=tuple(
            question_map[question.question_id]
            for question in questions
            if question.question_id not in excluded_set
        ),
        applied_proposal_ids=tuple(applied),
        unresolved_finding_ids=unresolved,
        audit_events=tuple(audit_events),
        excluded_question_ids=excluded_question_ids,
    )


def promotion_readiness(
    candidate: Candidate,
    findings: tuple[Finding, ...],
    *,
    comparison_complete: bool,
    unresolved_hold_ids: tuple[str, ...] = (),
) -> PromotionReadiness:
    """Report readiness only; this function has no promotion capability."""
    finding_map = _unique_by(findings, "finding_id")
    reasons = []
    for finding_id in candidate.unresolved_finding_ids:
        finding = finding_map.get(finding_id)
        if finding is None:
            raise DomainError("Candidate references an unknown finding")
        if finding.severity is FindingSeverity.BLOCKING:
            reasons.append(f"unresolved_finding:{finding_id}")
    if not comparison_complete:
        reasons.append("candidate_comparison_incomplete")
    reasons.extend(f"unresolved_hold:{hold_id}" for hold_id in sorted(unresolved_hold_ids))
    return PromotionReadiness(ready=not reasons, blocking_reasons=tuple(reasons))


def _unique_by(items, attribute: str) -> dict:
    result = {}
    for item in items:
        key = getattr(item, attribute)
        if key in result:
            raise DomainError(f"Duplicate {attribute}: {key}")
        result[key] = item
    return result


def _choice_structure_is_complete(question: QuestionRecord) -> bool:
    labels = tuple(label for label, _ in question.choices)
    expected = tuple(chr(ord("A") + index) for index in range(len(labels)))
    return bool(labels) and labels == expected and set(question.correct_answers).issubset(set(labels))
