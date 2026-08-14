import copy
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

import ingestion_v2.question_publisher as question_publisher
from ingestion_v2.prepflow_question_workbench_launcher import command
from ingestion_v2.question_publisher import prepare_public_worktree, publication_readiness, publish_saved_operation
from ingestion_v2.question_workbench import (
    QuestionWorkbenchError, apply_operation_to_pack, canonical_type_inventory, evaluate_answer,
    load_ledger, save_operation,
    TYPE_DEFINITIONS,
)
from ingestion_v2.workbench_server import WorkbenchHandler
from tools.pack_catalog import write_catalog


def question(kind="multiple_choice", question_id="PFQ-test-000000001"):
    value = {"id": question_id, "chapter": 1, "chapter_title": "One", "type": kind,
             "stem": "Which answer?", "choices": [{"label": "A", "text": "One"}, {"label": "B", "text": "Two"}],
             "correct_answers": ["A"], "rationale": "Because.", "source_record_id": "SOURCE-1"}
    if kind == "multiple_response": value["correct_answers"] = ["A", "B"]
    if kind == "completion": value.update(choices=[], correct_answers=["Communication", "communication process"])
    if kind == "ordered_response": value["correct_answers"] = ["B", "A"]
    return value


def pack(*questions):
    return {"format": "prepflow_pack", "version": "1.0", "pack_id": "test", "title": "Test", "questions": list(questions)}


