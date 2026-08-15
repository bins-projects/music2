#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    path = ROOT / path
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch anchor not found in {path}: {old[:100]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"Patch anchor is not unique in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {path.relative_to(ROOT)}")


# 1) Durable deletion operations + retry-safe Pack application.
replace_once(
    "ingestion_v2/question_workbench.py",
    '''    if operation_type not in {"repair", "addition"}:\n        raise QuestionWorkbenchError("Operation must be a repair or addition")\n    with locked_ledger(ledger_path) as ledger:\n        existing = next((item for item in ledger["operations"] if item.get("operation_id") == operation_id), None)\n        if existing and existing.get("state") != "pending":\n            raise QuestionWorkbenchError("Publication has started; resume it without editing the reserved operation")\n        if operation_type == "addition":\n            stable_id = existing["question_id"] if existing else reserve_question_id(pack_id, pack, ledger)\n            question = {**question, "id": stable_id}\n        elif original_question is None:\n            raise QuestionWorkbenchError("A repair requires the complete original question")\n        else:\n            stable_id = str(original_question.get("id") or "")\n            question = {**question, "id": stable_id}\n        normalized = validate_question(question)\n''',
    '''    if operation_type not in {"repair", "addition", "deletion"}:\n        raise QuestionWorkbenchError("Operation must be a repair, addition, or deletion")\n    with locked_ledger(ledger_path) as ledger:\n        existing = next((item for item in ledger["operations"] if item.get("operation_id") == operation_id), None)\n        if existing and existing.get("state") != "pending":\n            raise QuestionWorkbenchError("Publication has started; resume it without editing the reserved operation")\n        if operation_type == "addition":\n            stable_id = existing["question_id"] if existing else reserve_question_id(pack_id, pack, ledger)\n            question = {**question, "id": stable_id}\n        elif operation_type == "deletion":\n            if existing:\n                stable_id = str(existing.get("question_id") or "")\n                original_question = copy.deepcopy(existing.get("original_question"))\n            else:\n                stable_id = str(question.get("id") or "")\n                matches = [\n                    copy.deepcopy(item) for item in pack.get("questions", [])\n                    if item.get("id") == stable_id\n                ]\n                if len(matches) != 1:\n                    raise QuestionWorkbenchError("Deletion target is missing or duplicated")\n                original_question = matches[0]\n            if not isinstance(original_question, dict):\n                raise QuestionWorkbenchError("Deletion requires the complete original question")\n            question = copy.deepcopy(original_question)\n        elif original_question is None:\n            raise QuestionWorkbenchError("A repair requires the complete original question")\n        else:\n            stable_id = str(original_question.get("id") or "")\n            question = {**question, "id": stable_id}\n        normalized = validate_question(question)\n'''
)

replace_once(
    "ingestion_v2/question_workbench.py",
    '''    if operation["operation_type"] == "repair":\n        if len(matches) != 1:\n            raise QuestionWorkbenchError("Repair target is missing or duplicated")\n        original = operation.get("original_question")\n        if not isinstance(original, dict) or updated["questions"][matches[0]] != original:\n            raise QuestionWorkbenchError("Repair target changed after it was saved")\n        replacement = copy.deepcopy(original)\n        for field in ("chapter", "chapter_title", "type", "stem", "choices", "correct_answers", "rationale", "notes", "metadata"):\n            if field in question:\n                replacement[field] = copy.deepcopy(question[field])\n        replacement["id"] = operation["question_id"]\n        updated["questions"][matches[0]] = validate_question(replacement)\n    else:\n        if matches:\n            raise QuestionWorkbenchError("Reserved question ID already exists in the Pack")\n        updated["questions"].append(question)\n''',
    '''    if operation["operation_type"] == "repair":\n        if len(matches) != 1:\n            raise QuestionWorkbenchError("Repair target is missing or duplicated")\n        original = operation.get("original_question")\n        if not isinstance(original, dict) or updated["questions"][matches[0]] != original:\n            raise QuestionWorkbenchError("Repair target changed after it was saved")\n        replacement = copy.deepcopy(original)\n        for field in ("chapter", "chapter_title", "type", "stem", "choices", "correct_answers", "rationale", "notes", "metadata"):\n            if field in question:\n                replacement[field] = copy.deepcopy(question[field])\n        replacement["id"] = operation["question_id"]\n        updated["questions"][matches[0]] = validate_question(replacement)\n    elif operation["operation_type"] == "deletion":\n        original = operation.get("original_question")\n        if not isinstance(original, dict):\n            raise QuestionWorkbenchError("Deletion requires the complete original question")\n        if len(matches) == 1:\n            if updated["questions"][matches[0]] != original:\n                raise QuestionWorkbenchError("Deletion target changed after it was saved")\n            del updated["questions"][matches[0]]\n        elif len(matches) == 0 and (operation.get("publication") or {}).get("stage") == "applying_private":\n            # A process may die after the atomic Pack write but before the private commit.\n            # In that recovery state the deletion is already applied, so retry is a no-op.\n            pass\n        else:\n            raise QuestionWorkbenchError("Deletion target is missing or duplicated")\n    else:\n        if matches:\n            raise QuestionWorkbenchError("Reserved question ID already exists in the Pack")\n        updated["questions"].append(question)\n'''
)

