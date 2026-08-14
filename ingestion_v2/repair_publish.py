"""Private audit records for an explicitly published canonical Pack repair.

This module contains no Git or network operation.  It creates the durable,
source-neutral record that a later guarded publisher stages in private dev.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import shutil
from typing import Any
from tools.pack_catalog import write_catalog


REPAIR_LOG_HEADER = "# Published Pack Repair Log\n\n"


def repair_log_entry(
    *,
    pack_id: str,
    question_id: str,
    previous_question: dict[str, Any],
    replacement_question: dict[str, Any],
    pack_sha256_before: str,
    pack_sha256_after: str,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Build a private, reviewable record for one complete question repair."""
    recorded_at = timestamp or datetime.now(timezone.utc)
    return {
        "recorded_at": recorded_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pack_id": pack_id,
        "question_id": question_id,
        "pack_sha256_before": pack_sha256_before,
        "pack_sha256_after": pack_sha256_after,
        "previous_question": previous_question,
        "replacement_question": replacement_question,
    }


def append_repair_log(path: Path, entry: dict[str, Any]) -> None:
    """Append one immutable, human-readable private repair record."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(REPAIR_LOG_HEADER, encoding="utf-8")
    record = json.dumps(entry, indent=2, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(f"## {entry['recorded_at']} — `{entry['question_id']}`\n\n")
        log.write("```json\n")
        log.write(record)
        log.write("\n```\n\n")


def publish_preflight(project_root: Path, public_worktree: Path | None = None, *, allowed_private: set[str] = frozenset()) -> dict[str, Any]:
    """Report whether a Codespaces repair can be published; never writes or pushes."""
    def git(root: Path, *args: str) -> tuple[int, str]:
        result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
        return result.returncode, result.stdout.rstrip("\n") or result.stderr.strip()

    private_code, private_status = git(project_root, "status", "--porcelain")
    private_changes = private_status.splitlines()
    unrelated = [line for line in private_changes if line[3:].strip() not in allowed_private]
    result: dict[str, Any] = {
        "mode": "dry_run_only",
        "private_clean": private_code == 0 and not unrelated,
        "private_status": private_changes,
        "public_worktree_configured": public_worktree is not None,
        "ready": False,
        "reasons": [],
    }
    if private_code:
        result["reasons"].append("Private development Git status could not be read")
    elif unrelated:
        result["reasons"].append("Private development worktree has unpublished changes")
    if public_worktree is None:
        result["reasons"].append("No public release worktree is configured")
    else:
        public_code, public_status = git(public_worktree, "status", "--porcelain")
        result["public_clean"] = public_code == 0 and not public_status
        result["public_status"] = public_status.splitlines()
        if public_code:
            result["reasons"].append("Public release Git status could not be read")
        elif public_status:
            result["reasons"].append("Public release worktree has unpublished changes")
    result["ready"] = not result["reasons"]
    return result


def live_publish_enabled(environment: dict[str, str]) -> bool:
    """Live publishing requires an intentional Codespaces-only opt-in."""
    return environment.get("PREPFLOW_ENABLE_REPAIR_PUBLISH") == "1"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def publish_pack_repair(project_root: Path, public_worktree: Path, pack_path: Path, *, environment: dict[str, str], dry_run: bool = False) -> dict[str, str]:
    """Publish one reviewed Pack repair to private dev and the curated public app."""
    if not live_publish_enabled(environment):
        raise RuntimeError("Live repair publishing is disabled")
    check = publish_preflight(project_root, public_worktree, allowed_private={
        str(pack_path.relative_to(project_root)), "docs/REPAIR_LOG.md", "web/pack-precache.js",
    })
    if not check["ready"]:
        raise RuntimeError("Publish preflight blocked: " + "; ".join(check["reasons"]))
    relative_pack = pack_path.relative_to(project_root)
    if dry_run:
        return {"mode": "dry_run", "private_pack": str(relative_pack), "public_pack": str(relative_pack)}
    log = Path("docs/REPAIR_LOG.md")
    _git(project_root, "add", "--", str(relative_pack), str(log), "web/pack-precache.js")
    _git(project_root, "commit", "-m", f"Publish repair for {pack_path.stem}")
    private_commit = _git(project_root, "rev-parse", "HEAD")
    _git(project_root, "push", "origin", "HEAD:master")
    public_pack = public_worktree / relative_pack
    public_pack.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pack_path, public_pack)
    write_catalog(public_worktree / "packs", public_worktree / "web" / "data" / "pack-catalog.json")
    _git(public_worktree, "add", "--", str(relative_pack), "web/data/pack-catalog.json", "web/pack-precache.js")
    _git(public_worktree, "commit", "-m", f"Release repaired {pack_path.stem}")
    public_commit = _git(public_worktree, "rev-parse", "HEAD")
    _git(public_worktree, "push", "origin", "HEAD:master")
    return {"private_commit": private_commit, "public_commit": public_commit}
