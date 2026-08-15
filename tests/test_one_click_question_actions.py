import copy
import json
from pathlib import Path

from ingestion_v2.one_click_question_actions import (
    apply_canonical_operation,
    discard_pending_operation,
    reconcile_saved_operations,
)
from ingestion_v2.prepflow_question_workbench_launcher import command
from ingestion_v2.question_workbench import load_ledger, save_operation
from tools.pack_catalog import write_catalog


def question(question_id="PFQ-test-000000001"):
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
        "rationale": "Because.",
        "rationale_source_status": "provided",
        "source_record_id": "SOURCE-1",
    }


def pack(*questions):
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test",
        "title": "Test",
        "questions": list(questions),
    }


def project(tmp_path: Path):
    root = tmp_path / "project"
    (root / "packs").mkdir(parents=True)
    (root / "web" / "data").mkdir(parents=True)
    (root / "docs").mkdir()
    installed = pack(question())
    pack_path = root / "packs" / "test.prepflow.json"
    pack_path.write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")
    write_catalog(root / "packs", root / "web" / "data" / "pack-catalog.json")
    return root, pack_path, installed


def test_canonical_repair_writes_pack_audit_backup_and_preserves_provenance(tmp_path):
    root, pack_path, installed = project(tmp_path)
    ledger = root / "output" / "question-workbench" / "operations.json"
    original = copy.deepcopy(installed["questions"][0])
    repaired = copy.deepcopy(original)
    repaired["stem"] = "Which answer is repaired?"
    operation = save_operation(
        ledger,
        operation_type="repair",
        pack_id="test",
        pack=installed,
        question=repaired,
        original_question=original,
    )

    applied = apply_canonical_operation(root, ledger, operation["operation_id"])

    assert applied["state"] == "applied"
    assert applied["publication"]["stage"] == "canonical_saved"
    saved = json.loads(pack_path.read_text(encoding="utf-8"))["questions"][0]
    assert saved["stem"] == "Which answer is repaired?"
    assert saved["rationale_source_status"] == "provided"
    assert saved["source_record_id"] == "SOURCE-1"
    assert (root / "docs" / "QUESTION_OPERATION_LOG.md").is_file()
    assert (root / applied["publication"]["backup"]).is_file()


def test_canonical_addition_gets_reserved_id_and_is_not_applied_twice(tmp_path):
    root, pack_path, installed = project(tmp_path)
    ledger = root / "output" / "question-workbench" / "operations.json"
    candidate = question("")
    candidate["stem"] = "Brand new?"
    operation = save_operation(
        ledger,
        operation_type="addition",
        pack_id="test",
        pack=installed,
        question=candidate,
    )

    first = apply_canonical_operation(root, ledger, operation["operation_id"])
    second = apply_canonical_operation(root, ledger, operation["operation_id"])
    saved = json.loads(pack_path.read_text(encoding="utf-8"))["questions"]

    assert first["question_id"] == "PFQ-test-000000002"
    assert second["state"] == "applied"
    assert [item["id"] for item in saved].count("PFQ-test-000000002") == 1


def test_discard_removes_only_pending_workbench_state(tmp_path):
    root, pack_path, installed = project(tmp_path)
    before = pack_path.read_bytes()
    ledger = root / "output" / "question-workbench" / "operations.json"
    operation = save_operation(
        ledger,
        operation_type="addition",
        pack_id="test",
        pack=installed,
        question=question(""),
    )

    removed = discard_pending_operation(ledger, operation["operation_id"])

    assert removed["operation_id"] == operation["operation_id"]
    assert load_ledger(ledger)["operations"] == []
    assert pack_path.read_bytes() == before


def test_reconciliation_removes_stale_repair_already_present_in_pack(tmp_path):
    root, pack_path, installed = project(tmp_path)
    ledger = root / "output" / "question-workbench" / "operations.json"
    original = copy.deepcopy(installed["questions"][0])
    repaired = copy.deepcopy(original)
    repaired["stem"] = "Already repaired elsewhere?"
    operation = save_operation(
        ledger,
        operation_type="repair",
        pack_id="test",
        pack=installed,
        question=repaired,
        original_question=original,
    )
    already_clean = pack(repaired)
    pack_path.write_text(json.dumps(already_clean, indent=2) + "\n", encoding="utf-8")

    removed = reconcile_saved_operations(ledger, {"test": already_clean})

    assert removed == 1
    assert load_ledger(ledger)["operations"] == []
    assert operation["question_id"] == repaired["id"]


def test_launcher_uses_one_click_server(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    launch = command(repository, "127.0.0.1", 8765)
    assert "ingestion_v2.one_click_workbench_server" in launch