# 2) Publication messages/commits know about deletion as a first-class operation.
replace_once(
    "ingestion_v2/question_publisher.py",
    '''            verb = "Repair" if operation["operation_type"] == "repair" else "Add"\n            git(project_root, "commit", "-m", f"{verb} question {operation['question_id']}")\n''',
    '''            verb = {"repair": "Repair", "addition": "Add", "deletion": "Delete"}[operation["operation_type"]]\n            git(project_root, "commit", "-m", f"{verb} question {operation['question_id']}")\n'''
)
replace_once(
    "ingestion_v2/question_publisher.py",
    '''            verb = "Repaired" if operation["operation_type"] == "repair" else "Added"\n            git(public_worktree, "commit", "-m", f"{verb} {operation['question_id']}")\n''',
    '''            verb = {"repair": "Repaired", "addition": "Added", "deletion": "Deleted"}[operation["operation_type"]]\n            git(public_worktree, "commit", "-m", f"{verb} {operation['question_id']}")\n'''
)

# 3) UI: explicit Delete control + persistent operator feedback.
replace_once(
    "ingestion_v2/question_workbench_ui/index.html",
    '''      <form id="search-form"><label>Search or browse questions<input id="search" type="search" placeholder="Stem text, Ref number, or full PFQ ID"></label><button>Search / Browse</button></form>\n      <div id="search-results" class="results" aria-live="polite"></div>\n''',
    '''      <form id="search-form"><label>Search or browse questions<input id="search" type="search" placeholder="Stem text, Ref number, or full PFQ ID"></label><button>Search / Browse</button></form>\n      <p id="operation-feedback" class="message" aria-live="polite"></p>\n      <div id="search-results" class="results" aria-live="polite"></div>\n'''
)
replace_once(
    "ingestion_v2/question_workbench_ui/index.html",
    '''      <div class="editor-actions"><button id="open-for-repair" type="button">Open this question for repair</button></div>\n''',
    '''      <div class="editor-actions"><button id="open-for-repair" type="button">Open this question for repair</button><button id="delete-question" type="button" class="secondary">Delete question</button></div>\n'''
)
replace_once(
    "ingestion_v2/question_workbench_ui/index.html",
    '''    <section class="panel"><div class="row"><div><p class="eyebrow">SAVED OPERATIONS</p><h2>Pending repairs and additions</h2></div><button id="refresh" type="button" class="secondary">Refresh</button></div><div id="pending" class="pending"></div></section>\n''',
    '''    <section class="panel"><div class="row"><div><p class="eyebrow">SAVED OPERATIONS</p><h2>Pending question changes</h2></div><button id="refresh" type="button" class="secondary">Refresh</button></div><div id="pending" class="pending"></div></section>\n'''
)

