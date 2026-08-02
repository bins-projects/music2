from __future__ import annotations

from ingestion_v2.review import ReviewQueue


def review_queue_view(queue: ReviewQueue) -> dict:
    """Return the source-neutral, read-only payload consumed by the workbench UI."""
    return {
        "format": "prepflow_v2_review_queue",
        "version": "1.0",
        "summary": {
            "case_count": len(queue.cases),
            "blocking_case_count": queue.blocking_case_count,
            "status_counts": dict(queue.status_counts),
        },
        "cases": [
            {
                "finding_id": case.finding.finding_id,
                "question_id": case.question.question_id,
                "chapter": case.question.chapter,
                "question_type": case.question.question_type,
                "field": case.finding.field,
                "damage_type": case.finding.damage_type,
                "severity": case.finding.severity.value,
                "explanation": case.finding.explanation,
                "preserved_value": getattr(case.question, case.finding.field),
                "proposal": (
                    {
                        "proposal_id": case.proposal.proposal_id,
                        "proposed_value": case.proposal.proposed_after,
                        "explanation": case.proposal.explanation,
                        "requires_source_verification": (
                            case.proposal.requires_source_verification
                        ),
                    }
                    if case.proposal
                    else None
                ),
                "status": case.status.value,
                "allowed_actions": list(case.allowed_actions),
                "source_verification_recorded": bool(
                    case.verification and case.verification.verified
                ),
            }
            for case in queue.cases
        ],
        "capabilities": {
            "read_review_queue": True,
            "record_review_decision": True,
            "record_source_verification": True,
            "build_isolated_candidate": True,
            "compare_isolated_candidate": False,
            "promote_canonical": False,
        },
    }
