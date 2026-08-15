"""Trusted-operator canonical question actions for the PrepFlow Workbench.

A completed editor action writes Pack truth first. Git/publication is the delivery
mechanism and may be retried without applying the question twice.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from compiler.repair import load_pack
from ingestion_v2.question_workbench import (
    QuestionWorkbenchError,
    apply_operation_to_pack,
    load_ledger,
    locked_ledger,
    operation_by_id,
    update_operation,
    utc_now,
)
from tools.pack_catalog import installed_pack_registry, write_catalog


AUDIT_LOG = Path("docs/QUESTION_OPERATION_LOG.md")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
    return result.stdout.strip()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _pack_path(project_root: Path, pack_id: str) -> Path:
    registry = installed_pack_registry(project_root / "packs")
    try:
        return registry[pack_id]
    except KeyError as error:
        raise QuestionWorkbenchError("Selected Pack is unavailable") from error


def _question_by_id(pack: dict[str, Any], question_id: str) -> dict[str, Any] | None:
    return next((item for item in pack.get("questions", []) if item.get("id") == question_id), None)


def _desired_matches_current(operation: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return False
    desired = operation.get("question")
    if not isinstance(desired, dict):
        return False
    if operation.get("operation_type") == "addition":
        return current == desired
    # Repairs may have been applied by a bulk/manual route that retained extra
    # source/provenance fields. Compare every field the saved repair intended.
    return all(current.get(key) == value for key, value in desired.items())


def reconcile_saved_operations(ledger_path: Path, packs: dict[str, dict[str, Any]]) -> int:
    """Remove stale pending rows whose intended result is already Pack truth."""
    if not ledger_path.is_file():
        return 0
    removed = 0
    with locked_ledger(ledger_path) as ledger:
        kept = []
        for operation in ledger["operations"]:
            if operation.get("state") != "pending":
                kept.append(operation)
                continue
            pack = packs.get(str(operation.get("pack_id") or ""))
            current = _question_by_id(pack or {}, str(operation.get("question_id") or ""))
            if _desired_matches_current(operation, current):
                removed += 1
            else:
                kept.append(operation)
        ledger["operations"] = kept
    return removed


def discard_pending_operation(ledger_path: Path, operation_id: str) -> dict[str, Any]:
    """Discard only unapplied Workbench state; never mutate a Pack."""
    with locked_ledger(ledger_path) as ledger:
        index = next((i for i, item in enumerate(ledger["operations"]) if item.get("operation_id") == operation_id), None)
        if index is None:
            raise QuestionWorkbenchError("Saved operation was not found")
        operation = ledger["operations"][index]
        if operation.get("state") != "pending":
            raise QuestionWorkbenchError("Only an unapplied draft can be discarded")
        removed = ledger["operations"].pop(index)
    return copy.deepcopy(removed)


def _append_audit(log_path: Path, operation: dict[str, Any], before_hash: str, after_hash: str) -> None:
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# PrepFlow Question Operation Log\n\n", encoding="utf-8")
    record = {
        "recorded_at": utc_now(),
        "operation_id": operation["operation_id"],
        "operation_type": operation["operation_type"],
        "pack_id": operation["pack_id"],
        "question_id": operation["question_id"],
        "pack_sha256_before": before_hash,
        "pack_sha256_after": after_hash,
        "original_question": operation.get("original_question"),
        "question": operation["question"],
    }
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(f"## {record['recorded_at']} — `{record['question_id']}`\n\n```json\n")
        json.dump(record, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n```\n\n")


def apply_canonical_operation(project_root: Path, ledger_path: Path, operation_id: str) -> dict[str, Any]:
    """Apply one pending operation atomically to the installed canonical Pack."""
    operation = operation_by_id(ledger_path, operation_id)
    if operation.get("state") in {"applied", "publishing", "published"}:
        return operation
    if operation.get("state") != "pending":
        raise QuestionWorkbenchError("Saved operation is not actionable")

    pack_path = _pack_path(project_root, operation["pack_id"])
    original_bytes = pack_path.read_bytes()
    before_hash = hashlib.sha256(original_bytes).hexdigest()
    updated = apply_operation_to_pack(operation, load_pack(pack_path))
    encoded = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    after_hash = hashlib.sha256(encoded).hexdigest()

    audit_path = project_root / AUDIT_LOG
    catalog_path = project_root / "web" / "data" / "pack-catalog.json"
    precache_path = project_root / "web" / "pack-precache.js"
    snapshots = {
        path: path.read_bytes() if path.exists() else None
        for path in (audit_path, catalog_path, precache_path)
    }
    backup_dir = project_root / "output" / "pack-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{operation['pack_id']}-{utc_now().replace(':','').replace('-','')}-{before_hash[:12]}.prepflow.json"

    try:
        _atomic_write(backup_path, original_bytes)
        _atomic_write(pack_path, encoded)
        _append_audit(audit_path, operation, before_hash, after_hash)
        write_catalog(project_root / "packs", catalog_path)
    except Exception:
        _atomic_write(pack_path, original_bytes)
        for path, content in snapshots.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, content)
        raise

    return update_operation(
        ledger_path,
        operation_id,
        state="applied",
        blocker=None,
        publication={
            "stage": "canonical_saved",
            "pack_sha256_before": before_hash,
            "pack_sha256": after_hash,
            "backup": str(backup_path.relative_to(project_root)),
            "applied_at": utc_now(),
        },
    )


def _remote_matches(url: str | None, repository_name: str) -> bool:
    if not url:
        return False
    normalized = url.rstrip("/").removesuffix(".git").casefold()
    return normalized.endswith("/" + repository_name.casefold()) or normalized.endswith(":" + repository_name.casefold())


def publication_status(project_root: Path, public_worktree: Path | None, operation: dict[str, Any]) -> dict[str, Any]:
    """Check delivery prerequisites while allowing this operation's canonical files."""
    reasons: list[str] = []
    details: dict[str, Any] = {}
    try:
        branch = _git(project_root, "branch", "--show-current")
    except RuntimeError:
        branch = ""
    details["private_branch"] = branch
    if branch != "master":
        reasons.append("Private branch is not master")

    try:
        origin = _git(project_root, "remote", "get-url", "origin")
    except RuntimeError:
        origin = None
    try:
        public = _git(project_root, "remote", "get-url", "public")
    except RuntimeError:
        public = None
    if not _remote_matches(origin, "prepflow-dev"):
        reasons.append("Private remote is unavailable")
    if not _remote_matches(public, "PrepFlow"):
        reasons.append("Public remote is unavailable")
    details.update(private_remote=origin, public_remote=public)

    try:
        if _git(project_root, "rev-parse", "HEAD") != _git(project_root, "rev-parse", "origin/master"):
            reasons.append("Private master is out of date")
    except RuntimeError:
        reasons.append("Private master state is unavailable")

    pack_path = _pack_path(project_root, operation["pack_id"])
    allowed = {
        str(pack_path.relative_to(project_root)),
        str(AUDIT_LOG),
        "web/data/pack-catalog.json",
        "web/pack-precache.js",
    }
    try:
        changed = {
            line[3:].split(" -> ")[-1]
            for line in _git(project_root, "status", "--porcelain", "--untracked-files=no").splitlines()
            if line
        }
        unrelated = changed - allowed
        if unrelated:
            reasons.append("Private worktree has unrelated tracked changes")
            details["unrelated_private"] = sorted(unrelated)
    except RuntimeError:
        reasons.append("Private worktree state is unavailable")

    if public_worktree is None or not public_worktree.is_dir():
        reasons.append("Public release worktree is unavailable")
    else:
        try:
            if _git(public_worktree, "status", "--porcelain", "--untracked-files=no"):
                reasons.append("Public release worktree has unrelated changes")
            if _git(public_worktree, "rev-parse", "HEAD") != _git(public_worktree, "rev-parse", "public/master"):
                reasons.append("Public master is out of date")
        except RuntimeError:
            reasons.append("Public release worktree state is unavailable")

    reasons = list(dict.fromkeys(reasons))
    return {
        "ready": not reasons,
        "operator_state": "Publishable" if not reasons else "Saved to canonical Pack — publication pending",
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "details": details,
    }


