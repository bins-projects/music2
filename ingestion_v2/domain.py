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

    def __post_init__(self) -> None:
        if not QUESTION_ID_RE.fullmatch(self.question_id):
            raise DomainError("Question ID must be a stable PrepFlow ID")
        labels = tuple(label for label, _ in self.choices)
        if any(not label or not text for label, text in self.choices):
            raise DomainError("Choices require non-empty labels and text")
        if len(labels) != len(set(labels)):
            raise DomainError("Choice labels must be unique")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    question_id: str
    field: str
    damage_type: str
    severity: FindingSeverity
    explanation: str

    def __post_init__(self) -> None:
        _validate_reference(self.finding_id, "PFV2-FIND-")
        _validate_question_and_field(self.question_id, self.field)
        if not self.damage_type or not self.explanation:
            raise DomainError("Finding type and explanation are required")


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
class Candidate:
    questions: tuple[QuestionRecord, ...]
    applied_proposal_ids: tuple[str, ...] = ()
    unresolved_finding_ids: tuple[str, ...] = ()
    audit_events: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ids = tuple(question.question_id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise DomainError("Candidate question IDs must be unique")


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
