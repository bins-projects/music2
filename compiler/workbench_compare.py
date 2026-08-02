import hashlib
import json
from collections import Counter
from pathlib import Path

from compiler.promotion_holds import PromotionHold, promotion_hold_summary


EXPECTED_FILES = (
    "candidate.prepflow.json",
    "candidate-manifest.json",
    "repair-records.json",
)


class WorkbenchComparisonError(ValueError):
    """Raised when a workbench snapshot cannot be compared safely."""


def _workbench_dir(path: str | Path) -> Path:
    root = Path(path)
    nested = root / "fundamentals"
    return nested if nested.is_dir() else root


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkbenchComparisonError(f"Missing snapshot file: {path.name}") from error
    except json.JSONDecodeError as error:
        raise WorkbenchComparisonError(f"Malformed JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise WorkbenchComparisonError(f"Expected JSON object: {path.name}")
    return value


def verify_snapshot(path: str | Path) -> dict:
    directory = _workbench_dir(path)
    for name in EXPECTED_FILES:
        if not (directory / name).is_file():
            raise WorkbenchComparisonError(f"Missing snapshot file: {name}")

    checksum_path = directory.parent / "SHA256SUMS"
    verified = False
    if checksum_path.is_file():
        expected = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                raise WorkbenchComparisonError("Malformed SHA256SUMS")
            expected[Path(parts[1].lstrip("* ")).name] = parts[0]
        for name in EXPECTED_FILES:
            if name not in expected:
                raise WorkbenchComparisonError(f"Checksum missing for: {name}")
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if actual != expected[name]:
                raise WorkbenchComparisonError(f"Checksum mismatch: {name}")
        verified = True

    return {"directory": directory, "checksums_verified": verified}


def _question_map(pack: dict) -> dict[str, dict]:
    questions = pack.get("questions")
    if pack.get("format") != "prepflow_pack" or not isinstance(questions, list):
        raise WorkbenchComparisonError("Malformed candidate Pack")
    result = {}
    for question in questions:
        if not isinstance(question, dict) or not isinstance(question.get("id"), str):
            raise WorkbenchComparisonError("Candidate contains malformed question")
        if question["id"] in result:
            raise WorkbenchComparisonError(f"Duplicate question ID: {question['id']}")
        result[question["id"]] = question
    return result


def _blocker_map(manifest: dict) -> dict[tuple[str, str], dict]:
    blockers = manifest.get("promotion_blockers")
    if not isinstance(blockers, list):
        raise WorkbenchComparisonError("Manifest promotion_blockers must be a list")
    result = {}
    for blocker in blockers:
        if not isinstance(blocker, dict) or not all(
            isinstance(blocker.get(field), str)
            for field in ("finding_id", "question_id", "field", "damage_type")
        ):
            raise WorkbenchComparisonError("Malformed promotion blocker")
        key = (blocker["question_id"], blocker["field"])
        if key in result:
            raise WorkbenchComparisonError(f"Duplicate blocker field: {key}")
        result[key] = blocker
    return result


def _sorted_values(mapping: dict, keys: set) -> list[dict]:
    return [mapping[key] for key in sorted(keys)]


def compare_workbenches(
    baseline_path: str | Path,
    current_path: str | Path,
    *,
    holds: tuple[PromotionHold, ...] = (),
) -> dict:
    baseline_state = verify_snapshot(baseline_path)
    current_state = verify_snapshot(current_path)
    baseline_dir = baseline_state["directory"]
    current_dir = current_state["directory"]
    baseline_pack = _load_object(baseline_dir / EXPECTED_FILES[0])
    current_pack = _load_object(current_dir / EXPECTED_FILES[0])
    baseline_manifest = _load_object(baseline_dir / EXPECTED_FILES[1])
    current_manifest = _load_object(current_dir / EXPECTED_FILES[1])
    baseline_repairs = _load_object(baseline_dir / EXPECTED_FILES[2])
    current_repairs = _load_object(current_dir / EXPECTED_FILES[2])

    baseline_questions = _question_map(baseline_pack)
    current_questions = _question_map(current_pack)
    baseline_ids = set(baseline_questions)
    current_ids = set(current_questions)
    changed = []
    for question_id in sorted(baseline_ids & current_ids):
        before = baseline_questions[question_id]
        after = current_questions[question_id]
        fields = sorted(
            field
            for field in set(before) | set(after)
            if before.get(field) != after.get(field)
        )
        if fields:
            changed.append({"question_id": question_id, "fields": fields})

    baseline_blockers = _blocker_map(baseline_manifest)
    current_blockers = _blocker_map(current_manifest)
    baseline_keys = set(baseline_blockers)
    current_keys = set(current_blockers)
    reclassified = []
    for key in sorted(baseline_keys & current_keys):
        before = baseline_blockers[key]
        after = current_blockers[key]
        if before != after:
            reclassified.append({"before": before, "after": after})

    pack_metadata_fields = (set(baseline_pack) | set(current_pack)) - {"questions"}
    inventory_damage = Counter(item["damage_type"] for item in current_blockers.values())
    inventory_fields = Counter(item["field"] for item in current_blockers.values())
    choice_total = sum(count for field, count in inventory_fields.items() if field.startswith("choices["))

    def repair_count(value: dict) -> int:
        records = value.get("repairs")
        if not isinstance(records, list):
            raise WorkbenchComparisonError("Repair record set must contain repairs")
        return len(records)

    return {
        "format": "prepflow_workbench_comparison",
        "version": "1.0",
        "snapshots": {
            "baseline": {"checksums_verified": baseline_state["checksums_verified"]},
            "current": {"checksums_verified": current_state["checksums_verified"]},
        },
        "pack": {
            "metadata_equal": all(
                baseline_pack.get(field) == current_pack.get(field)
                for field in pack_metadata_fields
            ),
            "baseline_question_count": len(baseline_questions),
            "current_question_count": len(current_questions),
            "added_question_ids": sorted(current_ids - baseline_ids),
            "removed_question_ids": sorted(baseline_ids - current_ids),
            "changed_questions": changed,
        },
        "repairs": {
            "baseline_count": repair_count(baseline_repairs),
            "current_count": repair_count(current_repairs),
            "baseline_transformations": baseline_manifest.get("transformations"),
            "current_transformations": current_manifest.get("transformations"),
        },
        "blockers": {
            "baseline_count": len(baseline_blockers),
            "current_count": len(current_blockers),
            "removed": _sorted_values(baseline_blockers, baseline_keys - current_keys),
            "added": _sorted_values(current_blockers, current_keys - baseline_keys),
            "reclassified": reclassified,
            "current_inventory_by_damage": dict(sorted(inventory_damage.items())),
            "current_inventory_by_field": dict(sorted(inventory_fields.items())),
            "current_choice_field_total": choice_total,
        },
        "promotion_holds": promotion_hold_summary(holds),
    }
