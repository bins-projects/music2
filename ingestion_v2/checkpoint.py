from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re

from ingestion_v2.domain import DomainError, QUESTION_ID_RE


RECORD_ID_RE = re.compile(r"^PFV2-REC-\d{6}$")
REFERENCE_RE = re.compile(r"^PFV2-(?:PROP|FIND|DEC|VERIFY|DISP)-[A-Za-z0-9-]+$")
FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
ACTIONS = {"approve", "reject", "defer", "exclude_record", "retain_blocker"}
FORBIDDEN_KEYS = {
    "text", "stem", "choices", "rationale", "source_path", "filename",
    "page_text", "raw", "cleaned", "proposed_after", "expected_before",
}


def write_checkpoint(run_directory: Path, payload: dict) -> Path:
    validated = validate_checkpoint(payload, run_id=Path(run_directory).name)
    run = _run(run_directory)
    audit = run / "audit"
    if audit.is_symlink():
        raise DomainError("Checkpoint audit directory is unsafe")
    audit.mkdir(mode=0o700, exist_ok=True)
    path = audit / "checkpoint.json"
    temporary = audit / "checkpoint.json.tmp"
    if path.is_symlink() or temporary.is_symlink():
        raise DomainError("Checkpoint path is unsafe")
    temporary.write_text(json.dumps(validated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read_checkpoint(run_directory: Path) -> dict:
    run = _run(run_directory)
    path = run / "audit" / "checkpoint.json"
    if path.is_symlink() or not path.is_file():
        raise DomainError("Private run checkpoint is missing or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DomainError("Private run checkpoint is malformed") from error
    return validate_checkpoint(payload, run_id=run.name)


def validate_checkpoint(payload: dict, *, run_id: str) -> dict:
    if not isinstance(payload, dict):
        raise DomainError("Checkpoint must be an object")
    if _contains_forbidden_key(payload):
        raise DomainError("Checkpoint contains source-bearing or question-content fields")
    if payload.get("format") != "prepflow_v2_checkpoint" or payload.get("version") != "1.0":
        raise DomainError("Checkpoint format is invalid")
    if payload.get("run_id") != run_id:
        raise DomainError("Checkpoint run identity does not match its directory")
    if not isinstance(payload.get("target_pack_id"), str) or not payload["target_pack_id"]:
        raise DomainError("Checkpoint target Pack ID is required")
    for item in payload.get("identity_actions", []):
        if not isinstance(item, dict) or not RECORD_ID_RE.fullmatch(str(item.get("record_id") or "")):
            raise DomainError("Checkpoint contains an invalid temporary record ID")
        if not QUESTION_ID_RE.fullmatch(str(item.get("target_question_id") or "")):
            raise DomainError("Checkpoint contains an invalid stable question ID")
    for group in ("review_decisions", "verifications", "dispositions"):
        if not isinstance(payload.get(group, []), list):
            raise DomainError(f"Checkpoint {group} must be a list")
        for item in payload[group]:
            if not isinstance(item, dict) or any(
                key.endswith("_id") and key != "question_id" and not REFERENCE_RE.fullmatch(str(value))
                for key, value in item.items() if key.endswith("_id")
            ):
                raise DomainError(f"Checkpoint {group} contains an invalid reference")
            if "question_id" in item and not QUESTION_ID_RE.fullmatch(str(item["question_id"])):
                raise DomainError("Checkpoint disposition contains an invalid question ID")
            if "action" in item and item["action"] not in ACTIONS:
                raise DomainError("Checkpoint contains an invalid action")
    fingerprints = payload.get("proposal_fingerprints", [])
    if not isinstance(fingerprints, list):
        raise DomainError("Checkpoint proposal fingerprints must be a list")
    for item in fingerprints:
        if (
            not isinstance(item, dict)
            or not REFERENCE_RE.fullmatch(str(item.get("proposal_id") or ""))
            or not FINGERPRINT_RE.fullmatch(str(item.get("fingerprint") or ""))
        ):
            raise DomainError("Checkpoint contains an invalid proposal fingerprint")
    counts = payload.get("comparison_counts", {})
    if not isinstance(counts, dict) or any(not isinstance(value, int) or value < 0 for value in counts.values()):
        raise DomainError("Checkpoint comparison counts are invalid")
    return payload


def proposal_fingerprint(
    *, finding_id: str, question_id: str, field: str, expected_before,
    proposed_after, requires_source_verification: bool,
) -> str:
    value = {
        "finding_id": finding_id,
        "question_id": question_id,
        "field": field,
        "expected_before": expected_before,
        "proposed_after": proposed_after,
        "requires_source_verification": requires_source_verification,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _contains_forbidden_key(value) -> bool:
    if isinstance(value, dict):
        return any(key in FORBIDDEN_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _run(run_directory: Path) -> Path:
    run = Path(run_directory)
    if run.is_symlink() or not run.is_dir() or not run.name.startswith("v2-run-"):
        raise DomainError("Checkpoint requires a verified private run directory")
    return run
