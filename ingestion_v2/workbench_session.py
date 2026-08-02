from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path

from ingestion_v2.demo import SYNTHETIC_DOCUMENT, synthetic_review_records
from ingestion_v2.domain import (
    DomainError,
    DispositionAction,
    FindingDisposition,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
)
from ingestion_v2.engine import build_candidate, promotion_readiness
from ingestion_v2.comparison import compare_candidate, comparison_view
from ingestion_v2.review import ReviewStatus, build_review_queue
from ingestion_v2.review_view import review_queue_view
from ingestion_v2.run_lifecycle import RunLifecycle


@dataclass(frozen=True)
class SessionEvent:
    event_id: str
    finding_id: str
    event_type: str


class SyntheticWorkbenchSession:
    """In-memory adapter between the workbench UI and the real v2 review engine."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root
        self._lifecycle = None
        if workspace_root is None:
            self.questions, self.findings, self.proposals = synthetic_review_records()
        else:
            self.questions, self.findings, self.proposals = (), (), ()
        self._decisions_by_proposal: dict[str, ReviewDecision] = {}
        self._verifications_by_proposal: dict[str, SourceVerification] = {}
        self._events: list[SessionEvent] = []
        self._dispositions_by_finding: dict[str, FindingDisposition] = {}
        self._candidate = None
        self._comparison = None

    def view(self) -> dict:
        queue = self._queue()
        payload = review_queue_view(queue)
        payload["capabilities"]["build_isolated_candidate"] = True
        payload["capabilities"]["compare_isolated_candidate"] = True
        payload["session"] = {
            "mode": "synthetic_in_memory",
            "persistent": False,
            "event_count": len(self._events),
            "events": [event.__dict__ for event in self._events],
        }
        payload["pipeline"] = {
            "input": "synthetic_document",
            "parser": "existing_source_parser_without_broad_missing_a_recovery",
            "parsed_records": len(self.questions),
            "automatic_repairs": 0,
            "document_text_in_payload": False,
        }
        payload["candidate"] = self._candidate_view()
        payload["comparison"] = (
            comparison_view(self._comparison)
            if self._comparison is not None
            else {"state": "not_run"}
        )
        payload["run"] = self._run_view()
        return payload

    def start_run(self) -> dict:
        if self._workspace_root is None:
            raise DomainError("This session has no private run workspace")
        if self._lifecycle is not None:
            raise DomainError("A synthetic run is already active")
        lifecycle = RunLifecycle.create(self._workspace_root)
        try:
            encoded = SYNTHETIC_DOCUMENT.encode("utf-8")
            lifecycle.stage_disposable_copy(encoded, source_type="synthetic_text")
            lifecycle.record_extraction(SYNTHETIC_DOCUMENT)
            lifecycle.record_cleaning(SYNTHETIC_DOCUMENT)
            self.questions, self.findings, self.proposals = synthetic_review_records()
            lifecycle.record_review_ready(
                parsed_records=len(self.questions),
                finding_count=len(self.findings),
            )
        except Exception:
            lifecycle.fail("synthetic_run_start_failure")
            raise
        self._lifecycle = lifecycle
        return self.view()

    def record_action(self, finding_id: str, action: str) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        if action not in case.allowed_actions:
            raise DomainError(f"Action is not allowed for current review state: {action}")
        if action not in {"approve", "reject", "defer"}:
            raise DomainError("This action is not implemented by the connected preview")
        if case.proposal is None:
            raise DomainError("A review decision requires a proposal")
        action_value = ReviewAction(action)
        event_number = len(self._events) + 1
        decision = ReviewDecision(
            decision_id=f"PFV2-DEC-SESSION-{event_number:06d}",
            proposal_id=case.proposal.proposal_id,
            action=action_value,
            reviewer_note="Recorded in synthetic in-memory workbench session.",
        )
        self._decisions_by_proposal[case.proposal.proposal_id] = decision
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type=f"decision:{action}",
            )
        )
        return self.view()

    def build_isolated_candidate(self) -> dict:
        self._ensure_active_run_if_configured()
        self._candidate = build_candidate(
            self.questions,
            self.findings,
            self.proposals,
            tuple(self._decisions_by_proposal.values()),
            tuple(self._verifications_by_proposal.values()),
            tuple(self._dispositions_by_finding.values()),
        )
        self._comparison = None
        if self._lifecycle is not None:
            self._lifecycle.record_candidate(
                question_count=len(self._candidate.questions),
                unresolved_findings=len(self._candidate.unresolved_finding_ids),
            )
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id="PFV2-CANDIDATE",
                event_type="candidate:built_in_memory",
            )
        )
        return self.view()

    def record_disposition(self, finding_id: str, action: str) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        action_map = {
            "leave_blocked": DispositionAction.RETAIN_BLOCKER,
            "exclude_record": DispositionAction.EXCLUDE_RECORD,
        }
        if action not in action_map or action not in case.allowed_actions:
            raise DomainError(f"Disposition is not allowed for current review state: {action}")
        event_number = len(self._events) + 1
        disposition = FindingDisposition(
            disposition_id=f"PFV2-DISP-SESSION-{event_number:06d}",
            finding_id=finding_id,
            question_id=case.finding.question_id,
            action=action_map[action],
            reviewer_note="Recorded in synthetic in-memory workbench session.",
        )
        self._dispositions_by_finding[finding_id] = disposition
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type=f"disposition:{action_map[action].value}",
            )
        )
        return self.view()

    def compare_isolated_candidate(self) -> dict:
        self._ensure_active_run_if_configured()
        if self._candidate is None:
            raise DomainError("Build an isolated candidate before comparison")
        self._comparison = compare_candidate(self._candidate, self.questions)
        if self._lifecycle is not None:
            self._lifecycle.record_comparison(
                field_changes=len(self._comparison.field_changes),
                id_accounting_complete=self._comparison.id_accounting_complete,
            )
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id="PFV2-COMPARISON",
                event_type="comparison:completed_in_memory",
            )
        )
        return self.view()

    def record_verification(self, finding_id: str) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        if case.status is not ReviewStatus.AWAITING_SOURCE_VERIFICATION:
            raise DomainError("Source verification is not allowed for current review state")
        if case.proposal is None:
            raise DomainError("Source verification requires a proposal")
        event_number = len(self._events) + 1
        verification = SourceVerification(
            verification_id=f"PFV2-VERIFY-SESSION-{event_number:06d}",
            proposal_id=case.proposal.proposal_id,
            verified=True,
            reviewer_note="Synthetic source verification recorded in memory.",
        )
        self._verifications_by_proposal[case.proposal.proposal_id] = verification
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type="source_verification:verified",
            )
        )
        return self.view()

    def complete_run(self) -> dict:
        self._ensure_active_run_if_configured()
        if self._comparison is None:
            raise DomainError("Complete comparison before finishing the run")
        self._lifecycle.complete_and_cleanup()
        return self.view()

    def _queue(self):
        return build_review_queue(
            self.questions,
            self.findings,
            self.proposals,
            tuple(self._decisions_by_proposal.values()),
            tuple(self._verifications_by_proposal.values()),
            tuple(self._dispositions_by_finding.values()),
        )

    def _case(self, finding_id: str):
        for case in self._queue().cases:
            if case.finding.finding_id == finding_id:
                return case
        raise DomainError("Unknown finding ID")

    def _candidate_view(self) -> dict:
        if self._candidate is None:
            return {
                "state": "not_built",
                "persistent": False,
                "promotion_ready": False,
            }
        readiness = promotion_readiness(
            self._candidate,
            self.findings,
            comparison_complete=bool(self._comparison and self._comparison.complete),
        )
        return {
            "state": "built_in_memory",
            "persistent": False,
            "question_count": len(self._candidate.questions),
            "applied_proposal_ids": list(self._candidate.applied_proposal_ids),
            "unresolved_finding_ids": list(self._candidate.unresolved_finding_ids),
            "excluded_question_ids": list(self._candidate.excluded_question_ids),
            "promotion_ready": readiness.ready,
            "blocking_reasons": list(readiness.blocking_reasons),
        }

    def _ensure_active_run_if_configured(self) -> None:
        if self._workspace_root is not None and self._lifecycle is None:
            raise DomainError("Start the synthetic run first")
        if self._lifecycle is not None and self._lifecycle.manifest()["stage"] == "completed":
            raise DomainError("The synthetic run is already completed")

    def _return_lifecycle_to_review(self) -> None:
        if self._lifecycle is None:
            return
        stage = self._lifecycle.manifest()["stage"]
        if stage in {"candidate_built", "compared"}:
            self._lifecycle.return_to_review()

    def _run_view(self) -> dict:
        if self._workspace_root is None:
            return {"state": "unmanaged_demo"}
        if self._lifecycle is None:
            return {"state": "not_started"}
        manifest = self._lifecycle.manifest()
        return {
            "state": manifest["stage"],
            "status": manifest["status"],
            "run_id": manifest["run_id"],
            "staged_copy_present": manifest["staged_copy_present"],
            "raw_text_present": manifest["raw_text_present"],
            "cleaned_text_present": manifest["cleaned_text_present"],
            "promotion_available": False,
        }
