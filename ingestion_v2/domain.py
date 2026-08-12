from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import re
from typing import Any


QUESTION_ID_RE = re.compile(r"^PFQ-[a-z0-9_]+-\d{9}$")
FIELD_RE = re.compile(r"^(?:stem|rationale|chapter_title|correct_answers|choices)$")


class DomainError(ValueError):
    """Raised when a v2 record violates a safety invariant."""


class FindingSeverity(str, Enum):
    ADVISORY = "advisory"
    BLOCKING = "blocking"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


class DispositionAction(str, Enum):
    RETAIN_BLOCKER = "retain_blocker"
    EXCLUDE_RECORD = "exclude_record"
    ACCEPT_AS_IS = "accept_as_is"


@dataclass(frozen=True)
class QuestionRecord:
    question_id: str
    chapter: int | None
    question_type: str
    stem: str
    choices: tuple[tuple[str, str], ...] = ()
    correct_answers: tuple[str, ...] = ()
    rationale: str = ""
    chapter_title: str = ""
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        if not QUESTION_ID_RE.fullmatch(self.question_id):
            raise DomainError("Question ID must be a stable PrepFlow ID")
        # Damaged choice structures are valid workbench input. QA owns the
        # finding and promotion block; the domain preserves the evidence.
        if self.source_record_id is not None and not re.fullmatch(r"PFV2-REC-\d{6}", self.source_record_id):
            raise DomainError("Source record ID must be a temporary v2 record ID")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    question_id: str
    field: str
    damage_type: str
    severity: FindingSeverity
    explanation: str
    related_question_id: str | None = None

    def __post_init__(self) -> None:
        _validate_reference(self.finding_id, "PFV2-FIND-")
        _validate_question_and_field(self.question_id, self.field)
        if not self.damage_type or not self.explanation:
            raise DomainError("Finding type and explanation are required")
        if self.related_question_id is not None and not QUESTION_ID_RE.fullmatch(self.related_question_id):
            raise DomainError("Related question ID must be a stable PrepFlow ID")


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    finding_id: str
    question_id: str
    field: str
    expected_before: Any
    proposed_after: Any
    explanation: str
    requires_source_verification: bool = False

    def __post_init__(self) -> None:
        _validate_reference(self.proposal_id, "PFV2-PROP-")
        _validate_reference(self.finding_id, "PFV2-FIND-")
        _validate_question_and_field(self.question_id, self.field)
        if self.expected_before == self.proposed_after:
            raise DomainError("A proposal must describe an actual change")
        if not self.explanation:
            raise DomainError("A proposal explanation is required")


@dataclass(frozen=True)
class ReviewDecision:
    decision_id: str
    proposal_id: str
    action: ReviewAction
    reviewer_note: str = ""

    def __post_init__(self) -> None:
        _validate_reference(self.decision_id, "PFV2-DEC-")
        _validate_reference(self.proposal_id, "PFV2-PROP-")


@dataclass(frozen=True)
class SourceVerification:
    verification_id: str
    proposal_id: str
    verified: bool
    reviewer_note: str

    def __post_init__(self) -> None:
        _validate_reference(self.verification_id, "PFV2-VERIFY-")
        _validate_reference(self.proposal_id, "PFV2-PROP-")
        if self.verified and not self.reviewer_note:
            raise DomainError("Source verification requires a reviewer note")


@dataclass(frozen=True)
class FindingDisposition:
    disposition_id: str
    finding_id: str
    question_id: str
    action: DispositionAction
    reviewer_note: str

    def __post_init__(self) -> None:
        _validate_reference(self.disposition_id, "PFV2-DISP-")
        _validate_reference(self.finding_id, "PFV2-FIND-")
        if not QUESTION_ID_RE.fullmatch(self.question_id):
            raise DomainError("Disposition requires a stable PrepFlow question ID")
        if not self.reviewer_note:
            raise DomainError("Disposition requires a reviewer note")


@dataclass(frozen=True)
class Candidate:
    questions: tuple[QuestionRecord, ...]
    applied_proposal_ids: tuple[str, ...] = ()
    unresolved_finding_ids: tuple[str, ...] = ()
    audit_events: tuple[str, ...] = field(default_factory=tuple)
    excluded_question_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(question.question_id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise DomainError("Candidate question IDs must be unique")
        if set(ids) & set(self.excluded_question_ids):
            raise DomainError("A candidate cannot contain an excluded question")


@dataclass(frozen=True)
class PromotionReadiness:
    ready: bool
    blocking_reasons: tuple[str, ...]


def replace_question_field(question: QuestionRecord, field_name: str, value: Any) -> QuestionRecord:
    if not FIELD_RE.fullmatch(field_name):
        raise DomainError("Proposal field is not editable")
    if field_name in {"choices", "correct_answers"} and isinstance(value, list):
        value = tuple(tuple(item) if isinstance(item, list) else item for item in value)
    return replace(question, **{field_name: value})


def _validate_question_and_field(question_id: str, field_name: str) -> None:
    if not QUESTION_ID_RE.fullmatch(question_id):
        raise DomainError("Question ID must be a stable PrepFlow ID")
    if not FIELD_RE.fullmatch(field_name):
        raise DomainError("Finding field is not source-neutral or editable")


def _validate_reference(value: str, prefix: str) -> None:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) == len(prefix):
        raise DomainError(f"Reference must start with {prefix}")
