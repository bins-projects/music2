import copy
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import ingestion_v2.workbench_server as workbench_server
from ingestion_v2.question_workbench import (
    needs_review_inventory,
    save_operation,
)


def question(question_id="PFQ-test-000000001", *, rationale="Because."):
    return {
        "id": question_id,
        "chapter": 1,
        "chapter_title": "One",
        "type": "multiple_choice",
        "stem": "Which answer?",
        "choices": [
            {"label": "A", "text": "One"},
            {"label": "B", "text": "Two"},
        ],
        "correct_answers": ["A"],
        "rationale": rationale,
    }


def pack(*questions):
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test",
        "title": "Test Pack",
        "questions": list(questions),
    }


def test_dynamic_inventory_does_not_mutate_pack_or_ledger(tmp_path):
    installed = pack(
        question(),
        question("PFQ-test-000000002", rationale=""),
    )
    before = copy.deepcopy(installed)
    ledger = tmp_path / "operations.json"

    findings = needs_review_inventory({"test": installed})

    assert installed == before
    assert not ledger.exists()
    assert len(findings) == 1
    assert findings[0] == {
        "pack_id": "test",
        "pack_title": "Test Pack",
        "question_id": "PFQ-test-000000002",
        "reference": "Test Pack • Ref 2",
        "chapter": 1,
        "chapter_title": "One",
        "type": "multiple_choice",
        "stem": "Which answer?",
        "validation_issue": "Question rationale is required",
        "operation_id": None,
        "operation_state": None,
    }


def test_review_states_are_derived_from_pack_and_existing_operations():
    invalid = question(rationale="")
    installed = {"test": pack(invalid)}

    unsaved = needs_review_inventory(installed)
    assert unsaved[0]["operation_state"] is None

    pending_operation = {
        "operation_id": "PFOP-pending",
        "operation_type": "repair",
        "state": "pending",
        "pack_id": "test",
        "question_id": invalid["id"],
    }
    pending = needs_review_inventory(installed, [pending_operation])
    assert (pending[0]["operation_id"], pending[0]["operation_state"]) == (
        "PFOP-pending",
        "pending",
    )

    publishing_operation = {
        **pending_operation,
        "operation_id": "PFOP-publishing",
        "state": "publishing",
    }
    publishing = needs_review_inventory(installed, [publishing_operation])
    assert publishing[0]["operation_state"] == "publishing"

    repaired = copy.deepcopy(invalid)
    repaired["rationale"] = "Now valid."
    assert needs_review_inventory({"test": pack(repaired)}, [pending_operation]) == []


def test_clicks_reuse_exact_browse_and_saved_repair_paths(tmp_path, monkeypatch):
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="focused browser dependency is unavailable").sync_playwright
    ledger = tmp_path / "operations.json"
    monkeypatch.setattr(workbench_server, "QUESTION_LEDGER_PATH", ledger)
    _, packs = workbench_server.installed_question_packs()
    installed = packs["fundamentals"]
    original = next(
        item for item in installed["questions"]
        if item["id"] == "PFQ-fundamentals-000000230"
    )
    draft = copy.deepcopy(original)
    draft["correct_answers"] = [draft["correct_answers"][0]]
    draft["stem"] = "Saved repair draft?"
    operation = save_operation(
        ledger,
        operation_type="repair",
        pack_id="fundamentals",
        pack=installed,
        question=draft,
        original_question=original,
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), workbench_server.WorkbenchHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium",
            )
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(
                f"http://127.0.0.1:{server.server_port}/questions/",
                wait_until="networkidle",
            )
            page.locator("#needs-review-count").wait_for()
            assert page.locator("#needs-review-count").inner_text() == "(95)"
            summaries = page.locator("#needs-review details summary").all_inner_texts()
            assert summaries == [
                "Fundamentals of Nursing — 5",
                "Medical-Surgical — 0",
                "Pediatrics — 1",
                "Pharm — 89",
            ]
            page.screenshot(path="/tmp/prepflow-needs-review-panel.png", full_page=True)

            pediatrics = page.locator("#needs-review details").filter(
                has_text="Pediatrics — 1"
            )
            pediatrics.locator("summary").click()
            pediatrics.locator(".result").click()
            page.locator("#record-view:not([hidden])").wait_for()
            assert "PFQ-pediatrics-000000335" in page.locator(
                "#browse-record-meta"
            ).inner_text()
            page.locator("#open-for-repair").click()
            assert page.locator("#question-id").inner_text() == (
                "PFQ-pediatrics-000000335"
            )

            fundamentals = page.locator("#needs-review details").filter(
                has_text="Fundamentals of Nursing — 5"
            )
            fundamentals.locator("summary").click()
            pending_row = fundamentals.locator(".result").filter(
                has_text=operation["question_id"]
            )
            assert "Saved — awaiting publication" in pending_row.inner_text()
            pending_row.click()
            page.locator("#stem").wait_for(state="visible")
            assert page.locator("#stem").input_value() == "Saved repair draft?"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
