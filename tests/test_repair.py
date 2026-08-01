import json
from dataclasses import asdict
from pathlib import Path

import pytest

from compiler.repair import (
    Finding,
    RepairError,
    analyze_repair_delta,
    apply_repair,
    apply_repairs,
    create_repair_record,
    find_question,
    load_findings,
    load_repair_records,
    write_candidate_pack,
    write_repair_set,
)


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
                "chapter_title": "Safety",
                "type": "mc",
                "stem": "Which act ion is appropriate?",
                "choices": [
                    {"label": "A", "text": "First action"},
                    {"label": "B", "text": "Second action"},
                ],
                "correct_answers": ["A"],
                "rationale": "The first action is appropriate.",
            }
        ],
    }


def sample_finding() -> Finding:
    return Finding(
        finding_id="TEST-DAMAGE-001",
        question_id="PFQ-test-pack-000000001",
        field="stem",
        damage_type="possible split word",
    )


def test_legacy_ledger_loads_only_source_neutral_finding_fields(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "repair_id": "TEST-DAMAGE-001",
                        "question_id": "PFQ-test-pack-000000001",
                        "json_path": "$.questions[0].stem",
                        "rule": "possible split word",
                        "source_verified": True,
                        "source_location": "private-notes.docx, page 2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    finding = load_findings(ledger_path)[0]

    assert asdict(finding) == {
        "finding_id": "TEST-DAMAGE-001",
        "question_id": "PFQ-test-pack-000000001",
        "field": "stem",
        "damage_type": "possible split word",
    }


def test_repair_changes_candidate_without_mutating_canonical_pack() -> None:
    canonical = sample_pack()
    record = create_repair_record(
        canonical,
        sample_finding(),
        "Which action is appropriate?",
    )

    candidate = apply_repair(canonical, record)

    assert find_question(canonical, record.question_id)["stem"] == (
        "Which act ion is appropriate?"
    )
    assert find_question(candidate, record.question_id)["stem"] == (
        "Which action is appropriate?"
    )


def test_repair_collapses_pasted_wrapping_and_indentation() -> None:
    record = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action\n           is appropriate?",
    )

    assert record.after == "Which action is appropriate?"


def test_repair_delta_classifies_conservative_cleanup_patterns() -> None:
    assert analyze_repair_delta(
        "Choose w hich action.", "Choose which action."
    ).classification == "whitespace_only"
    assert analyze_repair_delta(
        "Clean rationale. Foreign metadata", "Clean rationale."
    ).classification == "trailing_metadata_removed"
    overlay = analyze_repair_delta(
        "beyNonUdRthSoIseNproGvidTedB.inCanOassociate",
        "beyondthoseprovidedinanassociate",
    )
    assert overlay.classification == "uppercase_overlay_fragment_removed"
    assert overlay.removed_characters == 12


def test_stale_repair_record_is_rejected() -> None:
    canonical = sample_pack()
    record = create_repair_record(
        canonical,
        sample_finding(),
        "Which action is appropriate?",
    )
    canonical["questions"][0]["stem"] = "Question changed elsewhere."

    with pytest.raises(RepairError, match="no longer matches"):
        apply_repair(canonical, record)


def test_repair_records_validate_pipeline_disposition() -> None:
    record = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is appropriate?",
        disposition="repair_rule_candidate",
    )

    assert record.disposition == "repair_rule_candidate"

    with pytest.raises(RepairError, match="Unsupported repair disposition"):
        create_repair_record(
            sample_pack(),
            sample_finding(),
            "Which action is appropriate?",
            disposition="automatic_rewrite",
        )


def test_candidate_writer_refuses_to_overwrite_canonical_pack(
    tmp_path: Path,
) -> None:
    canonical_path = tmp_path / "canonical.prepflow.json"
    canonical_path.write_text("canonical", encoding="utf-8")

    with pytest.raises(RepairError, match="must not overwrite"):
        write_candidate_pack(
            sample_pack(),
            canonical_path=canonical_path,
            candidate_path=canonical_path,
        )

    assert canonical_path.read_text(encoding="utf-8") == "canonical"


def test_candidate_writer_leaves_canonical_bytes_unchanged(
    tmp_path: Path,
) -> None:
    canonical_path = tmp_path / "canonical.prepflow.json"
    candidate_path = tmp_path / "output" / "candidate.prepflow.json"
    canonical_bytes = b"canonical pack bytes\n"
    canonical_path.write_bytes(canonical_bytes)

    write_candidate_pack(
        sample_pack(),
        canonical_path=canonical_path,
        candidate_path=candidate_path,
    )

    assert canonical_path.read_bytes() == canonical_bytes
    assert json.loads(candidate_path.read_text(encoding="utf-8"))[
        "pack_id"
    ] == "test-pack"


def test_repair_record_contains_no_source_provenance(
    tmp_path: Path,
) -> None:
    record = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is appropriate?",
    )
    path = write_repair_set([record], tmp_path / "repairs.json")
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert set(stored) == {
        "format",
        "version",
        "pack_id",
        "repairs",
    }
    assert set(stored["repairs"][0]) == {
        "format",
        "version",
        "repair_id",
        "pack_id",
        "question_id",
        "field",
        "before",
        "after",
        "damage_type",
        "approval",
        "disposition",
    }


def test_legacy_single_record_loads_for_migration(tmp_path: Path) -> None:
    record = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is appropriate?",
    )
    path = tmp_path / "repair-record.json"
    path.write_text(json.dumps(asdict(record)), encoding="utf-8")

    assert load_repair_records(path) == [record]


def test_multiple_repairs_rebuild_one_candidate() -> None:
    pack = sample_pack()
    first = create_repair_record(
        pack,
        sample_finding(),
        "Which action is appropriate?",
    )
    second = create_repair_record(
        pack,
        Finding(
            finding_id="TEST-DAMAGE-002",
            question_id="PFQ-test-pack-000000001",
            field="rationale",
            damage_type="possible split word",
        ),
        "The first action is the appropriate response.",
    )

    candidate = apply_repairs(pack, [first, second])
    question = candidate["questions"][0]

    assert question["stem"] == "Which action is appropriate?"
    assert question["rationale"] == (
        "The first action is the appropriate response."
    )
    assert pack == sample_pack()


def test_duplicate_repairs_are_rejected() -> None:
    pack = sample_pack()
    record = create_repair_record(
        pack,
        sample_finding(),
        "Which action is appropriate?",
    )

    with pytest.raises(RepairError, match="Duplicate repair identifier"):
        apply_repairs(pack, [record, record])
