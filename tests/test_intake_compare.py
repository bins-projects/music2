from compiler.intake_compare import compare_intake_candidate
from compiler.repair import RepairRecord


def pack(stem: str) -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Test",
                "type": "mc",
                "stem": stem,
                "choices": [
                    {"label": "A", "text": "First"},
                    {"label": "B", "text": "Second"},
                ],
                "correct_answers": ["A"],
                "rationale": "Rationale.",
            }
        ],
    }


def test_comparison_classifies_reproduced_repair_without_applying_it() -> None:
    canonical = pack("Damaged stem")
    candidate = pack("Corrected stem")
    isolated = pack("Corrected stem")
    record = RepairRecord(
        format="prepflow_repair",
        version="1.0",
        repair_id="PFR-ONE",
        pack_id="test-pack",
        question_id="PFQ-test-pack-000000001",
        field="stem",
        before="Damaged stem",
        after="Corrected stem",
        damage_type="test correction",
        approval="approved",
        disposition="one_question",
    )

    evaluated, report = compare_intake_candidate(
        isolated,
        canonical,
        candidate,
        [record],
        [],
    )

    assert evaluated["questions"][0]["stem"] == "Corrected stem"
    assert report["repair_lesson_counts"] == {"reproduced": 1}
    assert report["field_outcome_counts"]["matches_candidate_24"] == 1
    assert report["deterministic_normalization"]["manual_repairs"] == 0
    assert report["promotion_ready"] is False


def test_comparison_classifies_not_reproduced_and_different_results() -> None:
    canonical = pack("Damaged stem")
    candidate = pack("Corrected stem")
    record = RepairRecord(
        format="prepflow_repair",
        version="1.0",
        repair_id="PFR-ONE",
        pack_id="test-pack",
        question_id="PFQ-test-pack-000000001",
        field="stem",
        before="Damaged stem",
        after="Corrected stem",
        damage_type="test correction",
        approval="approved",
        disposition="one_question",
    )

    _, missed = compare_intake_candidate(canonical, canonical, candidate, [record], [])
    _, different = compare_intake_candidate(pack("Third result"), canonical, candidate, [record], [])

    assert missed["repair_lesson_counts"] == {"not_reproduced": 1}
    assert different["repair_lesson_counts"] == {"different_result": 1}
