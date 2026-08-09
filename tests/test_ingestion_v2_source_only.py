import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.source_intake import validate_source_metadata
from ingestion_v2.workbench_session import SyntheticWorkbenchSession
from tests.test_ingestion_v2_workbench_session import synthetic_pdf_bytes


def test_source_only_intake_preserves_internal_identity_metadata_and_blocks_promotion(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path)
    session.start_pdf_run(synthetic_pdf_bytes([
        "Chapter 1: Pediatrics", "1. Which finding?", "A. First", "B. Second", "ANS: A", "Rationale."
    ]))
    payload = session.materialize_source_only(
        {"display_name": "Pediatrics", "slug": "pediatrics", "prefix": "Peds"},
        registered_preset=True,
    )
    assert payload["run"]["state"] == "review_ready"
    assert session.questions[0].question_id == "PFQ-pediatrics-000000001"
    assert session.questions[0].chapter_title == "Pediatrics"
    assert payload["pipeline"]["source_metadata"] == {"display_name": "Pediatrics", "slug": "pediatrics", "prefix": "Peds"}
    candidate = session.build_isolated_candidate()["candidate"]
    assert candidate["promotion_ready"] is False
    assert "source_only_candidate_requires_explicit_pack_creation" in candidate["blocking_reasons"]


def test_new_source_rejects_collisions_and_private_path_identifiers() -> None:
    reserved = {"fundamentals", "fund", "pediatrics", "peds"}
    with pytest.raises(DomainError):
        validate_source_metadata({"display_name": "New", "slug": "fundamentals", "prefix": "New"}, reserved=reserved)
    with pytest.raises(DomainError):
        validate_source_metadata({"display_name": "private_sources/report.pdf", "slug": "new_book", "prefix": "New"}, reserved=reserved)
    with pytest.raises(DomainError):
        validate_source_metadata({"display_name": "New", "slug": "new_book", "prefix": "Peds"}, reserved=reserved)


def test_new_source_reload_preserves_metadata_and_deterministic_ids(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path)
    session.start_pdf_run(synthetic_pdf_bytes([
        "Chapter 1: Adult Health", "1. Which finding?", "A. First", "B. Second", "ANS: A", "Rationale."
    ]))
    session.materialize_source_only({"display_name": "Adult Health", "slug": "adult_health", "prefix": "Adult Health"})
    resumed = SyntheticWorkbenchSession.resume_source_only_run(session._lifecycle.run_directory)
    assert resumed.questions[0].question_id == "PFQ-adult_health-000000001"
    assert resumed.view()["pipeline"]["source_metadata"]["prefix"] == "Adult Health"


def test_zero_parsed_records_is_a_document_blocker_not_a_successful_run(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path)
    payload = session.start_pdf_run(synthetic_pdf_bytes(["This PDF has no question shapes."]))
    assert payload["run"]["state"] == "failed"
    assert payload["pipeline"]["document_findings"][0]["damage_type"] == "zero_parsed_records"
