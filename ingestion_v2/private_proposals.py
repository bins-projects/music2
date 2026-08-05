from __future__ import annotations

import json
from pathlib import Path

from ingestion_v2.checkpoint import proposal_fingerprint
from ingestion_v2.domain import DomainError, Proposal


FILENAME = "user_proposals.private.json"


def write_private_user_proposals(run_directory: Path, proposals: tuple[Proposal, ...]) -> None:
    """Persist user-authored content only inside the ignored private run."""
    path = _path(run_directory)
    user_proposals = [item for item in proposals if item.proposal_id.startswith("PFV2-PROP-USER-")]
    if not user_proposals:
        if path.exists() and not path.is_symlink():
            path.unlink()
        return
    payload = {
        "format": "prepflow_v2_private_user_proposals",
        "version": "1.0",
        "proposals": [
            {
                "proposal_id": item.proposal_id,
                "finding_id": item.finding_id,
                "question_id": item.question_id,
                "field": item.field,
                "expected_before": item.expected_before,
                "proposed_after": item.proposed_after,
                "explanation": item.explanation,
                "requires_source_verification": item.requires_source_verification,
            }
            for item in sorted(user_proposals, key=lambda value: value.proposal_id)
        ],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.is_symlink():
        raise DomainError("Private proposal temporary path is unsafe")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def read_private_user_proposals(run_directory: Path) -> tuple[Proposal, ...]:
    path = _path(run_directory)
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise DomainError("Private proposal artifact is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DomainError("Private proposal artifact is malformed") from error
    if payload.get("format") != "prepflow_v2_private_user_proposals" or payload.get("version") != "1.0":
        raise DomainError("Private proposal artifact format is invalid")
    result = []
    for item in payload.get("proposals", []):
        if not isinstance(item, dict):
            raise DomainError("Private proposal artifact contains a malformed proposal")
        result.append(Proposal(**item))
    return tuple(result)


def proposal_fingerprints(proposals: tuple[Proposal, ...]) -> dict[str, str]:
    return {
        item.proposal_id: proposal_fingerprint(
            finding_id=item.finding_id,
            question_id=item.question_id,
            field=item.field,
            expected_before=item.expected_before,
            proposed_after=item.proposed_after,
            requires_source_verification=item.requires_source_verification,
        )
        for item in proposals
    }


def _path(run_directory: Path) -> Path:
    run = Path(run_directory)
    if run.is_symlink() or not run.is_dir() or not run.name.startswith("v2-run-"):
        raise DomainError("Private proposal storage requires a verified run directory")
    artifacts = run / "artifacts"
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise DomainError("Private proposal artifact directory is unsafe")
    return artifacts / FILENAME