def run(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def commit(root, message):
    run(root, "add", ".")
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", message], cwd=root, check=True, capture_output=True)


def test_inventory_reports_all_installed_stored_values():
    packs = {}
    for path in Path("packs").glob("*.prepflow.json"):
        payload = json.loads(path.read_text()); packs[payload["pack_id"]] = payload
    inventory = {item["stored_type"]: item for item in canonical_type_inventory(packs)}
    assert set(inventory) == {"mc", "multiple_choice", "multiple_response", "completion", "ordered_response"}
    assert all(item["supported"] for item in inventory.values())


@pytest.mark.parametrize("kind,correct,wrong", [
    ("mc", ["A"], ["B"]), ("multiple_choice", ["A"], ["B"]), ("multiple_response", ["B", "A"], ["A"]),
    ("completion", " communication ", "communications"), ("ordered_response", ["B", "A"], ["A", "B"]),
])
def test_authoring_and_runtime_grading_for_every_behavior(tmp_path, kind, correct, wrong):
    operation = save_operation(tmp_path / "ledger.json", operation_type="addition", pack_id="test",
                               pack=pack(question()), question=question(kind, ""))
    assert evaluate_answer(operation["question"], correct)["is_correct"] is True
    assert evaluate_answer(operation["question"], wrong)["is_correct"] is False


def test_mc_aliases_share_the_same_single_choice_definition():
    assert TYPE_DEFINITIONS["mc"] == TYPE_DEFINITIONS["multiple_choice"]


def test_completion_accepts_alternate_case_and_whitespace_only(tmp_path):
    operation = save_operation(tmp_path / "ledger.json", operation_type="addition", pack_id="test",
                               pack=pack(question()), question=question("completion", ""))
    assert evaluate_answer(operation["question"], " COMMUNICATION PROCESS ")["is_correct"]
    assert not evaluate_answer(operation["question"], "Communication processes")["is_correct"]


def test_ordered_response_rejects_missing_duplicate_and_unknown_items(tmp_path):
    for answers in (["A"], ["A", "A"], ["A", "C"]):
        candidate = question("ordered_response", ""); candidate["correct_answers"] = answers
        with pytest.raises(QuestionWorkbenchError):
            save_operation(tmp_path / f"{len(answers)}-{answers[-1]}.json", operation_type="addition",
                           pack_id="test", pack=pack(question()), question=candidate)


def test_atomic_reservations_are_unique_and_never_reused(tmp_path):
    ledger = tmp_path / "ledger.json"; installed = pack(question())
    def reserve(index):
        candidate = question("multiple_choice", ""); candidate["stem"] = f"Question {index}?"
        return save_operation(ledger, operation_type="addition", pack_id="test", pack=installed, question=candidate)["question_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(reserve, range(12)))
    assert len(ids) == len(set(ids)) == 12
    assert min(int(value.rsplit("-", 1)[1]) for value in ids) == 2
    assert len(load_ledger(ledger)["operations"]) == 12


def test_pending_addition_edit_and_chapter_reassignment_preserve_id(tmp_path):
    ledger = tmp_path / "ledger.json"; installed = pack(question())
    first = save_operation(ledger, operation_type="addition", pack_id="test", pack=installed, question=question("multiple_choice", ""))
    edited = copy.deepcopy(first["question"]); edited.update(chapter=2, chapter_title="Two", stem="Edited?")
    second = save_operation(ledger, operation_type="addition", pack_id="test", pack=installed, question=edited, operation_id=first["operation_id"])
    assert second["question_id"] == first["question_id"]
    assert second["question"]["chapter"] == 2


@pytest.mark.parametrize("stored_type", ["mc", "multiple_choice"])
def test_repair_changes_only_approved_fields_and_preserves_id_metadata(tmp_path, stored_type):
    original = question(stored_type); original["metadata"] = {"generation": "installed"}
    installed = pack(original); replacement = copy.deepcopy(original); replacement["stem"] = "Repaired?"
    operation = save_operation(tmp_path / "ledger.json", operation_type="repair", pack_id="test", pack=installed,
                               question=replacement, original_question=original)
    updated = apply_operation_to_pack(operation, installed)["questions"][0]
    assert updated["id"] == original["id"] and updated["source_record_id"] == "SOURCE-1"
    assert updated["type"] == stored_type
    assert {key: value for key, value in updated.items() if key != "stem"} == {
        key: value for key, value in original.items() if key != "stem"
    }
    assert updated["stem"] == "Repaired?"


def initialize_repository(root, remote, public_remote=None):
    root.mkdir(); run(root, "init", "-b", "master")
    (root / "packs").mkdir(); (root / "web" / "data").mkdir(parents=True); (root / "docs").mkdir()
    (root / "packs" / "test.prepflow.json").write_text(json.dumps(pack(question()), indent=2) + "\n")
    write_catalog(root / "packs", root / "web" / "data" / "pack-catalog.json")
    commit(root, "Initial")
    run(root, "remote", "add", "origin", str(remote)); run(root, "push", "origin", "master")
    if public_remote:
        run(root, "remote", "add", "public", str(public_remote)); run(root, "push", "public", "master")


def test_launcher_prepares_public_worktree_and_readiness_maps_two_states(tmp_path):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    subprocess.run(["git", "init", "--bare", private_remote], check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", public_remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    public = tmp_path / "public-release"; prepared = prepare_public_worktree(private, public)
    assert Path(prepared["path"]) == public
    ready = publication_readiness(private, public)
    assert ready["operator_state"] == "Publishable" and ready["ready"]
    (private / "packs" / "test.prepflow.json").write_text("changed")
    blocked = publication_readiness(private, public)
    assert blocked["operator_state"] == "Publishing unavailable — will save"
    assert blocked["reason"] == "Repository contains unrelated changes"


def test_fake_remote_addition_publication_preserves_id_bytes_and_metadata(tmp_path):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote): subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    candidate = question("ordered_response", ""); candidate.update(chapter=1, chapter_title="One")
    operation = save_operation(ledger, operation_type="addition", pack_id="test", pack=pack(question()), question=candidate)
    result = publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    assert result["private_commit"] == run(private_remote, "rev-parse", "master")
    assert result["public_commit"] == run(public_remote, "rev-parse", "master")
    assert (private / "packs" / "test.prepflow.json").read_bytes() == (public / "packs" / "test.prepflow.json").read_bytes()
    published = json.loads((public / "packs" / "test.prepflow.json").read_text())["questions"][-1]
    assert published["id"] == operation["question_id"] and published["correct_answers"] == ["B", "A"]
    assert (private / "docs" / "QUESTION_OPERATION_LOG.md").is_file()


@pytest.mark.parametrize("stored_type", ["mc", "multiple_choice"])
def test_both_mc_aliases_publish_without_rewriting(tmp_path, stored_type):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    candidate = question(stored_type, "")
    operation = save_operation(ledger, operation_type="addition", pack_id="test",
                               pack=pack(question()), question=candidate)
    publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    for root in (private, public):
        published = json.loads((root / "packs" / "test.prepflow.json").read_text())
        saved = next(item for item in published["questions"] if item["id"] == operation["question_id"])
        assert saved["type"] == stored_type



def test_public_push_interruption_resumes_without_duplicate_question(tmp_path, monkeypatch):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    operation = save_operation(ledger, operation_type="addition", pack_id="test", pack=pack(question()),
                               question=question("multiple_choice", ""))
    real_git = question_publisher.git
    failed = False
    def interrupt_once(root, *args):
        nonlocal failed
        if Path(root).resolve() == public.resolve() and args[:2] == ("push", "public") and not failed:
            failed = True
            raise RuntimeError("synthetic public push interruption")
        return real_git(root, *args)
    monkeypatch.setattr(question_publisher, "git", interrupt_once)
    with pytest.raises(RuntimeError, match="synthetic public push interruption"):
        publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    interrupted = load_ledger(ledger)["operations"][0]
    assert interrupted["state"] == "publishing"
    assert interrupted["publication"]["stage"] == "public_committed"
    monkeypatch.setattr(question_publisher, "git", real_git)
    result = publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    assert result["public_commit"] == real_git(public_remote, "rev-parse", "master")
    published = json.loads((public / "packs" / "test.prepflow.json").read_text())
    assert [item["id"] for item in published["questions"]].count(operation["question_id"]) == 1
    assert int(real_git(public, "rev-list", "--count", "HEAD")) == 2
    assert int(real_git(private, "rev-list", "--count", "HEAD")) == 2


def test_private_push_interruption_resumes_without_duplicate_question_or_commit(tmp_path, monkeypatch):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    operation = save_operation(ledger, operation_type="addition", pack_id="test", pack=pack(question()),
                               question=question("mc", ""))
    real_git = question_publisher.git
    failed = False

    def interrupt_once(root, *args):
        nonlocal failed
        if Path(root).resolve() == private.resolve() and args[:2] == ("push", "origin") and not failed:
            failed = True
            raise RuntimeError("synthetic private push interruption")
        return real_git(root, *args)

    monkeypatch.setattr(question_publisher, "git", interrupt_once)
    with pytest.raises(RuntimeError, match="synthetic private push interruption"):
        publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    interrupted = load_ledger(ledger)["operations"][0]
    assert interrupted["state"] == "publishing"
    assert interrupted["publication"]["stage"] == "private_committed"
    private_commit = interrupted["publication"]["private_commit"]

    monkeypatch.setattr(question_publisher, "git", real_git)
    result = publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    assert result["private_commit"] == private_commit
    assert int(real_git(private, "rev-list", "--count", "HEAD")) == 2
    assert int(real_git(public, "rev-list", "--count", "HEAD")) == 2
    for root in (private, public):
        published = json.loads((root / "packs" / "test.prepflow.json").read_text())
        assert [item["id"] for item in published["questions"]].count(operation["question_id"]) == 1


def test_dirty_public_worktree_is_never_discarded(tmp_path):
    remote = tmp_path / "PrepFlow.git"; private_remote = tmp_path / "prepflow-dev.git"
    for item in (remote, private_remote): subprocess.run(["git", "init", "--bare", item], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, remote)
    public = tmp_path / "public"; prepare_public_worktree(private, public)
    (public / "packs" / "test.prepflow.json").write_text("operator work")
    with pytest.raises(RuntimeError, match="unrelated changes"):
        prepare_public_worktree(private, public)
    assert (public / "packs" / "test.prepflow.json").read_text() == "operator work"


def test_unified_server_serves_both_stations_health_and_shared_pack_discovery():
    server = ThreadingHTTPServer(("127.0.0.1", 0), WorkbenchHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def get(path):
        with urlopen(base + path) as response:
            return response.status, response.headers, response.read()

    try:
        status, _, body = get("/api/health")
        health = json.loads(body)
        assert status == 200 and health["workbench"] == "unified"
        assert health["stations"] == {
            "ingestion_clean": {"available": True, "path": "/"},
            "repair_add_questions": {"available": True, "path": "/questions/"},
        }
        assert b"Build a new Pack" in get("/")[2]
        assert b"Repair &amp; Add Questions" in get("/")[2]
        assert b"Repair and add questions" in get("/questions/")[2]
        assert b"Back to Ingestion &amp; Clean" in get("/questions/")[2]
        assert b"function preferredType" in get("/questions/questions.js")[2]
        assert b"Repair and add questions" in get("/questions/")[2]

        ingestion_packs = json.loads(get("/api/pack-registry")[2])["packs"]
        question_packs = json.loads(get("/api/question-workbench")[2])["packs"]
        installed = {item["id"] for item in ingestion_packs if not item["source_only"]}
        assert installed == {item["id"] for item in question_packs}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_codespaces_starts_one_unified_server_on_one_forwarded_port():
    launch = command(Path.cwd(), "0.0.0.0", 8765)
    assert launch[-5:] == ["ingestion_v2.workbench_server", "--host", "0.0.0.0", "--port", "8765"]
    devcontainer = json.loads(Path(".devcontainer/devcontainer.json").read_text())
    assert devcontainer["postStartCommand"] == "bash .devcontainer/start-workbench.sh"
    assert devcontainer["forwardPorts"] == [8765]
    start = Path(".devcontainer/start-workbench.sh").read_text()
    assert "prepflow_question_workbench_launcher" in start
    assert '"workbench": "unified"' in start
    assert "8766" not in start


def test_ui_contract_has_two_states_final_actions_preview_and_mobile_layout():
    root = Path("ingestion_v2/question_workbench_ui")
    html = (root / "index.html").read_text(); script = (root / "questions.js").read_text(); css = (root / "questions.css").read_text()
    for text in ("Repair existing question", "Add new question", "SAVED OPERATIONS", "Interactive learner preview"):
        assert text.casefold() in html.casefold()
    publisher = Path("ingestion_v2/question_publisher.py").read_text()
    for text in ("Replace question & publish", "Add question & publish"):
        assert text in script
    assert "Publishable" in publisher and "Publishing unavailable — will save" in publisher
    assert "window.confirm" not in script and "Check readiness" not in html
    assert 'function preferredType(){ return "mc"; }' in script
    assert 'option.hidden=option.value==="multiple_choice"' in script
    assert "@media(max-width:760px)" in css
    assert ".header-actions" in css and ".station-nav" in css
    ingestion_html = Path("ingestion_v2/workbench/index.html").read_text()
    ingestion_css = Path("ingestion_v2/workbench/workbench.css").read_text()
    assert 'href="/questions/"' in ingestion_html and "Repair &amp; Add Questions" in ingestion_html
    assert ".topbar-actions" in ingestion_css and "@media (max-width: 520px)" in ingestion_css
