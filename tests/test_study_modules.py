import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "web/data/study-modules/combined-nursing-final-review.json"
PACK_PATHS = {
    "fundamentals": ROOT / "packs/fundamentals.prepflow.json",
    "medical_surgical": ROOT / "packs/medical_surgical.prepflow.json",
    "pharmacy": ROOT / "packs/pharmacy.prepflow.json",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def manifest() -> dict:
    return load_json(MANIFEST_PATH)


def references(data: dict) -> list[str]:
    return [
        question_id
        for group in data["groups"]
        for chapter in group["chapters"]
        for question_id in chapter["question_ids"]
    ]


def canonical_index() -> dict[str, list[tuple[str, dict]]]:
    index: dict[str, list[tuple[str, dict]]] = {}
    for pack_id, path in PACK_PATHS.items():
        for question in load_json(path)["questions"]:
            index.setdefault(question["id"], []).append((pack_id, question))
    return index


def test_manifest_identity_and_behavior_contract() -> None:
    data = manifest()
    assert data["format"] == "prepflow_module_selection"
    assert data["version"] == "1.0"
    assert data["title"] == "Combined Nursing Final Review"
    assert data["behavior"] == {
        "navigation": "subject_then_chapter",
        "delivery": "one_question_at_a_time",
        "scoring": "first_attempt_by_chapter",
        "shuffle": "once_per_chapter",
        "reuse_existing_quiz_engine": True,
    }


def test_manifest_has_expected_325_unique_questions() -> None:
    ids = references(manifest())
    assert len(ids) == 325
    assert len(set(ids)) == 325


def test_manifest_has_expected_39_chapter_sections() -> None:
    assert sum(len(group["chapters"]) for group in manifest()["groups"]) == 39


def test_subject_and_chapter_grouping() -> None:
    data = manifest()
    assert [group["subject"] for group in data["groups"]] == [
        "Fundamentals", "Medical-Surgical", "Pharmacology"
    ]
    assert [len(group["chapters"]) for group in data["groups"]] == [5, 21, 13]
    assert [sum(len(chapter["question_ids"]) for chapter in group["chapters"])
            for group in data["groups"]] == [50, 170, 105]


def test_each_chapter_expected_count_matches_its_references() -> None:
    for group in manifest()["groups"]:
        for chapter in group["chapters"]:
            assert chapter["expected_question_count"] == len(chapter["question_ids"])


def test_all_references_exist_exactly_once_in_canonical_packs() -> None:
    index = canonical_index()
    missing = [question_id for question_id in references(manifest()) if question_id not in index]
    duplicate_matches = [question_id for question_id, hits in index.items() if len(hits) != 1]
    assert missing == []
    assert duplicate_matches == []


def test_references_resolve_to_declared_pack_and_chapter() -> None:
    index = canonical_index()
    for group in manifest()["groups"]:
        for chapter in group["chapters"]:
            for question_id in chapter["question_ids"]:
                pack_id, question = index[question_id][0]
                assert pack_id == group["source_pack_id"]
                assert question["chapter"] == chapter["source_chapter"]
                assert question["chapter_title"] == chapter["title"]


def test_duplicate_reference_fixture_is_detectable() -> None:
    ids = references(manifest())
    duplicated = ids + [ids[0]]
    assert [key for key, count in Counter(duplicated).items() if count > 1] == [ids[0]]


def test_missing_reference_fixture_is_detectable() -> None:
    assert "PFQ-fundamentals-does-not-exist" not in canonical_index()


def test_catalog_loads_the_module_manifest() -> None:
    catalog = load_json(ROOT / "web/data/study-modules/catalog.json")
    assert catalog["format"] == "prepflow_study_module_catalog"
    assert catalog["modules"][0]["module_id"] == manifest()["module_id"]
    assert (ROOT / "web" / catalog["modules"][0]["manifest"]).is_file()


def test_browser_launch_reuses_question_references_and_quiz_engine() -> None:
    app = (ROOT / "web/app.js").read_text()
    assert "PrepFlowStudyModuleRules.resolveChapter" in app
    assert "await startSession(" in app
    assert "beginBlock();" in app
    assert "questionId: question.id" in app
    assert "saveSession(\"question\")" in app
    assert "saveSession(\"feedback\")" in app


def test_module_session_is_shuffled_once_and_saved_for_resume() -> None:
    app = (ROOT / "web/app.js").read_text()
    assert "sessionQuestions = PrepFlowOrderRules.orderQuestions" in app
    assert "currentSessionContext" in app
    resume_body = app.split("async function resumeSavedSession()", 1)[1]
    assert "PrepFlowOrderRules.orderQuestions" not in resume_body
    assert "sessionQuestions = saved.sessionQuestions || [];" in resume_body


def test_scoring_remains_fresh_and_first_attempt_only_per_chapter() -> None:
    app = (ROOT / "web/app.js").read_text()
    start_body = app.split("async function startSession", 1)[1].split("async function launchModuleChapter", 1)[0]
    assert "firstPassCorrect = 0;" in start_body
    assert "firstPassMissed = 0;" in start_body
    assert "if (!reviewMode)" in app
    assert "firstPassCorrect += 1;" in app
    assert "firstPassMissed += 1;" in app


def test_canonical_packs_are_not_duplicated_into_module_manifest() -> None:
    data = manifest()
    serialized = json.dumps(data)
    for forbidden in ("stem", "choices", "correct_answers", "rationale"):
        assert f'"{forbidden}"' not in serialized
