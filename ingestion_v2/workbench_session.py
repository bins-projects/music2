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
    Proposal,
    replace_question_field,
)
from ingestion_v2.engine import build_candidate, promotion_readiness
from ingestion_v2.comparison import compare_candidate, comparison_view
from ingestion_v2.review import ReviewStatus, build_review_queue
from ingestion_v2.review_view import review_queue_view
from ingestion_v2.run_lifecycle import RunLifecycle
from ingestion_v2.cleaning import GuardedPageAwareCleaner
from ingestion_v2.extraction import extract_disposable_copy
from ingestion_v2.parser import ExistingParserAdapter
from ingestion_v2.identity import IdentityReport, match_existing_pack_identity
from ingestion_v2.identity_review import (
    IdentityReviewCase,
    authorize_reviewed_identity,
    build_identity_review_cases,
)
from ingestion_v2.pack_bridge import pack_questions_to_domain
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.qa_adapter import QaResult, detect_candidate_damage
from ingestion_v2.proposal_adapter import draft_benchmark_answer_proposals, draft_deterministic_proposals
from ingestion_v2.checkpoint import proposal_fingerprint, write_checkpoint
from ingestion_v2.recovery import recover_run


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
        self._cleaning_result = None
        self._extraction_result = None
        self._parse_batch = None
        self._identity_report: IdentityReport | None = None
        self._identity_cases: tuple[IdentityReviewCase, ...] = ()
        self._identity_actions: dict[str, dict[str, str]] = {}
        self._identity_mapping: dict[str, str] | None = None
        self._identity_target_pack: dict | None = None
        self._benchmark_questions = None
        self._qa_result: QaResult | None = None
        self._source_pages: tuple[str, ...] = ()
        self._viewed_source_findings: set[str] = set()
        self._last_cleanup = None

    @classmethod
    def resume_run(cls, run_directory: Path, target_pack: dict) -> "SyntheticWorkbenchSession":
        recovered = recover_run(Path(run_directory), target_pack)
        session = cls(workspace_root=Path(run_directory).parent)
        session._lifecycle = recovered.lifecycle
        session._parse_batch = recovered.parse_batch
        session._identity_report = recovered.identity_report
        session._identity_cases = recovered.identity_cases
        session._identity_actions = recovered.identity_actions
        session._identity_mapping = recovered.identity_mapping
        session._identity_target_pack = target_pack
        session.questions = recovered.questions
        session.findings = recovered.findings
        session.proposals = recovered.proposals
        session._benchmark_questions = recovered.benchmark
        session._qa_result = recovered.qa_result
        session._decisions_by_proposal = {
            item.proposal_id: item for item in recovered.decisions
        }
        session._verifications_by_proposal = {
            item.proposal_id: item for item in recovered.verifications
        }
        session._dispositions_by_finding = {
            item.finding_id: item for item in recovered.dispositions
        }
        session._candidate = recovered.candidate
        session._comparison = recovered.comparison
        raw_path = Path(run_directory) / "artifacts" / "raw.txt"
        if raw_path.is_file() and not raw_path.is_symlink():
            session._source_pages = tuple(raw_path.read_text(encoding="utf-8").split("\n\f\n"))
        session._events = [
            SessionEvent("PFV2-EVENT-RECOVERED-000001", "PFV2-CHECKPOINT", "checkpoint:recovered")
        ]
        return session

    def view(self) -> dict:
        queue = self._queue()
        payload = review_queue_view(queue)
        payload["capabilities"]["build_isolated_candidate"] = True
        payload["capabilities"]["compare_isolated_candidate"] = True
        payload["session"] = {
            "mode": "synthetic_in_memory",
            "persistent": self._lifecycle is not None,
            "private_checkpoint": self._lifecycle is not None,
            "event_count": len(self._events),
            "events": [event.__dict__ for event in self._events],
        }
        payload["pipeline"] = {
            "input": "synthetic_document",
            "parser": "existing_source_parser_without_broad_missing_a_recovery",
            "parsed_records": (
                len(self._parse_batch.records)
                if self._parse_batch is not None
                else len(self.questions)
            ),
            "automatic_repairs": 0,
            "document_text_in_payload": False,
            "extraction": (
                {
                    "adapter": self._extraction_result.adapter_name,
                    "page_count": self._extraction_result.page_count,
                    "extracted_characters": self._extraction_result.extracted_characters,
                }
                if self._extraction_result is not None
                else None
            ),
            "cleaning": (
                {
                    "cleaner": self._cleaning_result.cleaner_name,
                    "removed_repeated_lines": self._cleaning_result.removed_repeated_lines,
                    "stripped_repeated_suffixes": self._cleaning_result.stripped_repeated_suffixes,
                    "protected_repeated_structures": self._cleaning_result.protected_repeated_structures,
                    "meaning_repairs": self._cleaning_result.meaning_repairs,
                    "source_specific_rules": self._cleaning_result.source_specific_rules,
                }
                if self._cleaning_result is not None
                else None
            ),
            "identity_pending": bool(
                self._lifecycle
                and self._lifecycle.manifest()["stage"] == "identity_pending"
            ),
            "identity": self._identity_view(),
            "qa": (
                {
                    "detector_counts": dict(self._qa_result.detector_counts),
                    "finding_count": len(self._qa_result.findings),
                    "automatic_repairs": self._qa_result.automatic_repairs,
                    "proposals_created": self._qa_result.proposals_created,
                }
                if self._qa_result is not None
                else {"state": "not_run"}
            ),
            "proposal_generation": {
                "state": "complete" if self._qa_result is not None else "not_run",
                "proposal_count": len(self.proposals) if self._qa_result is not None else 0,
                "automatic_applications": 0,
            },
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
        self._reset_completed_run_for_new_intake()
        if self._lifecycle is not None:
            raise DomainError("A synthetic run is already active")
        lifecycle = RunLifecycle.create(self._workspace_root)
        try:
            encoded = SYNTHETIC_DOCUMENT.encode("utf-8")
            lifecycle.stage_disposable_copy(encoded, source_type="synthetic_text")
            extraction = extract_disposable_copy(lifecycle.run_directory, "synthetic_text")
            lifecycle.record_extraction(
                extraction.text,
                adapter_name=extraction.adapter_name,
                page_count=extraction.page_count,
            )
            self._extraction_result = extraction
            self._source_pages = extraction.pages
            cleaning = GuardedPageAwareCleaner().clean(extraction.text)
            lifecycle.record_cleaning(
                cleaning.text,
                cleaner_name=cleaning.cleaner_name,
                removed_repeated_lines=cleaning.removed_repeated_lines,
                stripped_repeated_suffixes=cleaning.stripped_repeated_suffixes,
                protected_repeated_structures=cleaning.protected_repeated_structures,
            )
            self._cleaning_result = cleaning
            self.questions, self.findings, self.proposals = synthetic_review_records(cleaning.text)
            lifecycle.record_review_ready(
                parsed_records=len(self.questions),
                finding_count=len(self.findings),
            )
        except Exception:
            lifecycle.fail("synthetic_run_start_failure")
            raise
        self._lifecycle = lifecycle
        return self.view()

    def match_existing_pack(self, target_pack: dict) -> dict:
        if self._lifecycle is None or self._parse_batch is None:
            raise DomainError("Start and parse a PDF before matching an existing Pack")
        if self._lifecycle.manifest()["stage"] != "identity_pending":
            raise DomainError("Existing-Pack identity can run only at the identity gate")
        report = match_existing_pack_identity(self._parse_batch, target_pack)
        cases = build_identity_review_cases(self._parse_batch, target_pack, report)
        self._lifecycle.record_identity_assessment(
            target_pack_id=report.target_pack_id,
            matched_records=len(report.matches),
            identity_findings=len(report.findings),
            target_only_records=len(report.target_only_question_ids),
            complete=report.complete,
        )
        self._identity_report = report
        self._identity_cases = cases
        self._identity_actions = {}
        self._identity_target_pack = target_pack
        self._identity_mapping = report.stable_id_by_record_id if report.complete else None
        self._save_checkpoint()
        return self.view()

    def record_identity_action(
        self,
        record_id: str,
        action: str,
        target_question_id: str | None = None,
    ) -> dict:
        if self._identity_report is None or self._lifecycle is None:
            raise DomainError("Run existing-Pack identity matching before review")
        if self._lifecycle.manifest()["stage"] != "identity_review":
            raise DomainError("Identity review is not active")
        case = next((item for item in self._identity_cases if item.record_id == record_id), None)
        if case is None:
            raise DomainError("Unknown identity review record")
        if action not in {"approve", "reject", "defer"}:
            raise DomainError("Unknown identity review action")
        if action == "approve":
            allowed = {item.target_question_id for item in case.suggestions}
            if target_question_id not in allowed:
                raise DomainError("Approval requires a displayed identity suggestion")
            already_used = {
                value["target_question_id"]
                for key, value in self._identity_actions.items()
                if key != record_id and value["action"] == "approve"
            } | {item.target_question_id for item in self._identity_report.matches}
            if target_question_id in already_used:
                raise DomainError("A stable question ID cannot be assigned twice")
            self._identity_actions[record_id] = {
                "action": action,
                "target_question_id": target_question_id,
            }
        else:
            self._identity_actions[record_id] = {"action": action, "target_question_id": ""}

        approvals = {
            key: value["target_question_id"]
            for key, value in self._identity_actions.items()
            if value["action"] == "approve"
        }
        if (
            len(approvals) == len(self._identity_cases)
            and len(self._identity_report.matches) + len(approvals) == self._identity_report.parsed_count
            and len(self._identity_report.matches) + len(approvals) == self._identity_report.target_count
        ):
            self._identity_mapping = authorize_reviewed_identity(
                self._identity_report, self._identity_cases, approvals
            )
            self._lifecycle.record_identity_resolution(approved_matches=len(approvals))
        self._save_checkpoint()
        return self.view()

    def materialize_identity_review(self) -> dict:
        if (
            self._lifecycle is None
            or self._parse_batch is None
            or self._identity_mapping is None
            or self._identity_target_pack is None
        ):
            raise DomainError("A complete authorized identity map is required")
        if self._lifecycle.manifest()["stage"] != "identity_matched":
            raise DomainError("Identity materialization is not available at this stage")
        questions, findings = materialize_matched_batch(
            self._parse_batch, self._identity_mapping
        )
        qa_result = detect_candidate_damage(questions)
        parser_answer_ids = {
            item.question_id for item in findings if item.damage_type == "correct_answer_without_choice"
        }
        qa_result = QaResult(
            findings=tuple(
                item for item in qa_result.findings
                if not (
                    item.question_id in parser_answer_ids
                    and item.damage_type == "choice_structure__correct_answer_without_choice"
                )
            ),
            detector_counts=qa_result.detector_counts,
        )
        benchmark = pack_questions_to_domain(self._identity_target_pack)
        if {item.question_id for item in questions} != {item.question_id for item in benchmark}:
            raise DomainError("Materialized stable IDs do not exactly match the benchmark Pack")
        self.questions = questions
        self.findings = findings + qa_result.findings
        self.proposals = (
            draft_deterministic_proposals(questions, self.findings)
            + draft_benchmark_answer_proposals(questions, benchmark, self.findings)
        )
        self._benchmark_questions = benchmark
        self._qa_result = qa_result
        self._lifecycle.record_identity_materialized(
            parsed_records=len(questions), finding_count=len(self.findings)
        )
        return self.view()

    def start_pdf_run(self, content: bytes) -> dict:
        if self._workspace_root is None:
            raise DomainError("This session has no private run workspace")
        self._reset_completed_run_for_new_intake()
        if self._lifecycle is not None:
            raise DomainError("A run is already active")
        if not content:
            raise DomainError("Selected PDF is empty")
        lifecycle = RunLifecycle.create(self._workspace_root)
        try:
            lifecycle.stage_disposable_copy(content, source_type="pdf")
            extraction = extract_disposable_copy(lifecycle.run_directory, "pdf")
            lifecycle.record_extraction(
                extraction.text,
                adapter_name=extraction.adapter_name,
                page_count=extraction.page_count,
            )
            self._extraction_result = extraction
            self._source_pages = extraction.pages
            cleaning = GuardedPageAwareCleaner().clean(extraction.text)
            lifecycle.record_cleaning(
                cleaning.text,
                cleaner_name=cleaning.cleaner_name,
                removed_repeated_lines=cleaning.removed_repeated_lines,
                stripped_repeated_suffixes=cleaning.stripped_repeated_suffixes,
                protected_repeated_structures=cleaning.protected_repeated_structures,
            )
            self._cleaning_result = cleaning
            self._parse_batch = ExistingParserAdapter().parse(cleaning.text)
            lifecycle.record_identity_pending(
                parsed_records=len(self._parse_batch.records),
                parser_findings=len(self._parse_batch.findings),
            )
        except Exception:
            lifecycle.fail("pdf_intake_failure")
            self._lifecycle = lifecycle
            raise
        self.questions, self.findings, self.proposals = (), (), ()
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
        self._save_checkpoint()
        return self.view()

    def draft_user_proposal(
        self,
        finding_id: str,
        proposed_after,
        explanation: str,
        *,
        requires_source_verification: bool,
    ) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        allowed = {"create_proposal", "create_new_proposal", "edit_as_new_proposal"}
        if not allowed.intersection(case.allowed_actions):
            raise DomainError("A new proposal is not allowed for the current review state")
        if not isinstance(explanation, str) or not explanation.strip():
            raise DomainError("A user-authored proposal requires an explanation")
        if not isinstance(requires_source_verification, bool):
            raise DomainError("Source-verification selection must be boolean")
        current = getattr(case.question, case.finding.field)
        # Normalize list-shaped JSON and validate it through the immutable domain
        # record before storing the proposal.
        validated = replace_question_field(case.question, case.finding.field, proposed_after)
        proposed_value = getattr(validated, case.finding.field)
        if proposed_value == current:
            raise DomainError("A proposal must change the preserved value")
        event_number = len(self._events) + 1
        proposal = Proposal(
            proposal_id=f"PFV2-PROP-USER-{event_number:06d}",
            finding_id=case.finding.finding_id,
            question_id=case.finding.question_id,
            field=case.finding.field,
            expected_before=current,
            proposed_after=proposed_value,
            explanation=explanation.strip(),
            requires_source_verification=requires_source_verification,
        )
        old_proposal_ids = {
            item.proposal_id for item in self.proposals if item.finding_id == finding_id
        }
        self.proposals = tuple(
            item for item in self.proposals if item.finding_id != finding_id
        ) + (proposal,)
        for proposal_id in old_proposal_ids:
            self._decisions_by_proposal.pop(proposal_id, None)
            self._verifications_by_proposal.pop(proposal_id, None)
        self._dispositions_by_finding.pop(finding_id, None)
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type="proposal:user_authored",
            )
        )
        self._save_checkpoint()
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
        self._save_checkpoint()
        return self.view()

    def record_disposition(
        self, finding_id: str, action: str, target_question_id: str | None = None
    ) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        action_map = {
            "leave_blocked": DispositionAction.RETAIN_BLOCKER,
            "exclude_record": DispositionAction.EXCLUDE_RECORD,
        }
        if action == "restore_record" and action in case.allowed_actions:
            self._dispositions_by_finding.pop(finding_id, None)
            self._candidate = None
            self._comparison = None
            self._return_lifecycle_to_review()
            self._save_checkpoint()
            return self.view()
        if action not in action_map or action not in case.allowed_actions:
            raise DomainError(f"Disposition is not allowed for current review state: {action}")
        allowed_targets = {case.finding.question_id}
        if case.finding.related_question_id:
            allowed_targets.add(case.finding.related_question_id)
        target = target_question_id or case.finding.question_id
        if target not in allowed_targets:
            raise DomainError("Disposition target is not part of this review finding")
        event_number = len(self._events) + 1
        disposition = FindingDisposition(
            disposition_id=f"PFV2-DISP-SESSION-{event_number:06d}",
            finding_id=finding_id,
            question_id=target,
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
        self._save_checkpoint()
        return self.view()

    def compare_isolated_candidate(self) -> dict:
        self._ensure_active_run_if_configured()
        if self._candidate is None:
            raise DomainError("Build an isolated candidate before comparison")
        benchmark = self._benchmark_questions or self.questions
        self._comparison = compare_candidate(self._candidate, benchmark)
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
        self._save_checkpoint()
        return self.view()

    def record_verification(self, finding_id: str) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        if case.status is not ReviewStatus.AWAITING_SOURCE_VERIFICATION:
            raise DomainError("Source verification is not allowed for current review state")
        if case.proposal is None:
            raise DomainError("Source verification requires a proposal")
        if (
            self._lifecycle is not None
            and self._lifecycle.manifest().get("source_type") == "pdf"
            and finding_id not in self._viewed_source_findings
        ):
            raise DomainError("Open the temporary source page before recording verification")
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
        self._save_checkpoint()
        return self.view()

    def view_source_page(self, finding_id: str) -> dict:
        if self._lifecycle is None or self._lifecycle.manifest().get("source_type") != "pdf":
            raise DomainError("A temporary source page is available only for an active PDF run")
        case = self._case(finding_id)
        if case.status is not ReviewStatus.AWAITING_SOURCE_VERIFICATION:
            raise DomainError("Source page viewing is available only for pending verification")
        if not self._source_pages:
            raise DomainError("Temporary source pages are no longer available")
        needle = _source_search_text(case.question.stem)
        matches = [
            index
            for index, page in enumerate(self._source_pages)
            if needle and needle in _source_search_text(page)
        ]
        if len(matches) != 1:
            raise DomainError("PrepFlow could not locate one unambiguous temporary source page")
        page_index = matches[0]
        self._viewed_source_findings.add(finding_id)
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type=f"source_page:viewed:{page_index + 1}",
            )
        )
        return {
            "format": "prepflow_v2_temporary_source_page",
            "version": "1.0",
            "run_id": self._lifecycle.manifest()["run_id"],
            "question_id": case.question.question_id,
            "page_number": page_index + 1,
            "page_count": len(self._source_pages),
            "text": self._source_pages[page_index],
            "temporary": True,
            "canonical_write_available": False,
        }

    def complete_run(self) -> dict:
        self._ensure_active_run_if_configured()
        if self._comparison is None:
            raise DomainError("Complete comparison before finishing the run")
        self._lifecycle.complete_and_cleanup()
        self._source_pages = ()
        self._viewed_source_findings.clear()
        return self.view()

    def cleanup_run(self) -> dict:
        if self._lifecycle is None:
            raise DomainError("No active run requires cleanup")
        manifest = self._lifecycle.manifest()
        if manifest["stage"] == "completed":
            raise DomainError("Completed run source artifacts are already cleaned")
        if manifest["stage"] != "failed":
            self._lifecycle.fail("user_requested_cleanup")
        cleaned = self._lifecycle.cleanup_failed_run()
        self._last_cleanup = {
            "run_id": cleaned["run_id"],
            "source_bearing_artifacts_removed": True,
        }
        self._lifecycle = None
        self._candidate = None
        self._comparison = None
        self._cleaning_result = None
        self._extraction_result = None
        self._parse_batch = None
        self._identity_report = None
        self._identity_cases = ()
        self._identity_actions = {}
        self._identity_mapping = None
        self._identity_target_pack = None
        self._benchmark_questions = None
        self._qa_result = None
        self._source_pages = ()
        self._viewed_source_findings.clear()
        self.questions, self.findings, self.proposals = (), (), ()
        self._decisions_by_proposal.clear()
        self._verifications_by_proposal.clear()
        self._dispositions_by_finding.clear()
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

    def _identity_view(self) -> dict:
        if self._identity_report is None:
            return {"state": "not_run"}
        view = self._identity_report.view()
        # The local browser needs counts and uncertain cases, not thousands of
        # successful automatic mappings. Keep the complete mapping inside the
        # engine so full-book payloads remain responsive and source-private.
        view.pop("matches", None)
        resolved = self._lifecycle is not None and self._lifecycle.manifest()["stage"] == "identity_matched"
        view["state"] = "complete" if resolved else view["state"]
        view["review_cases"] = [
            {
                "record_id": case.record_id,
                "chapter": case.chapter,
                "chapter_title": case.chapter_title,
                "finding_code": case.finding_code,
                "parsed_stem": case.parsed_stem,
                "status": self._identity_actions.get(case.record_id, {}).get("action", "pending"),
                "selected_target_question_id": self._identity_actions.get(case.record_id, {}).get("target_question_id") or None,
                "suggestions": [item.__dict__ for item in case.suggestions],
            }
            for case in self._identity_cases
        ]
        view["review_approved_count"] = sum(
            item.get("action") == "approve" for item in self._identity_actions.values()
        )
        view["automatic_id_assignments_authorized"] = self._identity_report.complete
        view["reviewed_id_assignments_authorized"] = bool(resolved and self._identity_cases)
        return view

    def _save_checkpoint(self) -> None:
        if self._lifecycle is None or self._identity_report is None:
            return
        comparison_counts = {}
        if self._comparison is not None:
            comparison_counts = {
                "field_changes": len(self._comparison.field_changes),
                "excluded_questions": len(self._comparison.documented_excluded_question_ids),
                "candidate_questions": self._comparison.candidate_question_count,
            }
        write_checkpoint(
            self._lifecycle.run_directory,
            {
                "format": "prepflow_v2_checkpoint",
                "version": "1.0",
                "run_id": self._lifecycle.manifest()["run_id"],
                "target_pack_id": self._identity_report.target_pack_id,
                "identity_actions": [
                    {
                        "record_id": record_id,
                        "target_question_id": value["target_question_id"],
                    }
                    for record_id, value in sorted(self._identity_actions.items())
                    if value["action"] == "approve"
                ],
                "review_decisions": [
                    {
                        "decision_id": item.decision_id,
                        "proposal_id": item.proposal_id,
                        "action": item.action.value,
                    }
                    for item in sorted(self._decisions_by_proposal.values(), key=lambda value: value.decision_id)
                ],
                "verifications": [
                    {
                        "verification_id": item.verification_id,
                        "proposal_id": item.proposal_id,
                        "verified": item.verified,
                    }
                    for item in sorted(self._verifications_by_proposal.values(), key=lambda value: value.verification_id)
                ],
                "proposal_fingerprints": [
                    {
                        "proposal_id": item.proposal_id,
                        "fingerprint": proposal_fingerprint(
                            finding_id=item.finding_id,
                            question_id=item.question_id,
                            field=item.field,
                            expected_before=item.expected_before,
                            proposed_after=item.proposed_after,
                            requires_source_verification=item.requires_source_verification,
                        ),
                    }
                    for item in sorted(self.proposals, key=lambda value: value.proposal_id)
                ],
                "dispositions": [
                    {
                        "disposition_id": item.disposition_id,
                        "finding_id": item.finding_id,
                        "question_id": item.question_id,
                        "action": item.action.value,
                    }
                    for item in sorted(self._dispositions_by_finding.values(), key=lambda value: value.disposition_id)
                ],
                "comparison_counts": comparison_counts,
            },
        )

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
            return {"state": "not_started", "last_cleanup": self._last_cleanup}
        manifest = self._lifecycle.manifest()
        return {
            "state": manifest["stage"],
            "status": manifest["status"],
            "run_id": manifest["run_id"],
            "staged_copy_present": manifest["staged_copy_present"],
            "raw_text_present": manifest["raw_text_present"],
            "cleaned_text_present": manifest["cleaned_text_present"],
            "promotion_available": False,
            "parsed_records": manifest.get("parsed_records"),
            "parser_findings": manifest.get("parser_finding_count", manifest.get("finding_count")),
            "failure_code": manifest.get("failure_code"),
        }

    def _reset_completed_run_for_new_intake(self) -> None:
        if self._lifecycle is None or self._lifecycle.manifest()["stage"] != "completed":
            return
        self._lifecycle = None
        self._candidate = None
        self._comparison = None
        self._cleaning_result = None
        self._extraction_result = None
        self._parse_batch = None
        self._identity_report = None
        self._identity_cases = ()
        self._identity_actions = {}
        self._identity_mapping = None
        self._identity_target_pack = None
        self._benchmark_questions = None
        self._qa_result = None
        self._source_pages = ()
        self._viewed_source_findings.clear()
        self.questions, self.findings, self.proposals = (), (), ()
        self._decisions_by_proposal.clear()
        self._verifications_by_proposal.clear()
        self._dispositions_by_finding.clear()


def _source_search_text(value: str) -> str:
    return " ".join(value.split()).casefold()
