from __future__ import annotations

from ingestion_v2.review import ReviewQueue
from ingestion_v2.domain import ReviewAction, replace_question_field


def _question_packet(question, *, changed_field: str | None = None, proposed_value=None) -> dict:
    """Expose the complete reviewable record without mutating engine evidence."""
    values = {
        "stem": question.stem,
        "choices": [list(choice) for choice in question.choices],
        "correct_answers": list(question.correct_answers),
        "rationale": question.rationale,
    }
    if changed_field is not None:
        values[changed_field] = proposed_value
    if isinstance(values["choices"], (list, tuple)):
        values["choices"] = [list(choice) for choice in values["choices"]]
    if isinstance(values["correct_answers"], tuple):
        values["correct_answers"] = list(values["correct_answers"])
    return {
        "question_id": question.question_id,
        "question_type": question.question_type,
        "stem": values["stem"],
        "choices": values["choices"],
        "correct_answers": values["correct_answers"],
        "rationale": values["rationale"],
        "changed_fields": [changed_field] if changed_field is not None else [],
    }


def review_queue_view(queue: ReviewQueue) -> dict:
    """Return the source-neutral, read-only payload consumed by the workbench UI."""
    groups = _question_groups(queue)
    return {
        "format": "prepflow_v2_review_queue",
        "version": "1.0",
        "summary": {
            "case_count": sum(item["unresolved"] for item in groups),
            "finding_count": len(queue.cases),
            "question_count": len(groups),
            "blocking_case_count": sum(
                item["unresolved"] and item["blocking"] for item in groups
            ),
            "status_counts": dict(queue.status_counts),
        },
        "cases": [
            {
                "finding_id": case.finding.finding_id,
                "question_id": case.question.question_id,
                "chapter": case.question.chapter,
                "chapter_title": case.question.chapter_title,
                "source_record_id": case.question.source_record_id,
                "question_type": case.question.question_type,
                "field": case.finding.field,
                "damage_type": case.finding.damage_type,
                "severity": case.finding.severity.value,
                "explanation": case.finding.explanation,
                "preserved_value": getattr(case.question, case.finding.field),
                "answer_choice_context": (
                    [list(choice) for choice in case.question.choices]
                    if case.finding.field == "correct_answers"
                    else None
                ),
                "preserved_question": _question_packet(case.question),
                "proposed_question": (
                    _question_packet(
                        case.question,
                        changed_field=case.proposal.field,
                        proposed_value=case.proposal.proposed_after,
                    )
                    if case.proposal
                    else None
                ),
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
                "related_question": (
                    {
                        "question_id": case.related_question.question_id,
                        "chapter": case.related_question.chapter,
                        "chapter_title": case.related_question.chapter_title,
                        "source_record_id": case.related_question.source_record_id,
                        "stem": case.related_question.stem,
                    }
                    if case.related_question
                    else None
                ),
                "disposition": (
                    {
                        "disposition_id": case.disposition.disposition_id,
                        "question_id": case.disposition.question_id,
                        "action": case.disposition.action.value,
                        "reviewer_note": case.disposition.reviewer_note,
                    }
                    if case.disposition
                    else None
                ),
            }
            for case in queue.cases
        ],
        "question_groups": groups,
        "capabilities": {
            "read_review_queue": True,
            "record_review_decision": True,
            "record_source_verification": True,
            "build_isolated_candidate": True,
            "compare_isolated_candidate": False,
            "promote_canonical": False,
        },
    }


def _question_groups(queue: ReviewQueue) -> list[dict]:
    """Present one human review item per source question, not per detector."""
    buckets: dict[str, list] = {}
    for case in queue.cases:
        buckets.setdefault(case.question.question_id, []).append(case)
    groups = []
    for question_id, cases in sorted(buckets.items()):
        first = cases[0]
        effective = first.question
        approved = sorted(
            (
                case.proposal
                for case in cases
                if case.proposal is not None
                and case.decision is not None
                and case.decision.action is ReviewAction.APPROVE
                and (not case.proposal.requires_source_verification or (case.verification and case.verification.verified))
            ),
            key=lambda item: item.proposal_id,
        )
        for proposal in approved:
            effective = replace_question_field(effective, proposal.field, proposal.proposed_after)
        effective_resolves_structure = _choice_structure_is_complete(effective)
        structural_repair_saved = any(
            proposal.field == "choices" and _choice_structure_is_complete(effective)
            for proposal in approved
        )
        complete_repair_saved = any(
            proposal.explanation == "Operator complete-question correction."
            for proposal in approved
        )
        accepted_as_is = bool(cases) and all(
            case.disposition is not None and case.disposition.action.value == "accept_as_is"
            for case in cases
        )
        unresolved_cases = [
            case for case in cases
            if case.status.value not in {"approved", "excluded_record"}
            and not (
                complete_repair_saved
                or (
                structural_repair_saved
                and case.finding.field in {"choices", "correct_answers"}
                )
            )
        ]
        status = unresolved_cases[0].status.value if unresolved_cases else "approved"
        groups.append(
            {
                "question_id": question_id,
                "chapter": first.question.chapter,
                "chapter_title": first.question.chapter_title,
                "source_record_id": first.question.source_record_id,
                "question_type": first.question.question_type,
                "status": status,
                "unresolved": bool(unresolved_cases),
                "blocking": any(case.finding.severity.value == "blocking" for case in cases),
                "finding_ids": [case.finding.finding_id for case in cases],
                "issues": [
                    {
                        "finding_id": case.finding.finding_id,
                        "field": case.finding.field,
                        "damage_type": case.finding.damage_type,
                        "explanation": case.finding.explanation,
                        "status": case.status.value,
                    }
                    for case in cases
                ],
                "original_question": _question_packet(first.question),
                "effective_question": _question_packet(effective),
                "proposal_ids": [item.proposal_id for item in approved],
                "has_fix": bool(approved),
                "accepted_as_is": accepted_as_is,
                "effective_resolution": structural_repair_saved or complete_repair_saved,
            }
        )
    return groups


def _choice_structure_is_complete(question) -> bool:
    """A saved complete-choice correction clears sibling structure detectors."""
    labels = tuple(label for label, _ in question.choices)
    if not labels:
        return False
    expected = tuple(chr(ord("A") + index) for index in range(len(labels)))
    return labels == expected and set(question.correct_answers).issubset(set(labels))