def publish_applied_operation(
    project_root: Path, public_worktree: Path | None, ledger_path: Path, operation_id: str,
) -> dict[str, Any]:
    """Commit/push an already-applied canonical operation and mirror its Pack publicly."""
    operation = operation_by_id(ledger_path, operation_id)
    if operation.get("state") == "published":
        return operation.get("publication") or {}
    if operation.get("state") == "pending":
        operation = apply_canonical_operation(project_root, ledger_path, operation_id)

    publication = operation.get("publication") or {}
    stage = publication.get("stage")
    private_commit = publication.get("private_commit")
    public_commit = publication.get("public_commit")

    if stage == "private_committed":
        if _git(project_root, "rev-parse", "HEAD") != private_commit:
            raise RuntimeError("Private publication recovery no longer matches HEAD")
        _git(project_root, "push", "origin", "HEAD:master")
        stage = "private_published"
        operation = update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                                     publication={**publication, "stage": stage})
        publication = operation["publication"]

    if stage not in {"private_published", "public_committed"}:
        status = publication_status(project_root, public_worktree, operation)
        if not status["ready"]:
            update_operation(ledger_path, operation_id, state="applied", blocker=status["reason"],
                             publication={**publication, "stage": "canonical_saved"})
            raise RuntimeError(status["reason"] or "Publication is unavailable")
        pack_path = _pack_path(project_root, operation["pack_id"])
        private_paths = [
            str(pack_path.relative_to(project_root)),
            str(AUDIT_LOG),
            "web/data/pack-catalog.json",
            "web/pack-precache.js",
        ]
        try:
            _git(project_root, "add", "--", *private_paths)
            verb = "Repair" if operation["operation_type"] == "repair" else "Add"
            _git(project_root, "commit", "-m", f"{verb} question {operation['question_id']}")
            private_commit = _git(project_root, "rev-parse", "HEAD")
            update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                             publication={**publication, "stage": "private_committed", "private_commit": private_commit})
            _git(project_root, "push", "origin", "HEAD:master")
        except Exception as error:
            current_head = _git(project_root, "rev-parse", "HEAD")
            if private_commit and current_head == private_commit:
                update_operation(ledger_path, operation_id, state="publishing", blocker=str(error),
                                 publication={**publication, "stage": "private_committed", "private_commit": private_commit})
            else:
                update_operation(ledger_path, operation_id, state="applied", blocker=str(error),
                                 publication={**publication, "stage": "canonical_saved"})
            raise
        stage = "private_published"
        operation = update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                                     publication={**publication, "stage": stage, "private_commit": private_commit})
        publication = operation["publication"]

    if public_worktree is None:
        raise RuntimeError("Public release worktree is unavailable")
    pack_path = _pack_path(project_root, operation["pack_id"])
    relative_pack = pack_path.relative_to(project_root)

    if stage == "public_committed":
        if _git(public_worktree, "rev-parse", "HEAD") != public_commit:
            raise RuntimeError("Public publication recovery no longer matches HEAD")
        _git(public_worktree, "push", "public", "HEAD:master")
    else:
        try:
            public_pack = public_worktree / relative_pack
            public_pack.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack_path, public_pack)
            write_catalog(public_worktree / "packs", public_worktree / "web" / "data" / "pack-catalog.json")
            if public_pack.read_bytes() != pack_path.read_bytes():
                raise RuntimeError("Private/public Pack byte equality failed")
            _git(public_worktree, "add", "--", str(relative_pack), "web/data/pack-catalog.json", "web/pack-precache.js")
            verb = "Repair" if operation["operation_type"] == "repair" else "Add"
            _git(public_worktree, "commit", "-m", f"{verb} question {operation['question_id']}")
            public_commit = _git(public_worktree, "rev-parse", "HEAD")
            update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                             publication={**publication, "stage": "public_committed", "private_commit": private_commit,
                                          "public_commit": public_commit})
            _git(public_worktree, "push", "public", "HEAD:master")
        except Exception as error:
            update_operation(ledger_path, operation_id, state="publishing", blocker=str(error),
                             publication={**publication, "stage": "public_committed" if public_commit else "private_published",
                                          "private_commit": private_commit, **({"public_commit": public_commit} if public_commit else {})})
            raise

    result = {
        **publication,
        "stage": "published",
        "private_commit": private_commit,
        "public_commit": public_commit,
        "pack_sha256": hashlib.sha256(pack_path.read_bytes()).hexdigest(),
        "published_at": utc_now(),
    }
    update_operation(ledger_path, operation_id, state="published", blocker=None, publication=result)
    return result