replace_once(
    "ingestion_v2/question_workbench_ui/questions.js",
    '''  function openCurrentForRepair(){\n    const question=browseState.currentQuestion;if(!question)return;\n    mode="repair";$("type").value=question.type||question.question_type;$("record-view").hidden=true;openEditor(question,question);\n  }\n''',
    '''  function openCurrentForRepair(){\n    const question=browseState.currentQuestion;if(!question)return;\n    mode="repair";$("type").value=question.type||question.question_type;$("record-view").hidden=true;openEditor(question,question);\n  }\n  async function deleteCurrentQuestion(){\n    const question=browseState.currentQuestion;if(!question)return;\n    const snippet=String(question.stem||"").replace(/\\s+/g," ").trim().slice(0,160);\n    const confirmed=window.confirm(`Delete ${question.id}?\\n\\n${snippet}${String(question.stem||"").length>160?"…":""}\\n\\nThis removes exactly this question from the canonical Pack when publication runs.`);\n    if(!confirmed)return;\n    const button=$("delete-question"),feedback=$("operation-feedback");button.disabled=true;button.textContent="Deleting…";feedback.textContent="";\n    try{\n      const response=await json("/api/question-workbench/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_type:"deletion",pack_id:$("pack").value,question})});\n      showReadiness(response.readiness);\n      const published=response.operation.state==="published";\n      feedback.textContent=published?`Deleted and published everywhere — ${question.id}`:`Deletion saved — publication pending for ${question.id}. The installed question remains until publication succeeds.`;\n      feedback.className="message ok";\n      $("record-view").hidden=true;browseState.currentQuestion=null;browseState.currentIndex=-1;\n      await reload();fillSelectors();await browseQuestions(browseState.page,false);\n    }catch(error){feedback.textContent=`Delete failed — ${error.message}`;feedback.className="message";button.disabled=false;button.textContent="Delete question";}\n  }\n'''
)

replace_once(
    "ingestion_v2/question_workbench_ui/questions.js",
    '''  function renderPending(){const target=$("pending");target.replaceChildren();if(!data.operations.length){target.textContent="No saved operations.";return;}data.operations.slice().reverse().forEach((op)=>{const card=document.createElement("article");card.className=`pending-card ${op.state==="published"?"published":""}`;card.innerHTML=`<div><strong>${op.operation_type==="repair"?"Repair":"Addition"} · ${escapeHtml(op.question_id)}</strong><p>${escapeHtml(op.question.stem.slice(0,120))}</p><small>${escapeHtml(op.pack_id)} · Chapter ${escapeHtml(op.question.chapter)} · ${escapeHtml(op.question.type)} · saved ${escapeHtml(op.updated_at)}${op.blocker?` · ${escapeHtml(op.blocker)}`:""}</small></div>`;const actions=document.createElement("div");actions.className="pending-actions";const edit=document.createElement("button");edit.className="secondary";edit.textContent=op.state==="published"?"Published":op.state==="publishing"?"Publication recovery pending":"Reopen and edit";edit.disabled=op.state!=="pending";edit.onclick=()=>reopen(op);actions.append(edit);if(op.state!=="published"&&(data.readiness.ready||op.state==="publishing")){const publish=document.createElement("button");publish.textContent=op.state==="publishing"?"Resume publication":op.operation_type==="repair"?"Replace question & publish":"Add question & publish";publish.onclick=()=>publishPending(op,publish);actions.append(publish);}card.append(actions);target.append(card);});}\n''',
    '''  function renderPending(){const target=$("pending");target.replaceChildren();const operations=data.operations.filter((op)=>op.state!=="published");if(!operations.length){target.textContent="No pending operations.";return;}operations.slice().reverse().forEach((op)=>{const card=document.createElement("article");card.className="pending-card";const label=op.operation_type==="repair"?"Repair":op.operation_type==="deletion"?"Deletion":"Addition";card.innerHTML=`<div><strong>${label} · ${escapeHtml(op.question_id)}</strong><p>${escapeHtml(op.question.stem.slice(0,120))}</p><small>${escapeHtml(op.pack_id)} · Chapter ${escapeHtml(op.question.chapter)} · ${escapeHtml(op.question.type)} · saved ${escapeHtml(op.updated_at)}${op.blocker?` · ${escapeHtml(op.blocker)}`:""}</small></div>`;const actions=document.createElement("div");actions.className="pending-actions";const edit=document.createElement("button");edit.className="secondary";edit.textContent=op.operation_type==="deletion"?"Deletion saved":op.state==="publishing"?"Publication recovery pending":"Reopen and edit";edit.disabled=op.operation_type==="deletion"||op.state!=="pending";if(op.operation_type!=="deletion")edit.onclick=()=>reopen(op);actions.append(edit);if(data.readiness.ready||op.state==="publishing"){const publish=document.createElement("button");publish.textContent=op.state==="publishing"?"Resume publication":op.operation_type==="repair"?"Replace question & publish":op.operation_type==="deletion"?"Delete question & publish":"Add question & publish";publish.onclick=()=>publishPending(op,publish);actions.append(publish);}card.append(actions);target.append(card);});}\n'''
)

