from pathlib import Path
import hashlib
import json

import ingestion_v2.workbench_server as workbench_server
from ingestion_v2.workbench_server import approved_pdf_sources, filename_metadata, validated_existing_extraction


WORKBENCH = Path("ingestion_v2/workbench")


def test_workbench_discovers_every_valid_installed_pack(tmp_path, monkeypatch) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "adult-health.prepflow.json").write_text(json.dumps({
        "format": "prepflow_pack", "version": "1.0", "pack_id": "adult_health",
        "title": "Adult Health", "questions": [{
            "id": "PFQ-adult_health-000000001", "chapter": 1,
            "chapter_title": "One", "type": "multiple_choice", "stem": "Which?",
            "choices": [{"label": "A", "text": "First"}],
            "correct_answers": ["A"], "rationale": "Because.",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(workbench_server, "PACK_DIRECTORY", packs)

    assert workbench_server.installed_identity_packs() == {
        "adult_health": packs / "adult-health.prepflow.json"
    }


def test_workbench_is_private_synthetic_preview_with_no_promotion_action() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    data = (WORKBENCH / "demo-data.js").read_text(encoding="utf-8")

    assert "Synthetic preview · no writes" in html
    assert 'id="local-status"' in html
    assert "LOCAL ONLY" in html
    assert "Not synced to GitHub" in html
    assert "Source PDF is not committed" in html
    assert "Canonical Pack has not been replaced or promoted" in html
    assert "Publication is separate" in html
    assert "promote_canonical: false" in data
    assert "promote(" not in script
    assert 'fetch("/api/review"' in script
    assert '"/api/actions"' in script
    assert '"/api/dispositions"' in script
    assert 'fetch("/api/candidate"' in script
    assert "Building new v2 Pack…" in script
    assert "candidateBuildInFlight" in script
    assert 'fetch("/api/comparison"' in script
    assert "localStorage" not in script
    assert 'id="record-locator-details"' in html
    assert 'id="record-locator-query"' in html
    assert "INTERNAL RECORD LOCATOR" in html and "Advanced diagnostics" in html
    assert "REPAIR DESK" not in html and "Locate a stable question ID" not in html
    assert "/api/repair-desk?q=" in script
    assert '"Repair this question"' not in script
    assert "openManualPackEditor" not in script
    assert 'fetch("/api/repair-desk/replace"' not in script
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert 'parsed.path == "/api/repair-desk/question"' in server
    assert 'self.path == "/api/repair-desk/replace"' in server
    assert '"/api/repair-publish/status"' in Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert 'self.path == "/api/repair-publish"' in Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert 'replace_canonical_pack_question' in Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert "installed_pack_registry" in Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert "question" in script
    assert "renderLocalStatus" in script
    assert 'id="candidate-inspection"' in html
    assert '"/api/candidate/inspection"' in script
    assert "ArrowLeft" in script


def test_workbench_exposes_required_review_information_and_actions() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")

    for required_id in (
        "question-meta",
        "finding-explanation",
        "preserved-value",
        "proposed-value",
        "verification-card",
        "actions",
        "candidate-button",
        "comparison-button",
        "comparison-changes",
        "start-run-button",
        "resume-run-button",
        "factory-home",
        "approved-pdf-select",
        "selected-pdf-name",
        "process-book-button",
        "completed-runs",
        "complete-run-button",
        "cleanup-run-button",
        "run-cleaning",
        "run-extraction",
        "run-identity",
        "run-qa",
        "run-proposals",
        "materialize-identity-button",
    ):
        assert f'id="{required_id}"' in html
    for action in ("approve", "reject", "defer", "leave_blocked", "exclude_record"):
        assert action in script
    assert "Broken parsed answer" in script
    assert "Corrected answer" in script
    assert "answer_choice_context" in script
    assert "Broken candidate value" in script
    assert "Existing Pack reference" in script
    assert "Candidate correct answer" in script
    assert "Approve exact group correction" in script
    assert '"/api/comparison/groups/approve"' in script
    assert "review_categories" in script
    assert "comparison-category-card" in script
    assert '"/api/comparison/categories/source-page"' in script
    assert '"/api/comparison/categories/approve"' in script
    assert "Accept full source title" in script
    assert "Use clean reference value" in script
    assert '"/api/run/start"' in script
    assert '"/api/run/complete"' in script
    assert '"/api/run/start-pdf"' in script
    assert '"/api/run/resume"' in script
    assert '"/api/runs"' in script
    assert "The public study app does not use this engine" in html
    assert '"/api/run/cleanup"' in script
    assert '"/api/run/start-approved-pdf"' in script
    assert "FormData" not in script
    assert ".name" not in script


def test_workbench_keeps_legacy_identity_routes_outside_normal_intake() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")

    assert 'id="approved-pdf-select"' in html
    assert 'id="process-book-button"' in html
    assert "Comparison Pack" not in html
    assert "Start synthetic run" in html
    assert 'id="start-run-button" type="button" hidden' in html
    assert '"/api/private-sources"' in script
    assert '"/api/run/start-approved-pdf"' in script
    assert "/api/identity/existing-pack" in script
    assert "installed_identity_packs" in server
    assert "Unknown protected Pack selection" in server
    assert "/api/identity/actions" in script
    assert "Same question" in script
    assert "Accept new question" in script
    assert "Exclude source artifact" in script
    assert "Exclude duplicate" in script
    assert "Decide later" in script
    assert 'unresolvedIdentity.find((entry) => entry.record_id === selectedIdentityRecordId)' in script
    assert '|| unresolvedIdentity[0]' in script
    assert '["pending", "defer"].includes(entry.status)' in script
    assert "Old Pack reference only" in script
    assert "identity-target-preview" in script
    assert "selected?.target_stem" in script
    assert "/api/identity/materialize" in script
    assert "/api/identity/source-only" in script
    assert "SOURCE_ONLY_PRESETS" in server
    assert "Registered source metadata cannot be changed" in server
    assert "Prepare review" in html
    assert 'id="proposal-dialog"' in html
    assert 'id="proposal-value"' in html
    assert "/api/proposals" in script
    assert "Save fix" in html
    assert "Source context is optional" in html
    assert "Open temporary source page" in script
    assert 'id="view-source-button"' in html
    assert 'id="source-dialog"' in html
    assert "/api/source-page" in script
    assert "TEMPORARY PRIVATE SOURCE VIEW" in html


def test_approved_pdf_intake_reports_progress_and_never_leaves_duplicate_clicks_enabled() -> None:
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")

    for state in ("Starting…", "Using existing extraction…", "Cleaning…", "Checking questions…", "Ready for review"):
        assert state in script
    assert 'button.disabled = true; button.textContent = "Starting…"' in script
    assert 'button.disabled = !sourceId' in script
    assert "Processing failed:" in script
    assert "existing_extraction_available" in server
    assert "temporary run was cleaned" in server


def test_grouped_review_keeps_source_context_available_with_effective_candidate_value() -> None:
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    session = Path("ingestion_v2/workbench_session.py").read_text(encoding="utf-8")

    assert 'add("Open source context"' in script
    assert "if (!dialog.open) dialog.show();" in script
    assert "Your corrected question · effective candidate value" in script
    assert "Return the existing verified previous/current/next source window" in session
    assert '"current" if index in page_indexes' in session


def test_complete_editor_refreshes_answer_controls_on_any_choice_edit() -> None:
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    session = Path("ingestion_v2/workbench_session.py").read_text(encoding="utf-8")

    assert 'addEventListener("input", () => renderAnswerEditor(type))' in script
    assert "completeEditorAnswers = new Set" in script
    assert "filter((label) => currentLabels.has(label))" in script
    assert "This review has no editable finding" not in session
    assert "operator_complete_question_correction" in session


def test_grouped_review_supports_explicit_accept_as_is_and_save_confirmation() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")

    assert ">Save fix<" in html
    assert "Save fix and next" not in html
    assert 'add("Accept as is"' in script
    assert '"/api/questions/accept-as-is"' in script
    assert "Accepted as is" in script
    assert "Saved correction" in script
    assert "def accept_question_as_is" in Path("ingestion_v2/workbench_session.py").read_text(encoding="utf-8")
    assert 'self.path == "/api/questions/accept-as-is"' in server


def test_duplicate_review_keeps_explicit_exclusion_available_after_acceptance() -> None:
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")

    assert 'add(`Exclude duplicate ${item.question_id}`' in script
    assert 'Keeps ${item.related_question.question_id}' in script
    assert 'takeDuplicateDisposition(item, "exclude_record", item.question_id)' in script
    assert 'const duplicateIssue = item.issues.find((issue) => issue.damage_type === "complete_duplicate_record")' in script
    assert 'takeDuplicateDisposition(duplicateCase, "exclude_record", item.question_id)' in script


def test_workbench_health_endpoint_is_content_free_and_loopback_bound() -> None:
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert 'parsed.path == "/api/health"' in server
    assert '"scope": "local_only"' in server
    assert 'ThreadingHTTPServer(("127.0.0.1", args.port)' in server
    assert 'self.send_header("Cache-Control", "no-store, max-age=0")' in server


def test_workbench_has_responsive_layout() -> None:
    css = (WORKBENCH / "workbench.css").read_text(encoding="utf-8")

    assert "@media (max-width: 850px)" in css
    assert "@media (max-width: 520px)" in css


def test_approved_private_pdf_listing_uses_opaque_ids_and_filename_metadata(tmp_path) -> None:
    source = tmp_path / "Pediatrics Sample.pdf"
    source.write_bytes(b"%PDF-test")

    listed = approved_pdf_sources(tmp_path)

    assert listed[0][2] == "Pediatrics Sample.pdf"
    assert str(tmp_path) not in listed[0][0]
    assert filename_metadata(listed[0][2])["slug"] == "pediatricssample"


def test_existing_ocr_artifact_is_reused_only_for_exact_source_identity(tmp_path, monkeypatch) -> None:
    source = tmp_path / "pediatrics.pdf"
    source.write_bytes(b"not a real PDF")

    assert validated_existing_extraction(source, "pediatrics.pdf") is None


def test_manual_pack_replacement_preserves_id_position_and_writes_backup(tmp_path) -> None:
    from ingestion_v2.workbench_server import replace_canonical_pack_question

    pack_path = tmp_path / "fundamentals.prepflow.json"
    backup_root = tmp_path / "backups"
    original = {
        "format": "prepflow_pack", "version": "1.0", "pack_id": "fundamentals",
        "title": "Fundamentals",
        "questions": [
            {
                "id": "PFQ-fundamentals-000000001", "chapter": 1,
                "chapter_title": "One", "type": "mc", "stem": "Before?",
                "choices": [{"label": "A", "text": "Old"}, {"label": "B", "text": "Other"}],
                "correct_answers": ["A"], "rationale": "Before rationale.",
            },
            {
                "id": "PFQ-fundamentals-000000002", "chapter": 1,
                "chapter_title": "One", "type": "mc", "stem": "Untouched?",
                "choices": [{"label": "A", "text": "Yes"}],
                "correct_answers": ["A"], "rationale": "Untouched rationale.",
            },
        ],
    }
    pack_path.write_text(json.dumps(original), encoding="utf-8")
    digest = hashlib.sha256(pack_path.read_bytes()).hexdigest()

    result = replace_canonical_pack_question(
        "PFQ-fundamentals-000000001",
        {
            "stem": "After?",
            "choices": [{"label": "A", "text": "New"}, {"label": "B", "text": "Other"}],
            "correct_answers": ["A"],
            "rationale": "After rationale.",
        },
        digest,
        registry={"fundamentals": pack_path},
        backup_root=backup_root,
        repair_log_path=tmp_path / "REPAIR_LOG.md",
    )

    updated = json.loads(pack_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in updated["questions"]] == [
        "PFQ-fundamentals-000000001", "PFQ-fundamentals-000000002"
    ]
    assert updated["questions"][0]["stem"] == "After?"
    assert updated["questions"][1] == original["questions"][1]
    assert result["question_count"] == 2
    backups = list(backup_root.glob("*.prepflow.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original
    log = (tmp_path / "REPAIR_LOG.md").read_text(encoding="utf-8")
    assert '"stem": "Before?"' in log
    assert '"stem": "After?"' in log
