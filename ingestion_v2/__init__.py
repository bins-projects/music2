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
from ingestion_v2.review import ReviewCase, ReviewQueue, ReviewStatus, build_review_queue
from ingestion_v2.review_view import review_queue_view
from ingestion_v2.parser import ExistingParserAdapter, ParseBatch, ParsedRecord, ParserFinding
from ingestion_v2.parser_bridge import materialize_matched_batch
from ingestion_v2.comparison import ComparisonReport, FieldChange, compare_candidate

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
    "ReviewCase",
    "ReviewQueue",
    "ReviewStatus",
    "build_review_queue",
    "review_queue_view",
    "ExistingParserAdapter",
    "ParseBatch",
    "ParsedRecord",
    "ParserFinding",
    "materialize_matched_batch",
    "ComparisonReport",
    "FieldChange",
    "compare_candidate",
]