replace_once(
    "ingestion_v2/question_workbench_ui/questions.js",
    '''  async function publishPending(op,button){button.disabled=true;button.textContent="Publishing…";try{const response=await json("/api/question-workbench/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_id:op.operation_id})});showReadiness(response.readiness);await reload();}catch(error){button.disabled=false;button.textContent="Try publication again";alert(error.message);}}\n''',
    '''  async function publishPending(op,button){button.disabled=true;button.textContent="Publishing…";const feedback=$("operation-feedback");try{const response=await json("/api/question-workbench/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_id:op.operation_id})});showReadiness(response.readiness);feedback.textContent=op.operation_type==="deletion"?`Deleted and published everywhere — ${op.question_id}`:`Published everywhere — ${op.question_id}`;feedback.className="message ok";await reload();if(op.operation_type==="deletion"){fillSelectors();browseState.currentQuestion=null;browseState.currentIndex=-1;await browseQuestions(browseState.page,false);}}catch(error){button.disabled=false;button.textContent="Try publication again";feedback.textContent=`Publication pending — ${error.message}`;feedback.className="message";}}\n'''
)

replace_once(
    "ingestion_v2/question_workbench_ui/questions.js",
    '''  $("back-to-results").onclick=backToResults;$("previous-question").onclick=()=>void stepQuestion(-1);$("next-question").onclick=()=>void stepQuestion(1);$("open-for-repair").onclick=openCurrentForRepair;\n''',
    '''  $("back-to-results").onclick=backToResults;$("previous-question").onclick=()=>void stepQuestion(-1);$("next-question").onclick=()=>void stepQuestion(1);$("open-for-repair").onclick=openCurrentForRepair;$("delete-question").onclick=()=>void deleteCurrentQuestion();\n'''
)

# 4) Tests: make the new confirmation intentional, and add deletion/idempotency coverage.
replace_once(
    "tests/test_question_workbench.py",
    '''    assert "window.confirm" not in script and "Check readiness" not in html\n''',
    '''    assert "window.confirm" in script and "Delete question" in html and "Check readiness" not in html\n'''
)
replace_once(
    "tests/test_question_workbench.py",
    '''    for text in ("Back to results", "Previous question", "Next question", "Open this question for repair"):\n        assert text in html\n''',
    '''    for text in ("Back to results", "Previous question", "Next question", "Open this question for repair", "Delete question"):\n        assert text in html\n'''
)

