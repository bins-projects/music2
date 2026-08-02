import hashlib
import json
from pathlib import Path

import pytest

from compiler.promotion_holds import PromotionHold
from compiler.workbench_compare import WorkbenchComparisonError, compare_workbenches
from compiler.workbench_compare_cli import main, render_text


def snapshot(root: Path, *, stem: str = "Question?", damage: str = "old damage") -> Path:
    directory = root / "fundamentals"
    directory.mkdir(parents=True)
    pack = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "stem": stem,
            }
        ],
    }
    manifest = {
        "format": "prepflow_candidate_manifest",
        "transformations": {"manual_repairs": 1},
        "promotion_blockers": [
            {
                "finding_id": "PFQA-ONE",
                "question_id": "PFQ-test-pack-000000001",
                "field": "stem",
                "damage_type": damage,
            }
        ],
    }
    repairs = {"format": "prepflow_repair_set", "repairs": [{}]}
    values = {
        "candidate.prepflow.json": pack,
        "candidate-manifest.json": manifest,
        "repair-records.json": repairs,
    }
    lines = []
    for name, value in values.items():
        path = directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  fundamentals/{name}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def hold() -> PromotionHold:
    return PromotionHold(
        hold_id="PFH-ONE",
        pack_id="test-pack",
        question_id="PFQ-test-pack-000000001",
        category="source_verification_required",
        reason="Verify before promotion.",
        status="unresolved",
    )


def test_unchanged_snapshots_compare_without_mutation(tmp_path) -> None:
    baseline = snapshot(tmp_path / "baseline")
    current = snapshot(tmp_path / "current")
    before = {path: path.read_bytes() for path in baseline.rglob("*") if path.is_file()}

    result = compare_workbenches(baseline, current, holds=(hold(),))

    assert result["pack"]["changed_questions"] == []
    assert result["blockers"]["removed"] == []
    assert result["blockers"]["added"] == []
    assert result["promotion_holds"]["promotion_ready"] is False
    assert all(path.read_bytes() == content for path, content in before.items())


def test_field_change_and_reclassification_are_reported_stably(tmp_path) -> None:
    baseline = snapshot(tmp_path / "baseline", damage="old damage")
    current = snapshot(tmp_path / "current", stem="Changed?", damage="new damage")

    result = compare_workbenches(baseline, current)

    assert result["pack"]["changed_questions"] == [
        {"question_id": "PFQ-test-pack-000000001", "fields": ["stem"]}
    ]
    assert result["blockers"]["reclassified"][0]["before"]["damage_type"] == "old damage"
    assert result["blockers"]["reclassified"][0]["after"]["damage_type"] == "new damage"
    assert "Reclassified: 1" in render_text(result)
    json.dumps(result, sort_keys=True)


def test_cli_emits_structured_json(tmp_path, monkeypatch, capsys) -> None:
    baseline = snapshot(tmp_path / "baseline")
    current = snapshot(tmp_path / "current")
    holds_path = tmp_path / "holds.json"
    holds_path.write_text(
        json.dumps(
            {
                "format": "prepflow_promotion_holds",
                "version": "1.0",
                "holds": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "workbench_compare_cli",
            str(baseline),
            str(current),
            "--holds",
            str(holds_path),
            "--json",
        ],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "prepflow_workbench_comparison"
    assert result["snapshots"]["baseline"]["checksums_verified"] is True


def test_added_and_removed_blockers_are_reported(tmp_path) -> None:
    baseline = snapshot(tmp_path / "baseline")
    current = snapshot(tmp_path / "current")
    manifest_path = current / "fundamentals" / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["promotion_blockers"][0]["field"] = "rationale"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checksum_path = current / "SHA256SUMS"
    lines = checksum_path.read_text().splitlines()
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    checksum_path.write_text("\n".join(digest + line[64:] if line.endswith("candidate-manifest.json") else line for line in lines) + "\n")

    result = compare_workbenches(baseline, current)

    assert [item["field"] for item in result["blockers"]["removed"]] == ["stem"]
    assert [item["field"] for item in result["blockers"]["added"]] == ["rationale"]


def test_checksum_failure_is_rejected(tmp_path) -> None:
    baseline = snapshot(tmp_path / "baseline")
    current = snapshot(tmp_path / "current")
    (current / "fundamentals" / "candidate.prepflow.json").write_text("{}")

    with pytest.raises(WorkbenchComparisonError, match="Checksum mismatch"):
        compare_workbenches(baseline, current)


@pytest.mark.parametrize("failure", ["missing", "malformed"])
def test_missing_or_malformed_snapshot_file_is_rejected(tmp_path, failure) -> None:
    baseline = snapshot(tmp_path / "baseline")
    current = snapshot(tmp_path / "current")
    target = current / "fundamentals" / "repair-records.json"
    if failure == "missing":
        target.unlink()
    else:
        target.write_text("not json")
        (current / "SHA256SUMS").unlink()

    with pytest.raises(WorkbenchComparisonError):
        compare_workbenches(baseline, current)
