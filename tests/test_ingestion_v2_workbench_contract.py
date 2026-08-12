from pathlib import Path


WORKBENCH = Path("ingestion_v2/workbench")


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
    assert "No canonical write available" in html
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
    assert 'id="repair-desk-query"' in html
    assert "/api/repair-desk?q=" in script
    assert "question" in script
    assert "renderLocalStatus" in script


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
        "new-run-button",
        "new-run-pack",
        "new-source-metadata",
        "new-source-name",
        "new-source-slug",
        "new-source-prefix",
        "new-source-preview",
        "completed-runs",
        "complete-run-button",
        "cleanup-run-button",
        "run-cleaning",
        "run-extraction",
        "run-identity",
        "run-qa",
        "run-proposals",
        "pdf-input",
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
    assert 'headers: { "Content-Type": "application/pdf" }' in script
    assert "FormData" not in script
    assert ".name" not in script


def test_workbench_exposes_guarded_existing_pack_identity_actions() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")

    assert 'data-pack-id="fundamentals"' in html
    assert 'data-pack-id="medical_surgical"' in html
    assert 'value="pharmacy"' in html
    assert 'value="peds"' in html
    assert 'value="new_source"' in html
    assert "/api/identity/existing-pack" in script
    assert "IDENTITY_PACKS" in server
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
    assert "sourceOnlyMetadata" in script
    assert "PFQ-${slug || \"slug\"}-000000001" in script
    assert "SOURCE_ONLY_PRESETS" in server
    assert "Registered source metadata cannot be changed" in server
    assert "Prepare parsed review" in html
    assert 'id="proposal-dialog"' in html
    assert 'id="proposal-value"' in html
    assert "/api/proposals" in script
    assert "Saving this draft does not approve or apply it" in html
    assert "Edit ordinary text directly" in html
    assert "Open temporary source page" in script
    assert 'id="view-source-button"' in html
    assert 'id="source-dialog"' in html
    assert "/api/source-page" in script
    assert "TEMPORARY PRIVATE SOURCE VIEW" in html


def test_workbench_health_endpoint_is_content_free_and_loopback_bound() -> None:
    server = Path("ingestion_v2/workbench_server.py").read_text(encoding="utf-8")
    assert 'parsed.path == "/api/health"' in server
    assert '"scope": "local_only"' in server
    assert 'ThreadingHTTPServer(("127.0.0.1", args.port)' in server


def test_workbench_has_responsive_layout() -> None:
    css = (WORKBENCH / "workbench.css").read_text(encoding="utf-8")

    assert "@media (max-width: 850px)" in css
    assert "@media (max-width: 520px)" in css
