from ingestion_v2.workbench_session import SyntheticWorkbenchSession
from tests.test_ingestion_v2_workbench_session import synthetic_pdf_bytes


def test_source_only_intake_uses_concise_ids_preserves_chapter_title_and_blocks_promotion(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path)
    session.start_pdf_run(synthetic_pdf_bytes([
        "Chapter 1: Pediatrics", "1. Which finding?", "A. First", "B. Second", "ANS: A", "Rationale."
    ]))
    payload = session.materialize_source_only("peds")
    assert payload["run"]["state"] == "review_ready"
    assert session.questions[0].question_id == "PFQ-pediatrics-000000001"
    assert session.questions[0].chapter_title == "Pediatrics"
    candidate = session.build_isolated_candidate()["candidate"]
    assert candidate["promotion_ready"] is False
    assert "source_only_candidate_requires_explicit_pack_creation" in candidate["blocking_reasons"]


def test_zero_parsed_records_is_a_document_blocker_not_a_successful_run(tmp_path) -> None:
    session = SyntheticWorkbenchSession(workspace_root=tmp_path)
    payload = session.start_pdf_run(synthetic_pdf_bytes(["This PDF has no question shapes."]))
    assert payload["run"]["state"] == "failed"
    assert payload["pipeline"]["document_findings"][0]["damage_type"] == "zero_parsed_records"
