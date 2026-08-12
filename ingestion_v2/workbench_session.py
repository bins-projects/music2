from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json

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
    Finding,
    FindingSeverity,
    replace_question_field,
)
from ingestion_v2.engine import build_candidate, promotion_readiness
from ingestion_v2.comparison import compare_candidate, comparison_view
from ingestion_v2.comparison_categories import (
    apply_category_reference_values,
    categorize_comparison_changes,
    comparison_category_view,
)
from ingestion_v2.comparison_groups import (
    apply_exact_contaminant_group,
    contaminant_group_view,
    detect_exact_contaminant_groups,
)
from ingestion_v2.review import ReviewStatus, build_review_queue
from ingestion_v2.review_view import review_queue_view
from ingestion_v2.run_lifecycle import RunLifecycle
from ingestion_v2.cleaning import CleaningResult, GuardedPageAwareCleaner
from ingestion_v2.extraction import ExtractionResult, extract_disposable_copy
from ingestion_v2.parser import ExistingParserAdapter, ParseBatch
from ingestion_v2.identity import IdentityReport, match_existing_pack_identity
from ingestion_v2.identity_review import (
    IdentityReviewCase,
    authorize_reviewed_identity,
    build_identity_review_cases,
)
from ingestion_v2.pack_bridge import pack_questions_to_domain
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.private_proposals import read_private_user_proposals, write_private_user_proposals
from ingestion_v2.qa_adapter import QaResult, detect_candidate_damage
from ingestion_v2.proposal_adapter import draft_benchmark_answer_proposals, draft_deterministic_proposals
from ingestion_v2.checkpoint import proposal_fingerprint, read_checkpoint, write_checkpoint
from ingestion_v2.recovery import recover_run
from ingestion_v2.source_intake import validate_source_metadata


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
        self._identity_repair_findings: dict[str, Finding] = {}
        self._identity_mapping: dict[str, str] | None = None
        self._identity_target_pack: dict | None = None
        self._benchmark_questions = None
        self._qa_result: QaResult | None = None
        self._source_pages: tuple[str, ...] = ()
        self._viewed_source_findings: set[str] = set()
        self._approved_comparison_group_ids: set[str] = set()
        self._post_group_qa_result: QaResult | None = None
        self._comparison_category_decisions: dict[str, str] = {}
        self._viewed_comparison_categories: set[str] = set()
        self._last_cleanup = None
        self._source_only = False
        self._document_findings: list[dict] = []
        self._source_metadata: dict | None = None
        self._chapter_edits: dict[str, dict] = {}
        self._question_chapter_edits: dict[str, dict] = {}

    @classmethod
    def resume_run(cls, run_directory: Path, target_pack: dict) -> "SyntheticWorkbenchSession":
        recovered = recover_run(Path(run_directory), target_pack)
        session = cls(workspace_root=Path(run_directory).parent)
        session._lifecycle = recovered.lifecycle
        session._parse_batch = recovered.parse_batch
        session._identity_report = recovered.identity_report
        session._identity_cases = recovered.identity_cases
        session._identity_actions = recovered.identity_actions
        session.proposals = recovered.proposals
        if session._lifecycle.manifest().get("stage") in {"identity_review", "identity_matched"}:
            for proposal in read_private_user_proposals(session._lifecycle.run_directory):
                if proposal.proposal_id.startswith("PFV2-PROP-USER-IDENTITY-REPAIR-"):
                    record_id = f"PFV2-REC-{proposal.proposal_id.rsplit('-', 1)[1]}"
                    finding = Finding(f"PFV2-FIND-IDENTITY-REPAIR-{record_id.rsplit('-', 1)[1]}", proposal.question_id, proposal.field, "identity_matched_field_repair", FindingSeverity.BLOCKING, "Field repair staged after identity match; source verification and explicit approval are required.")
                    session._identity_repair_findings[record_id] = finding
        session._identity_mapping = recovered.identity_mapping
        session._identity_target_pack = target_pack
        session.questions = recovered.questions
        session.findings = recovered.findings
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
        session._approved_comparison_group_ids = set(recovered.comparison_group_ids)
        session._post_group_qa_result = recovered.post_group_qa_result
        session._comparison_category_decisions = dict(recovered.comparison_category_decisions)
        raw_path = Path(run_directory) / "artifacts" / "raw.txt"
        if raw_path.is_file() and not raw_path.is_symlink():
            session._source_pages = tuple(raw_path.read_text(encoding="utf-8").split("\n\f\n"))
        manifest = session._lifecycle.manifest()
        if manifest.get("raw_text_present"):
            session._extraction_result = ExtractionResult("", session._source_pages, manifest.get("extraction_adapter", "recovered_private_extraction"), manifest.get("extracted_pages", len(session._source_pages)), manifest.get("extracted_characters", 0))
        if manifest.get("cleaned_text_present"):
            session._cleaning_result = CleaningResult("", manifest.get("cleaner_name", "recovered_private_cleaning"), manifest.get("extracted_characters", 0), manifest.get("cleaned_characters", 0), manifest.get("removed_repeated_lines", 0), manifest.get("stripped_repeated_suffixes", 0), manifest.get("protected_repeated_structures", 0), manifest.get("cleaning_meaning_repairs", 0), manifest.get("cleaning_source_specific_rules", 0))
        session._events = [
            SessionEvent("PFV2-EVENT-RECOVERED-000001", "PFV2-CHECKPOINT", "checkpoint:recovered")
        ]
        return session

    @classmethod
    def resume_source_only_run(cls, run_directory: Path) -> "SyntheticWorkbenchSession":
        """Rebuild a source-only review from controlled cleaned text and manifest metadata."""
        lifecycle = RunLifecycle.open(run_directory)
        manifest = lifecycle.manifest()
        metadata = manifest.get("source_metadata")
        if not manifest.get("source_only") or not isinstance(metadata, dict):
            raise DomainError("Run is not a source-only review")
        if manifest.get("stage") not in {"review_ready", "candidate_built", "compared"}:
            raise DomainError("Source-only run is not ready to resume")
        cleaned = Path(run_directory) / "artifacts" / "cleaned.txt"
        if cleaned.is_symlink() or not cleaned.is_file():
            raise DomainError("Resume requires the controlled cleaned artifact")
        raw = Path(run_directory) / "artifacts" / "raw.txt"
        if raw.is_symlink() or not raw.is_file():
            raise DomainError("Resume requires the controlled temporary source pages")
        session = cls(workspace_root=Path(run_directory).parent)
        session._lifecycle = lifecycle
        session._source_pages = tuple(raw.read_text(encoding="utf-8").split("\n\f\n"))
        session._parse_batch = ExistingParserAdapter().parse(cleaned.read_text(encoding="utf-8"))
        session._source_only = True
        session._source_metadata = validate_source_metadata(metadata, reserved=set())
        mapping = {
            record.record_id: f"PFQ-{session._source_metadata['slug']}-{index:09d}"
            for index, record in enumerate(session._parse_batch.records, start=1)
        }
        session.questions, parser_findings = materialize_matched_batch(session._parse_batch, mapping)
        checkpoint = read_checkpoint(run_directory)
        session._restore_chapter_edits(checkpoint)
        session._qa_result = detect_candidate_damage(session.questions)
        session.findings = parser_findings + session._qa_result.findings
        session.proposals = draft_deterministic_proposals(session.questions, session.findings)
        saved = tuple(_restore_private_proposal_collections(item) for item in read_private_user_proposals(run_directory))
        saved_fingerprints = {
            item["proposal_id"]: item["fingerprint"]
            for item in checkpoint.get("proposal_fingerprints", [])
        }
        if any(
            saved_fingerprints.get(item.proposal_id) != proposal_fingerprint(
                finding_id=item.finding_id, question_id=item.question_id,
                field=item.field, expected_before=item.expected_before,
                proposed_after=item.proposed_after,
                requires_source_verification=item.requires_source_verification,
            )
            for item in saved
        ):
            raise DomainError("Private proposal does not match its content-free checkpoint fingerprint")
        known_question_ids = {item.question_id for item in session.questions}
        recovered_user_findings = []
        known_findings = {item.finding_id for item in session.findings}
        for proposal in saved:
            if (
                proposal.explanation == "Operator complete-question correction."
                and proposal.finding_id not in known_findings
                and proposal.question_id in known_question_ids
            ):
                recovered_user_findings.append(Finding(
                    proposal.finding_id, proposal.question_id, proposal.field,
                    "operator_complete_question_correction", FindingSeverity.BLOCKING,
                    "Operator changed this field through the complete-question editor.",
                ))
        if recovered_user_findings:
            session.findings = session.findings + tuple(recovered_user_findings)
        known_findings = {item.finding_id for item in session.findings}
        if any(item.finding_id not in known_findings for item in saved):
            raise DomainError("Private proposal cannot be matched to the recovered source-only run")
        session.proposals = tuple(
            item for item in session.proposals if item.finding_id not in {saved_item.finding_id for saved_item in saved}
        ) + saved
        proposal_ids = {item.proposal_id for item in session.proposals}
        session._decisions_by_proposal = {
            item["proposal_id"]: ReviewDecision(
                item["decision_id"], item["proposal_id"], ReviewAction(item["action"]),
                "Recovered from private checkpoint.",
            )
            for item in checkpoint.get("review_decisions", [])
            if item["proposal_id"] in proposal_ids
        }
        session._verifications_by_proposal = {
            item["proposal_id"]: SourceVerification(
                item["verification_id"], item["proposal_id"], item["verified"],
                "Recovered verified checkpoint event.",
            )
            for item in checkpoint.get("verifications", [])
            if item["proposal_id"] in proposal_ids
        }
        finding_ids = {item.finding_id for item in session.findings}
        session._dispositions_by_finding = {
            item["finding_id"]: FindingDisposition(
                item["disposition_id"], item["finding_id"], item["question_id"],
                DispositionAction(item["action"]), "Recovered from private checkpoint.",
            )
            for item in checkpoint.get("dispositions", [])
            if item["finding_id"] in finding_ids
        }
        session._events = [SessionEvent("PFV2-EVENT-RECOVERED-000001", "PFV2-CHECKPOINT", "checkpoint:recovered")]
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
            "document_findings": list(self._document_findings),
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
        if self._source_metadata is not None:
            payload["pipeline"]["source_metadata"] = self._source_metadata
        payload["candidate"] = self._candidate_view()
        payload["comparison"] = (
            self._comparison_view()
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
        if action not in {"approve", "retain_new_question", "exclude_parser_debris", "exclude_duplicate", "defer"}:
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
                owner = next((key for key, value in self._identity_actions.items() if key != record_id and value.get("target_question_id") == target_question_id), None)
                raise DomainError(f"Stable question ID is already assigned to {owner or 'an automatic match'}; inspect that parsed record before changing identity decisions")
            self._identity_actions[record_id] = {
                "action": action,
                "target_question_id": target_question_id,
            }
        elif action == "retain_new_question":
            self._identity_actions[record_id] = {
                "action": action,
                "target_question_id": self._allocate_new_question_id(record_id),
            }
        elif action in {"exclude_parser_debris", "exclude_duplicate", "defer"}:
            self._identity_actions[record_id] = {"action": action, "target_question_id": ""}

        approvals = {
            key: value["target_question_id"]
            for key, value in self._identity_actions.items()
            if value["action"] == "approve"
        }
        exclusions = {
            key for key, value in self._identity_actions.items()
            if value["action"] in {"exclude_parser_debris", "exclude_duplicate"}
        }
        new_questions = {
            key: value["target_question_id"]
            for key, value in self._identity_actions.items()
            if value["action"] == "retain_new_question"
        }
        completed = set(approvals) | exclusions | set(new_questions)
        if (
            len(completed) == len(self._identity_cases)
            and len(self._identity_report.matches) + len(approvals) + len(exclusions) + len(new_questions) == self._identity_report.parsed_count
        ):
            self._identity_mapping = authorize_reviewed_identity(
                self._identity_report, self._identity_cases, approvals, exclusions, new_questions
            )
            self._lifecycle.record_identity_resolution(
                approved_matches=len(approvals), excluded_records=len(exclusions),
                retained_new_questions=len(new_questions),
            )
        self._save_checkpoint()
        return self.view()

    def draft_identity_field_repair(self, record_id: str, field: str, proposed_after, explanation: str) -> dict:
        """Stage a field repair without changing an already-authorized identity decision."""
        if self._lifecycle is None or self._parse_batch is None or self._identity_report is None:
            raise DomainError("Identity matching must be active before staging a field repair")
        action = self._identity_actions.get(record_id, {})
        question_id = action.get("target_question_id") or self._identity_report.stable_id_by_record_id.get(record_id)
        record = next((item for item in self._parse_batch.records if item.record_id == record_id), None)
        if not question_id or record is None:
            raise DomainError("Field repair requires an already matched parsed record")
        question, _ = materialize_matched_batch(ParseBatch((record,), (), self._parse_batch.parser_name), {record_id: question_id})
        current = getattr(question[0], field)
        validated = replace_question_field(question[0], field, proposed_after)
        value = getattr(validated, field)
        if value == current or not isinstance(explanation, str) or not explanation.strip():
            raise DomainError("A field repair must change the parsed value and explain the source evidence")
        suffix = record_id.rsplit("-", 1)[1]
        finding = Finding(f"PFV2-FIND-IDENTITY-REPAIR-{suffix}", question_id, field, "identity_matched_field_repair", FindingSeverity.BLOCKING, "Field repair staged after identity match; source verification and explicit approval are required.")
        proposal = Proposal(f"PFV2-PROP-USER-IDENTITY-REPAIR-{suffix}", finding.finding_id, question_id, field, current, value, explanation.strip(), True)
        self._identity_repair_findings[record_id] = finding
        self.proposals = tuple(item for item in self.proposals if item.finding_id != finding.finding_id) + (proposal,)
        self._save_checkpoint()
        return self.view()

    def view_identity_source_context(self, record_id: str) -> dict:
        """Return a private three-page source window for one identity record."""
        if self._lifecycle is None or self._lifecycle.manifest().get("source_type") != "pdf":
            raise DomainError("Temporary source context is available only for an active PDF run")
        if self._lifecycle.manifest().get("stage") not in {"identity_review", "identity_matched"}:
            raise DomainError("Source context is available only during identity review")
        case = next((item for item in self._identity_cases if item.record_id == record_id), None)
        if case is None:
            raise DomainError("Unknown identity review record")
        if not self._source_pages:
            raise DomainError("Temporary source pages are no longer available")

        page_index = _locate_source_page(case.parsed_stem, self._source_pages)
        first = max(0, page_index - 1)
        last = min(len(self._source_pages), page_index + 2)
        return {
            "format": "prepflow_v2_temporary_source_context",
            "version": "1.0",
            "record_id": record_id,
            "focus_page_number": page_index + 1,
            "page_count": len(self._source_pages),
            "pages": [
                {
                    "page_number": index + 1,
                    "role": (
                        "current"
                        if index == page_index
                        else "previous"
                        if index < page_index
                        else "next"
                    ),
                    "text": self._source_pages[index],
                }
                for index in range(first, last)
            ],
            "temporary": True,
            "canonical_write_available": False,
        }

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
        retained_batch = ParseBatch(
            records=tuple(
                item for item in self._parse_batch.records
                if item.record_id in self._identity_mapping
            ),
            findings=tuple(
                item for item in self._parse_batch.findings
                if item.record_id in self._identity_mapping
            ),
            parser_name=self._parse_batch.parser_name,
            automatic_repairs=self._parse_batch.automatic_repairs,
        )
        questions, findings = materialize_matched_batch(
            retained_batch, self._identity_mapping
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
        staged = tuple(item for item in self.proposals if item.proposal_id.startswith("PFV2-PROP-USER-IDENTITY-REPAIR-"))
        self.questions = questions
        self.findings = findings + qa_result.findings + tuple(self._identity_repair_findings.values())
        self.proposals = (
            draft_deterministic_proposals(questions, self.findings)
            + draft_benchmark_answer_proposals(questions, benchmark, self.findings)
            + staged
        )
        self._benchmark_questions = benchmark
        self._qa_result = qa_result
        self._lifecycle.record_identity_materialized(
            parsed_records=len(questions), finding_count=len(self.findings)
        )
        return self.view()

    def start_pdf_run(self, content: bytes) -> dict:
        return self._start_pdf_run(content)

    def start_pdf_run_from_existing_extraction(
        self, content: bytes, text: str, *, adapter_name: str, page_count: int
    ) -> dict:
        return self._start_pdf_run(
            content, existing_text=text, adapter_name=adapter_name,
            page_count=page_count,
        )

    def _start_pdf_run(
        self, content: bytes, *, existing_text: str | None = None,
        adapter_name: str | None = None, page_count: int | None = None,
    ) -> dict:
        if self._workspace_root is None:
            raise DomainError("This session has no private run workspace")
        self._reset_completed_run_for_new_intake()
        if self._lifecycle is not None:
            raise DomainError("A run is already active")
        if not content:
            raise DomainError("Selected PDF is empty")
        self._source_only = False
        self._document_findings = []
        lifecycle = RunLifecycle.create(self._workspace_root)
        try:
            lifecycle.stage_disposable_copy(content, source_type="pdf")
            extraction = (
                ExtractionResult(
                    existing_text,
                    tuple(existing_text.split("\n\f\n")),
                    adapter_name or "validated_existing_extraction",
                    page_count or len(existing_text.split("\n\f\n")),
                    len(existing_text),
                )
                if existing_text is not None
                else extract_disposable_copy(lifecycle.run_directory, "pdf")
            )
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
            if not self._parse_batch.records:
                self._document_findings = [{"finding_id": "PFV2-DOCUMENT-000001", "severity": "blocking", "damage_type": "zero_parsed_records", "explanation": "No questions were parsed. This PDF may require another extraction strategy or OCR."}]
                lifecycle.fail("zero_parsed_records")
                self._lifecycle = lifecycle
                return self.view()
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

    def materialize_source_only(self, source_metadata: dict, *, registered_preset: bool = False) -> dict:
        if self._lifecycle is None or self._parse_batch is None or self._lifecycle.manifest()["stage"] != "identity_pending":
            raise DomainError("Parse a PDF before starting source-only review")
        reserved = {"fundamentals", "medical_surgical", "pharmacy", "pediatrics", "fund", "medsurg", "pharm", "peds"}
        if registered_preset:
            reserved -= {str(source_metadata.get("slug", "")).casefold(), "peds"}
        metadata = validate_source_metadata(source_metadata, reserved=reserved)
        mapping = {record.record_id: f"PFQ-{metadata['slug']}-{index:09d}" for index, record in enumerate(self._parse_batch.records, start=1)}
        self.questions, parser_findings = materialize_matched_batch(self._parse_batch, mapping)
        qa = detect_candidate_damage(self.questions)
        self.findings = parser_findings + qa.findings
        self.proposals = draft_deterministic_proposals(self.questions, self.findings)
        self._qa_result = qa
        self._source_only = True
        self._source_metadata = metadata
        self._lifecycle.record_source_only_review(parsed_records=len(self.questions), finding_count=len(self.findings), source_metadata=metadata)
        self._save_checkpoint()
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

    def accept_question_as_is(self, question_id: str) -> dict:
        """Persist an explicit human acceptance without changing source fields."""
        self._ensure_active_run_if_configured()
        question = next((item for item in self.questions if item.question_id == question_id), None)
        if question is None:
            raise DomainError("Question is unavailable in this private run")
        findings = [item for item in self.findings if item.question_id == question_id]
        if not findings:
            raise DomainError("Question has no review findings to accept")
        event_number = len(self._events) + 1
        for offset, finding in enumerate(findings, start=1):
            self._dispositions_by_finding[finding.finding_id] = FindingDisposition(
                disposition_id=f"PFV2-DISP-SESSION-{event_number:06d}-{offset:02d}",
                finding_id=finding.finding_id,
                question_id=question_id,
                action=DispositionAction.ACCEPT_AS_IS,
                reviewer_note="Operator accepted the complete pipeline question as is.",
            )
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(SessionEvent(
            f"PFV2-EVENT-{event_number:06d}", question_id, "decision:accept_question_as_is"
        ))
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

    def save_complete_question_repair(self, question_id: str, values: dict) -> dict:
        """Save one operator-facing complete-question repair as field proposals.

        The engine still stores field-level audit evidence, while the operator
        edits one complete question and never has to replay sibling detectors.
        """
        self._ensure_active_run_if_configured()
        question = next((item for item in self.questions if item.question_id == question_id), None)
        if question is None:
            raise DomainError("Question is unavailable in this private run")
        repaired = _validated_complete_question(question, values)
        existing = [item for item in self.proposals if item.question_id == question_id]
        replacement_fields = {
            field for field in ("stem", "choices", "correct_answers", "rationale")
            if getattr(repaired, field) != getattr(question, field)
        }
        if not replacement_fields:
            return self.view()
        finding_by_field = {}
        for finding in self.findings:
            if finding.question_id == question_id:
                finding_by_field.setdefault(finding.field, finding)
        extra_findings = []
        for field in sorted(replacement_fields - set(finding_by_field)):
            finding = Finding(
                f"PFV2-FIND-USER-{question.source_record_id.rsplit('-', 1)[-1] if question.source_record_id else question_id.rsplit('-', 1)[-1]}-{field.upper()}",
                question_id, field, "operator_complete_question_correction",
                FindingSeverity.BLOCKING,
                "Operator changed this field through the complete-question editor.",
            )
            finding_by_field[field] = finding
            extra_findings.append(finding)
        if extra_findings:
            self.findings = self.findings + tuple(extra_findings)
        kept = [item for item in self.proposals if item.question_id != question_id]
        removed_ids = {item.proposal_id for item in existing}
        for proposal_id in removed_ids:
            self._decisions_by_proposal.pop(proposal_id, None)
            self._verifications_by_proposal.pop(proposal_id, None)
        next_number = _next_user_proposal_number(self.proposals)
        for field in sorted(replacement_fields):
            finding = finding_by_field[field]
            proposal = Proposal(
                proposal_id=f"PFV2-PROP-USER-{next_number:06d}",
                finding_id=finding.finding_id,
                question_id=question_id,
                field=field,
                expected_before=getattr(question, field),
                proposed_after=getattr(repaired, field),
                explanation="Operator complete-question correction.",
                requires_source_verification=False,
            )
            kept.append(proposal)
            self._decisions_by_proposal[proposal.proposal_id] = ReviewDecision(
                decision_id=f"PFV2-DEC-SESSION-{len(self._events) + next_number:06d}",
                proposal_id=proposal.proposal_id,
                action=ReviewAction.APPROVE,
                reviewer_note="Approved through complete-question editor.",
            )
            next_number += 1
        self.proposals = tuple(kept)
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(SessionEvent(
            f"PFV2-EVENT-{len(self._events) + 1:06d}", question_id, "repair:complete_question_saved"
        ))
        self._save_checkpoint()
        return self.view()

    def undo_complete_question_repair(self, question_id: str) -> dict:
        self._ensure_active_run_if_configured()
        removed = {
            item.proposal_id for item in self.proposals
            if item.question_id == question_id and item.proposal_id.startswith("PFV2-PROP-USER-")
        }
        if not removed:
            raise DomainError("This question has no saved operator correction to undo")
        self.proposals = tuple(item for item in self.proposals if item.proposal_id not in removed)
        self.findings = tuple(
            item for item in self.findings
            if not (item.question_id == question_id and item.finding_id.startswith("PFV2-FIND-USER-"))
        )
        for proposal_id in removed:
            self._decisions_by_proposal.pop(proposal_id, None)
            self._verifications_by_proposal.pop(proposal_id, None)
        self._candidate = None
        self._comparison = None
        self._return_lifecycle_to_review()
        self._events.append(SessionEvent(
            f"PFV2-EVENT-{len(self._events) + 1:06d}", question_id, "repair:complete_question_undone"
        ))
        self._save_checkpoint()
        return self.view()

    def edit_chapter(self, chapter: int, title: str, new_chapter: int, new_title: str) -> dict:
        self._ensure_active_run_if_configured()
        if not isinstance(new_chapter, int) or new_chapter < 1:
            raise DomainError("Chapter number must be a positive integer")
        if not isinstance(new_title, str) or not new_title.strip():
            raise DomainError("Chapter title cannot be blank")
        affected = [item for item in self.questions if item.chapter == chapter and item.chapter_title == title]
        if not affected:
            raise DomainError("Chapter is unavailable in this private run")
        if any(item.chapter == new_chapter and item.chapter_title != title for item in self.questions if item not in affected):
            raise DomainError("Chapter number is already assigned to another chapter")
        key = f"{chapter}|{title}"
        self._chapter_edits.setdefault(key, {
            "original_chapter": chapter, "original_title": title,
        }).update({"chapter": new_chapter, "title": new_title.strip()})
        affected_ids = {item.question_id for item in affected}
        self.questions = tuple(
            replace(item, chapter=new_chapter, chapter_title=new_title.strip()) if item.question_id in affected_ids else item
            for item in self.questions
        )
        self._candidate = None
        self._comparison = None
        self._events.append(SessionEvent(f"PFV2-EVENT-{len(self._events)+1:06d}", key, "chapter:edited"))
        self._save_checkpoint()
        return self.view()

    def undo_chapter_edit(self, original_chapter: int, original_title: str) -> dict:
        self._ensure_active_run_if_configured()
        key = f"{original_chapter}|{original_title}"
        edit = self._chapter_edits.pop(key, None)
        if edit is None:
            raise DomainError("Chapter has no saved edit to undo")
        current_ids = {
            item.question_id for item in self.questions
            if item.chapter == edit["chapter"] and item.chapter_title == edit["title"]
        }
        self.questions = tuple(
            replace(item, chapter=original_chapter, chapter_title=original_title) if item.question_id in current_ids else item
            for item in self.questions
        )
        self._candidate = None
        self._comparison = None
        self._events.append(SessionEvent(f"PFV2-EVENT-{len(self._events)+1:06d}", key, "chapter:edit_undone"))
        self._save_checkpoint()
        return self.view()

    def reassign_question_chapter(self, question_id: str, chapter: int, title: str) -> dict:
        self._ensure_active_run_if_configured()
        target_exists = any(item.chapter == chapter and item.chapter_title == title for item in self.questions)
        question = next((item for item in self.questions if item.question_id == question_id), None)
        if question is None or not target_exists:
            raise DomainError("Question or target chapter is unavailable")
        self._question_chapter_edits.setdefault(question_id, {
            "original_chapter": question.chapter, "original_title": question.chapter_title,
        }).update({"chapter": chapter, "title": title})
        self.questions = tuple(
            replace(item, chapter=chapter, chapter_title=title) if item.question_id == question_id else item
            for item in self.questions
        )
        self._candidate = None
        self._comparison = None
        self._events.append(SessionEvent(f"PFV2-EVENT-{len(self._events)+1:06d}", question_id, "question:chapter_reassigned"))
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

    def candidate_inspection(self) -> dict:
        """Return local-only source-first candidate inspection data."""
        if self._candidate is None:
            return {"state": "not_built"}
        questions = self._candidate.questions
        groups: dict[tuple[int | None, str], list] = {}
        order: list[tuple[int | None, str]] = []
        for question in questions:
            key = (question.chapter, question.chapter_title)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(question)
        chapter_rows = []
        warnings = []
        seen_numbers: dict[int | None, set[str]] = {}
        for number, title in order:
            items = groups[(number, title)]
            if number is None:
                warnings.append("questions_without_chapter")
            if not title.strip():
                warnings.append(f"unnamed_chapter:{number}")
            seen_numbers.setdefault(number, set()).add(title)
            if len(items) < 2:
                warnings.append(f"unusually_small_chapter:{number}")
            if len(items) > 100:
                warnings.append(f"unusually_large_chapter:{number}")
            chapter_row = {"chapter": number, "title": title, "question_count": len(items)}
            # Keep the audit origin visible to the local UI so an operator can
            # deliberately undo a bulk metadata correction.  The original
            # parser value itself remains in the checkpoint edit record.
            for edit in self._chapter_edits.values():
                if edit["chapter"] == number and edit["title"] == title:
                    chapter_row.update({
                        "original_chapter": edit["original_chapter"],
                        "original_title": edit["original_title"],
                    })
                    break
            chapter_rows.append(chapter_row)
        warnings.extend(f"duplicated_chapter_number:{number}" for number, titles in seen_numbers.items() if len(titles) > 1)
        serialized_questions = [
            {
                "question_id": item.question_id,
                "source_record_id": item.source_record_id,
                "chapter": item.chapter,
                "chapter_title": item.chapter_title,
                "question_type": item.question_type,
                "stem": item.stem,
                "choices": [list(choice) for choice in item.choices],
                "correct_answers": list(item.correct_answers),
                "rationale": item.rationale,
                "position_in_chapter": len(groups[(item.chapter, item.chapter_title)][:groups[(item.chapter, item.chapter_title)].index(item) + 1]),
            }
            for item in questions
        ]
        digest = hashlib.sha256(json.dumps(serialized_questions, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "state": "ready",
            "overview": {
                "title": (self._source_metadata or {}).get("display_name") or "New Pack candidate",
                "chapter_count": len(chapter_rows),
                "retained_questions": len(questions),
                "excluded_questions": self._candidate_view()["documented_exclusion_count"],
                "applied_fixes": len(self._candidate.applied_proposal_ids),
                "unresolved_blockers": len(self._candidate.unresolved_finding_ids),
                "qa_finding_count": len(detect_candidate_damage(questions).findings),
                "candidate_sha256": digest,
            },
            "chapters": chapter_rows,
            "chapter_count_matches_total": sum(item["question_count"] for item in chapter_rows) == len(questions),
            "warnings": sorted(set(warnings)),
            "questions": serialized_questions,
        }

    def record_disposition(
        self, finding_id: str, action: str, target_question_id: str | None = None
    ) -> dict:
        self._ensure_active_run_if_configured()
        case = self._case(finding_id)
        action_map = {
            "leave_blocked": DispositionAction.RETAIN_BLOCKER,
            "exclude_record": DispositionAction.EXCLUDE_RECORD,
            "accept_as_is": DispositionAction.ACCEPT_AS_IS,
        }
        if action == "restore_record" and action in case.allowed_actions:
            self._dispositions_by_finding.pop(finding_id, None)
            self._candidate = None
            self._comparison = None
            self._return_lifecycle_to_review()
            self._save_checkpoint()
            return self.view()
        if action not in action_map or (
            action not in case.allowed_actions
            and not (action == "accept_as_is" and case.proposal is None)
        ):
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

    def approve_comparison_group(self, group_id: str) -> dict:
        self._ensure_active_run_if_configured()
        if self._candidate is None or self._comparison is None:
            raise DomainError("Build and compare an isolated candidate before group review")
        benchmark = self._benchmark_questions or self.questions
        self._candidate, group = apply_exact_contaminant_group(
            self._candidate, benchmark, group_id
        )
        self._approved_comparison_group_ids.add(group.group_id)
        self._post_group_qa_result = detect_candidate_damage(self._candidate.questions)
        self._comparison = compare_candidate(self._candidate, benchmark)
        if self._lifecycle is not None:
            self._lifecycle.return_to_review()
            self._lifecycle.record_candidate(
                question_count=len(self._candidate.questions),
                unresolved_findings=len(self._post_group_qa_result.findings),
            )
            self._lifecycle.record_comparison(
                field_changes=len(self._comparison.field_changes),
                id_accounting_complete=self._comparison.id_accounting_complete,
            )
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=group.group_id,
                event_type="comparison_group:approved_exact_scope_and_rechecked",
            )
        )
        self._save_checkpoint()
        return self.view()

    def approve_comparison_category(self, category_id: str, action: str) -> dict:
        self._ensure_active_run_if_configured()
        if self._candidate is None or self._comparison is None:
            raise DomainError("Build and compare an isolated candidate before category review")
        categories = {
            item.category_id: item
            for item in categorize_comparison_changes(self._comparison)
        }
        category = categories.get(category_id)
        if category is None:
            raise DomainError("Comparison category is missing or no longer current")
        if category.classification == "repeated_metadata_difference":
            if action != "accept_candidate":
                raise DomainError("Repeated metadata requires an explicit accept-candidate decision")
        else:
            if action != "use_reference":
                raise DomainError("Content correction requires an explicit use-reference decision")
            if category_id not in self._viewed_comparison_categories:
                raise DomainError("Open the temporary source page before approving this correction")
            self._candidate = apply_category_reference_values(self._candidate, category)
        self._comparison_category_decisions[category_id] = action
        benchmark = self._benchmark_questions or self.questions
        self._post_group_qa_result = detect_candidate_damage(self._candidate.questions)
        self._comparison = compare_candidate(self._candidate, benchmark)
        if self._lifecycle is not None:
            self._lifecycle.return_to_review()
            self._lifecycle.record_candidate(
                question_count=len(self._candidate.questions),
                unresolved_findings=len(self._post_group_qa_result.findings),
            )
            self._lifecycle.record_comparison(
                field_changes=len(self._comparison.field_changes),
                id_accounting_complete=self._comparison.id_accounting_complete,
            )
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=category_id,
                event_type=f"comparison_category:{action}_and_rechecked",
            )
        )
        self._save_checkpoint()
        return self.view()

    def view_comparison_source(self, category_id: str) -> dict:
        if self._lifecycle is None or self._lifecycle.manifest().get("source_type") != "pdf":
            raise DomainError("A temporary source page is available only for an active PDF run")
        if self._comparison is None:
            raise DomainError("Run comparison before viewing category source evidence")
        categories = {
            item.category_id: item
            for item in categorize_comparison_changes(self._comparison)
        }
        category = categories.get(category_id)
        if category is None or len(category.changes) != 1:
            raise DomainError("Individual source viewing requires one current comparison change")
        question_id = category.changes[0].question_id
        question = next(
            (item for item in self._candidate.questions if item.question_id == question_id),
            None,
        )
        if question is None or not self._source_pages:
            raise DomainError("Temporary source evidence is unavailable")
        change = category.changes[0]
        source_anchor = (
            change.benchmark_value
            if change.field == "stem" and isinstance(change.benchmark_value, str)
            else question.stem
        )
        needle = _source_search_text(source_anchor)
        matches = [
            index for index, page in enumerate(self._source_pages)
            if needle and needle in _source_search_text(page)
        ]
        if len(matches) != 1:
            raise DomainError("Temporary source page could not be located unambiguously")
        self._viewed_comparison_categories.add(category_id)
        page_index = matches[0]
        return {
            "category_id": category_id,
            "page_number": page_index + 1,
            "page_count": len(self._source_pages),
            "text": self._source_pages[page_index],
            "temporary": True,
        }

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
        """Return the existing verified previous/current/next source window.

        Reading source evidence is always safe.  It must remain available after
        a repair is approved so an operator can inspect the source alongside
        the effective candidate question.
        """
        if self._lifecycle is None or self._lifecycle.manifest().get("source_type") != "pdf":
            raise DomainError("A temporary source page is available only for an active PDF run")
        case = self._case(finding_id)
        if not self._source_pages:
            raise DomainError("Temporary source pages are no longer available")
        page_indexes = _source_context_page_indexes(
            case.question.stem,
            self._source_pages,
        )
        if not page_indexes:
            raise DomainError("PrepFlow could not locate one unambiguous temporary source page")
        page_index = page_indexes[0]
        first = max(0, page_indexes[0] - 1)
        last = min(len(self._source_pages), page_indexes[-1] + 2)
        self._viewed_source_findings.add(finding_id)
        event_number = len(self._events) + 1
        self._events.append(
            SessionEvent(
                event_id=f"PFV2-EVENT-{event_number:06d}",
                finding_id=finding_id,
                event_type=(
                    f"source_page:viewed:{page_index + 1}"
                    if len(page_indexes) == 1
                    else f"source_pages:viewed:{page_indexes[0] + 1}-{page_indexes[-1] + 1}"
                ),
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
            "page_range": [page_indexes[0] + 1, page_indexes[-1] + 1],
            "pages": [
                {
                    "page_number": index + 1,
                    "role": (
                        "current" if index in page_indexes else "previous" if index < page_indexes[0] else "next"
                    ),
                    "text": self._source_pages[index],
                }
                for index in range(first, last)
            ],
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
        finding_ids = {item.finding_id for item in self.findings}
        return build_review_queue(
            self.questions,
            self.findings,
            tuple(item for item in self.proposals if item.finding_id in finding_ids),
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
        blocking_reasons = list(readiness.blocking_reasons)
        if self._source_only:
            blocking_reasons.append("source_only_candidate_requires_explicit_pack_creation")
        if self._comparison is not None and self._unreviewed_comparison_change_count():
            blocking_reasons.append("unreviewed_comparison_field_changes")
        if self._post_group_qa_result is not None and self._post_group_qa_result.findings:
            blocking_reasons.append("post_group_qa_findings")
        identity_excluded_record_ids = sorted(
            record_id
            for record_id, action in self._identity_actions.items()
            if action.get("action") in {"exclude_parser_debris", "exclude_duplicate"}
        )
        return {
            "state": "built_in_memory",
            "persistent": False,
            "question_count": len(self._candidate.questions),
            "applied_proposal_ids": list(self._candidate.applied_proposal_ids),
            "unresolved_finding_ids": list(self._candidate.unresolved_finding_ids),
            "excluded_question_ids": list(self._candidate.excluded_question_ids),
            "excluded_source_record_ids": identity_excluded_record_ids,
            "documented_exclusion_count": (
                len(self._candidate.excluded_question_ids)
                + len(identity_excluded_record_ids)
            ),
            "promotion_ready": False if self._source_only else readiness.ready and not blocking_reasons,
            "blocking_reasons": blocking_reasons,
        }

    def _comparison_view(self) -> dict:
        payload = comparison_view(self._comparison)
        candidate_by_id = {
            item.question_id: item for item in self._candidate.questions
        } if self._candidate else {}
        benchmark_by_id = {
            item.question_id: item for item in (self._benchmark_questions or self.questions)
        }
        payload["question_context"] = [
            {
                "question_id": question_id,
                "candidate": _question_comparison_context(candidate_by_id.get(question_id)),
                "benchmark": _question_comparison_context(benchmark_by_id.get(question_id)),
            }
            for question_id in sorted({item.question_id for item in self._comparison.field_changes})
        ]
        payload["field_changes_require_review"] = bool(
            self._unreviewed_comparison_change_count()
        )
        payload["exact_contaminant_groups"] = [
            contaminant_group_view(item)
            for item in detect_exact_contaminant_groups(self._comparison)
        ]
        payload["review_categories"] = []
        for item in categorize_comparison_changes(self._comparison):
            category = comparison_category_view(item)
            category["decision"] = self._comparison_category_decisions.get(item.category_id)
            category["source_viewed"] = item.category_id in self._viewed_comparison_categories
            category["allowed_action"] = (
                "accept_candidate"
                if item.classification == "repeated_metadata_difference"
                else "use_reference"
            )
            payload["review_categories"].append(category)
        payload["approved_exact_group_ids"] = sorted(self._approved_comparison_group_ids)
        payload["post_group_qa"] = (
            {
                "state": "complete",
                "finding_count": len(self._post_group_qa_result.findings),
                "detector_counts": dict(self._post_group_qa_result.detector_counts),
                "automatic_repairs": self._post_group_qa_result.automatic_repairs,
            }
            if self._post_group_qa_result is not None
            else {"state": "not_run"}
        )
        return payload

    def _unreviewed_comparison_change_count(self) -> int:
        if self._comparison is None:
            return 0
        accounted = {
            (change.question_id, change.field)
            for category in categorize_comparison_changes(self._comparison)
            if self._comparison_category_decisions.get(category.category_id) == "accept_candidate"
            for change in category.changes
        }
        return sum(
            (change.question_id, change.field) not in accounted
            for change in self._comparison.field_changes
        )

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
                "parsed_choices": [list(item) for item in case.parsed_choices],
                "parsed_correct_answers": list(case.parsed_correct_answers),
                "status": self._identity_actions.get(case.record_id, {}).get("action", "pending"),
                "selected_target_question_id": self._identity_actions.get(case.record_id, {}).get("target_question_id") or None,
                "field_repair_staged": case.record_id in self._identity_repair_findings,
                "suggestions": [item.__dict__ for item in case.suggestions],
            }
            for case in self._identity_cases
        ]
        view["review_approved_count"] = sum(
            item.get("action") == "approve" for item in self._identity_actions.values()
        )
        view["unresolved_count"] = sum(
            self._identity_actions.get(case.record_id, {}).get("action", "pending") in {"pending", "defer"}
            for case in self._identity_cases
        )
        view["automatic_id_assignments_authorized"] = self._identity_report.complete
        view["reviewed_id_assignments_authorized"] = bool(resolved and self._identity_cases)
        return view

    def _allocate_new_question_id(self, record_id: str) -> str:
        """Allocate a deterministic run-local ID without renumbering old questions."""
        if self._identity_target_pack is None or self._identity_report is None:
            raise DomainError("New identity allocation requires a protected identity target")
        existing_ids = {
            str(item.get("id") or "")
            for item in self._identity_target_pack.get("questions", [])
        }
        try:
            highest = max(int(item.rsplit("-", 1)[1]) for item in existing_ids)
            record_number = int(record_id.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            raise DomainError("Stable identity allocation inputs are malformed")
        question_id = (
            f"PFQ-{self._identity_report.target_pack_id}-"
            f"{highest + record_number:09d}"
        )
        if question_id in existing_ids:
            raise DomainError("Allocated stable question ID collides with the protected Pack")
        return question_id

    def _save_checkpoint(self) -> None:
        if self._lifecycle is None or (self._identity_report is None and not self._source_only):
            return
        write_private_user_proposals(self._lifecycle.run_directory, self.proposals)
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
                "target_pack_id": (self._identity_report.target_pack_id if self._identity_report is not None else f"source_only:{self._source_metadata['slug']}"),
                "identity_actions": [
                    {
                        "record_id": record_id,
                        "action": value["action"],
                        "target_question_id": value["target_question_id"],
                    }
                    for record_id, value in sorted(self._identity_actions.items())
                    if value["action"] in {"approve", "retain_new_question", "exclude_parser_debris", "exclude_duplicate", "defer"}
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
                "chapter_edits": list(self._chapter_edits.values()),
                "question_chapter_edits": [
                    {"question_id": question_id, **value}
                    for question_id, value in sorted(self._question_chapter_edits.items())
                ],
                "comparison_counts": comparison_counts,
                "comparison_group_decisions": [
                    {"group_id": group_id, "action": "approve_exact_group"}
                    for group_id in sorted(self._approved_comparison_group_ids)
                ],
                "comparison_category_decisions": [
                    {"category_id": category_id, "action": action}
                    for category_id, action in sorted(self._comparison_category_decisions.items())
                ],
            },
        )

    def _restore_chapter_edits(self, checkpoint: dict) -> None:
        for edit in checkpoint.get("chapter_edits", []):
            if not all(key in edit for key in ("original_chapter", "original_title", "chapter", "title")):
                continue
            key = f"{edit['original_chapter']}|{edit['original_title']}"
            affected = {
                item.question_id for item in self.questions
                if item.chapter == edit["original_chapter"] and item.chapter_title == edit["original_title"]
            }
            self.questions = tuple(
                replace(item, chapter=edit["chapter"], chapter_title=edit["title"]) if item.question_id in affected else item
                for item in self.questions
            )
            self._chapter_edits[key] = dict(edit)
        for edit in checkpoint.get("question_chapter_edits", []):
            question_id = edit.get("question_id")
            if not isinstance(question_id, str) or not all(key in edit for key in ("original_chapter", "original_title", "chapter", "title")):
                continue
            self.questions = tuple(
                replace(item, chapter=edit["chapter"], chapter_title=edit["title"]) if item.question_id == question_id else item
                for item in self.questions
            )
            self._question_chapter_edits[question_id] = {key: edit[key] for key in ("original_chapter", "original_title", "chapter", "title")}

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
            "source_only": bool(manifest.get("source_only")),
            "source_metadata": manifest.get("source_metadata"),
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
        self._approved_comparison_group_ids.clear()
        self._post_group_qa_result = None
        self._comparison_category_decisions.clear()
        self._viewed_comparison_categories.clear()
        self._source_only = False
        self._source_metadata = None
        self.questions, self.findings, self.proposals = (), (), ()
        self._decisions_by_proposal.clear()
        self._verifications_by_proposal.clear()
        self._dispositions_by_finding.clear()


def _locate_source_page(value: str, pages: tuple[str, ...]) -> int:
    needle = _source_search_text(value)
    if not needle:
        raise DomainError("Identity record has no searchable source text")
    matches = [
        index
        for index, page in enumerate(pages)
        if needle in _source_search_text(page)
    ]
    if len(matches) == 1:
        return matches[0]

    # A parsed stem may cross a page boundary. In that case, use only its
    # opening words as a temporary page anchor; ambiguity remains blocked.
    anchor = " ".join(needle.split()[:12])
    matches = [
        index
        for index, page in enumerate(pages)
        if anchor and anchor in _source_search_text(page)
    ]
    if len(matches) != 1:
        raise DomainError("PrepFlow could not locate one unambiguous temporary source page")
    return matches[0]


def _source_context_page_indexes(value: str, pages: tuple[str, ...]) -> tuple[int, ...]:
    """Return a verified temporary-source page or contiguous page range.

    A saved parsed stem can contain a trailing page footer which physically
    follows the question's rationale.  In that case an exact whole-stem search
    is invalid, but a unique opening anchor still provides trustworthy source
    provenance.  A range is returned only when unique opening and closing
    anchors identify its two ends; otherwise ambiguity remains blocked.
    """
    needle = _source_search_text(value)
    if not needle:
        return ()
    normalized_pages = tuple(_source_search_text(page) for page in pages)
    exact_matches = tuple(
        index for index, page in enumerate(normalized_pages) if needle in page
    )
    if len(exact_matches) == 1:
        return exact_matches

    words = needle.split()
    opening_anchor = " ".join(words[:12])
    opening_matches = tuple(
        index for index, page in enumerate(normalized_pages)
        if opening_anchor and opening_anchor in page
    )
    if len(opening_matches) != 1:
        return ()

    # A footer or other trailing parser contamination may not exist at the
    # physical end of the question.  The unique opening anchor is therefore a
    # valid single-page provenance result.  Only expand to a range when a
    # distinct, unique closing anchor supports it.
    for size in range(min(12, len(words)), 3, -1):
        closing_anchor = " ".join(words[-size:])
        closing_matches = tuple(
            index for index, page in enumerate(normalized_pages)
            if closing_anchor and closing_anchor in page
        )
        if len(closing_matches) == 1 and closing_matches[0] >= opening_matches[0]:
            return tuple(range(opening_matches[0], closing_matches[0] + 1))
    return opening_matches


def _source_search_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _question_comparison_context(question) -> dict | None:
    if question is None:
        return None
    choice_by_label = dict(question.choices)
    return {
        "chapter": question.chapter,
        "chapter_title": question.chapter_title,
        "stem": question.stem,
        "correct_answers": list(question.correct_answers),
        "correct_answer_text": [
            {"label": label, "text": choice_by_label.get(label)}
            for label in question.correct_answers
        ],
    }


def _restore_private_proposal_collections(proposal: Proposal) -> Proposal:
    """JSON stores collections as lists; QuestionRecord stores immutable tuples."""
    if proposal.field == "correct_answers":
        return Proposal(
            proposal.proposal_id, proposal.finding_id, proposal.question_id,
            proposal.field, tuple(proposal.expected_before), tuple(proposal.proposed_after),
            proposal.explanation, proposal.requires_source_verification,
        )
    if proposal.field == "choices":
        return Proposal(
            proposal.proposal_id, proposal.finding_id, proposal.question_id,
            proposal.field, tuple(tuple(item) for item in proposal.expected_before),
            tuple(tuple(item) for item in proposal.proposed_after), proposal.explanation,
            proposal.requires_source_verification,
        )
    return proposal


def _validated_complete_question(question, values: dict):
    if not isinstance(values, dict):
        raise DomainError("Complete question values are required")
    choices = values.get("choices")
    if not isinstance(choices, list):
        raise DomainError("Choices must be provided as labeled text")
    normalized_choices = tuple(
        (str(item.get("label", "")).strip().upper(), str(item.get("text", "")).strip())
        for item in choices if isinstance(item, dict)
    )
    labels = tuple(label for label, text in normalized_choices)
    if len(labels) != len(choices) or not all(labels) or not all(text for _, text in normalized_choices):
        raise DomainError("Every choice needs a label and text")
    if len(labels) != len(set(labels)):
        raise DomainError("Choice labels must be unique")
    expected_labels = tuple(chr(ord("A") + index) for index in range(len(labels)))
    if labels != expected_labels:
        raise DomainError("Choice labels must be ordered A, B, C, and so on")
    answers = tuple(str(item).strip().upper() for item in values.get("correct_answers", []))
    if any(answer not in labels for answer in answers):
        raise DomainError("Each correct-answer label must be one of the choices")
    if question.question_type in {"multiple_choice", "multiple_response"} and not normalized_choices:
        raise DomainError("Multiple-choice questions require usable choices")
    if normalized_choices and not answers:
        raise DomainError("Select at least one correct answer")
    if question.question_type == "multiple_choice" and len(answers) > 1:
        raise DomainError("A single-answer question can have only one correct answer")
    return replace_question_field(
        replace_question_field(
            replace_question_field(
                replace_question_field(question, "stem", str(values.get("stem", "")).strip()),
                "choices", normalized_choices,
            ),
            "correct_answers", answers,
        ),
        "rationale", str(values.get("rationale", "")).strip(),
    )


def _next_user_proposal_number(proposals: tuple[Proposal, ...]) -> int:
    numbers = []
    for proposal in proposals:
        if proposal.proposal_id.startswith("PFV2-PROP-USER-"):
            try:
                numbers.append(int(proposal.proposal_id.rsplit("-", 1)[1]))
            except ValueError:
                continue
    return max(numbers, default=0) + 1
