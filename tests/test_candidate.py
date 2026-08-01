import json
from pathlib import Path

from compiler.candidate import (
    build_candidate,
    candidate_manifest,
    write_candidate_manifest,
)
from compiler.repair import Finding, create_repair_record


def sample_pack() -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Communication",
                "type": "mc",
                "stem": "The patient states, ―I understand.‖",
                "choices": [
                    {"label": "A", "text": "First action"},
                    {"label": "B", "text": "Second action"},
                ],
                "correct_answers": ["A"],
                "rationale": "The nurse states, ―This text is damaged.",
            }
        ],
    }


def test_candidate_combines_manual_repairs_and_typography_normalization() -> None:
    canonical = sample_pack()
    record = create_repair_record(
        canonical,
        Finding(
            "TEST-REPAIR-001",
            "PFQ-test-pack-000000001",
            "choices[0].text",
            "spacing artifact",
        ),
        "Preferred action",
    )

    result = build_candidate(canonical, [record])
    question = result.candidate["questions"][0]

    assert canonical == sample_pack()
    assert question["stem"] == "The patient states, “I understand.”"
    assert question["choices"][0]["text"] == "Preferred action"
    assert question["rationale"] == "The nurse states, “This text is damaged."
    assert result.manual_repairs == 1
    assert result.typography_fields_changed == 2
    assert result.opening_marks_replaced == 2
    assert result.closing_marks_replaced == 1
    assert len(result.promotion_blockers) == 1
    assert result.promotion_blockers[0].field == "rationale"


def test_candidate_manifest_is_source_agnostic_and_records_blockers(
    tmp_path: Path,
) -> None:
    result = build_candidate(sample_pack(), [])
    manifest = candidate_manifest(result)

    assert set(manifest) == {
        "format",
        "version",
        "pack_id",
        "transformations",
        "promotion_blockers",
    }
    assert "source" not in json.dumps(manifest).lower()
    assert manifest["promotion_blockers"][0]["question_id"] == (
        "PFQ-test-pack-000000001"
    )

    path = write_candidate_manifest(result, tmp_path / "manifest.json")
    assert json.loads(path.read_text(encoding="utf-8")) == manifest


def test_candidate_deduplicates_multiple_blockers_for_one_field() -> None:
    pack = sample_pack()
    pack["questions"][0]["rationale"] = (
        "Damaged abCdEf g h j fragments begin with ―an open quote."
    )

    result = build_candidate(pack, [])

    assert len(result.promotion_blockers) == 1
    blocker = result.promotion_blockers[0]
    assert blocker.finding_id.startswith("PFQA-INTERLEAVE-")
    assert "unbalanced directional quotation marks" in blocker.damage_type


def test_candidate_applies_approved_text_rules_after_manual_repairs() -> None:
    pack = sample_pack()
    pack["questions"][0]["choices"][1]["text"] = (
        "Select w hich action is safest"
    )

    result = build_candidate(pack, [])

    assert result.candidate["questions"][0]["choices"][1]["text"] == (
        "Select which action is safest"
    )
    assert result.approved_text_fields_changed == 1
    assert result.approved_text_rule_fields == (("join_which_fragment", 1),)
