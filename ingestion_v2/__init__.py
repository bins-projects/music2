"""PrepFlow's source-neutral, candidate-first ingestion engine."""

from ingestion_v2.domain import (
    Candidate,
    Finding,
    FindingSeverity,
    Proposal,
    QuestionRecord,
    ReviewAction,
    ReviewDecision,
    SourceVerification,
)
from ingestion_v2.engine import build_candidate, promotion_readiness

__all__ = [
    "Candidate",
    "Finding",
    "FindingSeverity",
    "Proposal",
    "QuestionRecord",
    "ReviewAction",
    "ReviewDecision",
    "SourceVerification",
    "build_candidate",
    "promotion_readiness",
]
