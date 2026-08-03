from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingestion_v2.checkpoint import read_checkpoint
from ingestion_v2.comparison import ComparisonReport, compare_candidate
from ingestion_v2.domain import (
    Candidate, DispositionAction, DomainError, Finding, FindingDisposition,
    Proposal, QuestionRecord, ReviewAction, ReviewDecision, SourceVerification,
)
from ingestion_v2.engine import build_candidate
from ingestion_v2.identity import IdentityReport, match_existing_pack_identity
from ingestion_v2.identity_review import IdentityReviewCase, authorize_reviewed_identity, build_identity_review_cases
from ingestion_v2.pack_bridge import pack_questions_to_domain
from ingestion_v2.parser import ExistingParserAdapter, ParseBatch
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.proposal_adapter import draft_benchmark_answer_proposals, draft_deterministic_proposals
from ingestion_v2.qa_adapter import QaResult, detect_candidate_damage
from ingestion_v2.run_lifecycle import RunLifecycle


@dataclass(frozen=True)
class RecoveredRun:
    lifecycle: RunLifecycle
    parse_batch: ParseBatch
    identity_report: IdentityReport
    identity_cases: tuple[IdentityReviewCase, ...]
    identity_actions: dict[str, dict[str, str]]
    identity_mapping: dict[str, str]
    questions: tuple[QuestionRecord, ...]
    findings: tuple[Finding, ...]
    proposals: tuple[Proposal, ...]
    decisions: tuple[ReviewDecision, ...]
    verifications: tuple[SourceVerification, ...]
    dispositions: tuple[FindingDisposition, ...]
    benchmark: tuple[QuestionRecord, ...]
    qa_result: QaResult
    candidate: Candidate | None
    comparison: ComparisonReport | None


def recover_run(run_directory: Path, target_pack: dict) -> RecoveredRun:
    lifecycle = RunLifecycle.open(run_directory)
    manifest = lifecycle.manifest()
    if manifest.get("stage") in {"completed", "failed", "failed_cleaned"}:
        raise DomainError("Only an active source-bearing run can be resumed")
    checkpoint = read_checkpoint(run_directory)
    if checkpoint["target_pack_id"] != target_pack.get("pack_id"):
        raise DomainError("Checkpoint target Pack does not match the selected Pack")
    cleaned_path = Path(run_directory) / "artifacts" / "cleaned.txt"
    if cleaned_path.is_symlink() or not cleaned_path.is_file():
        raise DomainError("Resume requires the controlled cleaned artifact")

    batch = ExistingParserAdapter().parse(cleaned_path.read_text(encoding="utf-8"))
    report = match_existing_pack_identity(batch, target_pack)
    cases = build_identity_review_cases(batch, target_pack, report)
    approvals = {
        item["record_id"]: item["target_question_id"]
        for item in checkpoint["identity_actions"]
    }
    if report.complete:
        mapping = report.stable_id_by_record_id
    else:
        mapping = authorize_reviewed_identity(report, cases, approvals)
    identity_actions = {
        record_id: {"action": "approve", "target_question_id": target_id}
        for record_id, target_id in approvals.items()
    }

    questions, parser_findings = materialize_matched_batch(batch, mapping)
    benchmark = pack_questions_to_domain(target_pack)
    qa = detect_candidate_damage(questions)
    parser_answer_ids = {
        item.question_id for item in parser_findings
        if item.damage_type == "correct_answer_without_choice"
    }
    qa = QaResult(
        findings=tuple(
            item for item in qa.findings
            if not (
                item.question_id in parser_answer_ids
                and item.damage_type == "choice_structure__correct_answer_without_choice"
            )
        ),
        detector_counts=qa.detector_counts,
    )
    findings = parser_findings + qa.findings
    proposals = (
        draft_deterministic_proposals(questions, findings)
        + draft_benchmark_answer_proposals(questions, benchmark, findings)
    )
    proposal_ids = {item.proposal_id for item in proposals}
    finding_by_id = {item.finding_id: item for item in findings}

    decisions = tuple(
        ReviewDecision(item["decision_id"], item["proposal_id"], ReviewAction(item["action"]), "Recovered from private checkpoint.")
        for item in checkpoint["review_decisions"]
    )
    verifications = tuple(
        SourceVerification(item["verification_id"], item["proposal_id"], item["verified"], "Recovered verified checkpoint event.")
        for item in checkpoint["verifications"]
    )
    if any(item.proposal_id not in proposal_ids for item in decisions + verifications):
        raise DomainError("Checkpoint references a proposal that cannot be reproduced exactly")
    dispositions = []
    for item in checkpoint["dispositions"]:
        finding = finding_by_id.get(item["finding_id"])
        if finding is None or finding.question_id != item["question_id"]:
            raise DomainError("Checkpoint disposition finding cannot be reproduced exactly")
        dispositions.append(
            FindingDisposition(
                item["disposition_id"], item["finding_id"], item["question_id"],
                DispositionAction(item["action"]), "Recovered from private checkpoint.",
            )
        )
    dispositions = tuple(dispositions)

    candidate = comparison = None
    counts = checkpoint["comparison_counts"]
    if manifest["stage"] in {"candidate_built", "compared"} or counts:
        candidate = build_candidate(questions, findings, proposals, decisions, verifications, dispositions)
    if counts:
        comparison = compare_candidate(candidate, benchmark)
        expected = {
            "field_changes": len(comparison.field_changes),
            "excluded_questions": len(comparison.documented_excluded_question_ids),
            "candidate_questions": comparison.candidate_question_count,
        }
        if counts != expected:
            raise DomainError("Recovered comparison counts do not match the checkpoint")
    return RecoveredRun(
        lifecycle, batch, report, cases, identity_actions, mapping, questions,
        findings, proposals, decisions, verifications, dispositions, benchmark,
        qa, candidate, comparison,
    )