anchor = '''\ndef test_dirty_public_worktree_is_never_discarded(tmp_path):\n'''
addition = r'''

def test_deletion_operation_removes_exact_question_and_retry_cannot_touch_neighbor(tmp_path):
    target = question("mc", "PFQ-test-000000001")
    neighbor = question("mc", "PFQ-test-000000002")
    neighbor["stem"] = "Neighbor question?"
    installed = pack(target, neighbor)
    operation = save_operation(
        tmp_path / "ledger.json", operation_type="deletion", pack_id="test",
        pack=installed, question=target,
    )
    assert operation["original_question"] == target
    assert operation["question_id"] == target["id"]

    deleted = apply_operation_to_pack(operation, installed)
    assert [item["id"] for item in deleted["questions"]] == [neighbor["id"]]

    recovering = copy.deepcopy(operation)
    recovering["publication"] = {"stage": "applying_private"}
    retried = apply_operation_to_pack(recovering, deleted)
    assert retried == deleted
    assert retried["questions"][0] == neighbor

    with pytest.raises(QuestionWorkbenchError, match="Deletion target is missing"):
        apply_operation_to_pack(operation, deleted)


def test_deletion_publication_removes_exact_question_from_private_and_public(tmp_path):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    target = question("mc", "PFQ-test-000000001")
    neighbor = question("mc", "PFQ-test-000000002")
    neighbor["stem"] = "Neighbor question?"
    installed = pack(target, neighbor)
    (private / "packs" / "test.prepflow.json").write_text(json.dumps(installed, indent=2) + "\n")
    write_catalog(private / "packs", private / "web" / "data" / "pack-catalog.json")
    commit(private, "Add neighbor")
    run(private, "push", "origin", "master")
    run(private, "push", "public", "master")

    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    operation = save_operation(
        ledger, operation_type="deletion", pack_id="test", pack=installed, question=target,
    )
    result = publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    assert result["stage"] == "published"
    for root in (private, public):
        published = json.loads((root / "packs" / "test.prepflow.json").read_text())
        assert [item["id"] for item in published["questions"]] == [neighbor["id"]]
        assert published["questions"][0]["stem"] == "Neighbor question?"


def test_deletion_private_push_retry_does_not_delete_neighbor(tmp_path, monkeypatch):
    private_remote = tmp_path / "prepflow-dev.git"; public_remote = tmp_path / "PrepFlow.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; initialize_repository(private, private_remote, public_remote)
    target = question("mc", "PFQ-test-000000001")
    neighbor = question("mc", "PFQ-test-000000002"); neighbor["stem"] = "Neighbor question?"
    installed = pack(target, neighbor)
    (private / "packs" / "test.prepflow.json").write_text(json.dumps(installed, indent=2) + "\n")
    write_catalog(private / "packs", private / "web" / "data" / "pack-catalog.json")
    commit(private, "Add neighbor")
    run(private, "push", "origin", "master"); run(private, "push", "public", "master")
    public = tmp_path / "public-release"; prepare_public_worktree(private, public)
    ledger = private / "output" / "question-workbench" / "operations.json"
    operation = save_operation(ledger, operation_type="deletion", pack_id="test", pack=installed, question=target)
    real_git = question_publisher.git; failed = False

    def interrupt_once(root, *args):
        nonlocal failed
        if Path(root).resolve() == private.resolve() and args[:2] == ("push", "origin") and not failed:
            failed = True
            raise RuntimeError("synthetic private deletion push interruption")
        return real_git(root, *args)

    monkeypatch.setattr(question_publisher, "git", interrupt_once)
    with pytest.raises(RuntimeError, match="synthetic private deletion push interruption"):
        publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    interrupted = load_ledger(ledger)["operations"][0]
    assert interrupted["publication"]["stage"] == "private_committed"
    private_after_first = json.loads((private / "packs" / "test.prepflow.json").read_text())
    assert [item["id"] for item in private_after_first["questions"]] == [neighbor["id"]]

    monkeypatch.setattr(question_publisher, "git", real_git)
    publish_saved_operation(private, public, ledger, operation["operation_id"], readiness={"ready": True})
    for root in (private, public):
        published = json.loads((root / "packs" / "test.prepflow.json").read_text())
        assert [item["id"] for item in published["questions"]] == [neighbor["id"]]
'''

test_path = ROOT / "tests/test_question_workbench.py"
text = test_path.read_text(encoding="utf-8")
if "test_deletion_operation_removes_exact_question_and_retry_cannot_touch_neighbor" not in text:
    if anchor not in text:
        raise SystemExit("Test insertion anchor not found")
    test_path.write_text(text.replace(anchor, addition + anchor, 1), encoding="utf-8")
    print("patched tests/test_question_workbench.py")

print("Delete Question workflow patch applied. No Pack data was changed.")
