"""Guarded two-repository publisher for saved question operations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from compiler.repair import load_pack
from ingestion_v2.question_workbench import apply_operation_to_pack, operation_by_id, update_operation, utc_now
from tools.pack_catalog import write_catalog


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
    return result.stdout.strip()


def _remote_url(root: Path, name: str) -> str | None:
    try:
        return git(root, "remote", "get-url", name)
    except RuntimeError:
        return None


def _same_commit(root: Path, left: str, right: str) -> bool:
    try:
        return git(root, "rev-parse", left) == git(root, "rev-parse", right)
    except RuntimeError:
        return False


def publication_readiness(
    project_root: Path, public_worktree: Path | None, *, private_remote: str = "origin",
    public_remote: str = "public", private_branch: str = "master", public_branch: str = "master",
    expected_private_url_suffix: str = "prepflow-dev.git", expected_public_url_suffix: str = "PrepFlow.git",
) -> dict[str, Any]:
    reasons: list[str] = []
    details: dict[str, Any] = {}
    try: top = Path(git(project_root, "rev-parse", "--show-toplevel")).resolve()
    except RuntimeError: top = None
    if top != project_root.resolve(): reasons.append("Unexpected private repository")
    private_url, public_url = _remote_url(project_root, private_remote), _remote_url(project_root, public_remote)
    details.update(private_remote=private_url, public_remote=public_url)
    if not private_url or not private_url.rstrip("/").endswith(expected_private_url_suffix): reasons.append("Unexpected private remote")
    if not public_url or not public_url.rstrip("/").endswith(expected_public_url_suffix): reasons.append("Unexpected public remote")
    try: branch = git(project_root, "branch", "--show-current")
    except RuntimeError: branch = ""
    details["private_branch"] = branch
    if branch != private_branch: reasons.append(f"Private branch is not {private_branch}")
    try: status = git(project_root, "status", "--porcelain", "--untracked-files=no")
    except RuntimeError: status = "status unavailable"
    if status: reasons.append("Repository contains unrelated changes")
    if not _same_commit(project_root, "HEAD", f"{private_remote}/{private_branch}"): reasons.append("Private branch is out of date")
    if public_worktree is None or not public_worktree.is_dir():
        reasons.append("Public worktree unavailable")
    else:
        try:
            public_top = Path(git(public_worktree, "rev-parse", "--show-toplevel")).resolve()
            public_status = git(public_worktree, "status", "--porcelain", "--untracked-files=no")
        except RuntimeError:
            public_top, public_status = None, "status unavailable"
        details["public_worktree"] = str(public_worktree)
        if public_top != public_worktree.resolve(): reasons.append("Public worktree unavailable")
        elif public_status: reasons.append("Public worktree contains unrelated changes")
        if not _same_commit(public_worktree, "HEAD", f"{public_remote}/{public_branch}"): reasons.append("Public branch is out of date")
        if not (public_worktree / "packs").is_dir() or not (public_worktree / "web").is_dir(): reasons.append("Public Pack or catalog location unavailable")
    if not (project_root / "packs").is_dir() or not (project_root / "web").is_dir(): reasons.append("Private Pack or catalog location unavailable")
    reasons = list(dict.fromkeys(reasons))
    return {"ready": not reasons, "operator_state": "Publishable" if not reasons else "Publishing unavailable — will save",
            "reason": reasons[0] if reasons else None, "reasons": reasons, "details": details}


def prepare_public_worktree(project_root: Path, destination: Path, *, public_remote: str = "public", public_branch: str = "master") -> dict[str, Any]:
    """Create/update a clean detached public worktree, never resetting unrelated work."""
    git(project_root, "fetch", public_remote, public_branch)
    if destination.exists():
        try: git(destination, "rev-parse", "--show-toplevel")
        except RuntimeError as error: raise RuntimeError("Public worktree destination is not a Git worktree") from error
        if git(destination, "status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("Public worktree contains unrelated changes")
        git(destination, "checkout", "--detach", f"{public_remote}/{public_branch}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        git(project_root, "worktree", "add", "--detach", str(destination), f"{public_remote}/{public_branch}")
    return {"path": str(destination), "commit": git(destination, "rev-parse", "HEAD")}


def _append_evidence(path: Path, operation: dict[str, Any], before_hash: str, after_hash: str) -> None:
    if not path.exists():
        path.write_text("# PrepFlow Question Operation Log\n\n", encoding="utf-8")
    summary = {
        "recorded_at": utc_now(), "operation_id": operation["operation_id"],
        "operation_type": operation["operation_type"], "pack_id": operation["pack_id"],
        "question_id": operation["question_id"], "pack_sha256_before": before_hash,
        "pack_sha256_after": after_hash, "original_question": operation.get("original_question"),
        "question": operation["question"],
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"## {summary['recorded_at']} — `{operation['question_id']}`\n\n```json\n")
        json.dump(summary, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n```\n\n")


def _changed_paths(root: Path) -> set[str]:
    paths = set()
    for line in git(root, "status", "--porcelain", "--untracked-files=no").splitlines():
        if line:
            paths.add(line[3:].split(" -> ")[-1])
    return paths


def publish_saved_operation(
    project_root: Path, public_worktree: Path, ledger_path: Path, operation_id: str, *,
    private_remote: str = "origin", public_remote: str = "public", private_branch: str = "master",
    public_branch: str = "master", readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish or deterministically resume one saved operation."""
    operation = operation_by_id(ledger_path, operation_id)
    if operation["state"] == "published":
        return operation["publication"]
    publication = operation.get("publication") or {}
    stage = publication.get("stage")

    if stage == "private_committed":
        private_commit = publication["private_commit"]
        if git(project_root, "rev-parse", "HEAD") != private_commit:
            raise RuntimeError("Private committed recovery state no longer matches HEAD")
        git(project_root, "push", private_remote, f"HEAD:{private_branch}")
        operation = update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                                     publication={"stage": "private_published", "private_commit": private_commit})
        stage = "private_published"

    if stage not in {"private_published", "public_committed"}:
        check = readiness or publication_readiness(
            project_root, public_worktree, private_remote=private_remote, public_remote=public_remote,
            private_branch=private_branch, public_branch=public_branch,
        )
        if not check["ready"]:
            update_operation(ledger_path, operation_id, state="pending", blocker=check["reason"])
            raise RuntimeError(check["reason"] or "Publishing unavailable")
        pack_path = next((path for path in (project_root / "packs").glob("*.prepflow.json")
                          if load_pack(path)["pack_id"] == operation["pack_id"]), None)
        if pack_path is None:
            raise RuntimeError("Selected Pack is unavailable")
        original_pack_bytes = pack_path.read_bytes()
        before_hash = hashlib.sha256(original_pack_bytes).hexdigest()
        updated = apply_operation_to_pack(operation, load_pack(pack_path))
        encoded = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode()
        evidence = project_root / "docs" / "QUESTION_OPERATION_LOG.md"
        catalog = project_root / "web" / "data" / "pack-catalog.json"
        precache = project_root / "web" / "pack-precache.js"
        changed_paths = (pack_path, evidence, catalog, precache)
        backups = {path: path.read_bytes() if path.exists() else None for path in (evidence, catalog, precache)}
        update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                         publication={"stage": "applying_private"})
        private_commit = None
        try:
            pack_path.write_bytes(encoded)
            _append_evidence(evidence, operation, before_hash, hashlib.sha256(encoded).hexdigest())
            write_catalog(project_root / "packs", catalog)
            git(project_root, "add", "--", *(str(path.relative_to(project_root)) for path in changed_paths))
            verb = {"repair": "Repair", "addition": "Add", "deletion": "Delete"}[operation["operation_type"]]
            git(project_root, "commit", "-m", f"{verb} question {operation['question_id']}")
            private_commit = git(project_root, "rev-parse", "HEAD")
            git(project_root, "push", private_remote, f"HEAD:{private_branch}")
        except Exception as error:
            if private_commit is not None:
                update_operation(ledger_path, operation_id, state="publishing", blocker=str(error),
                                 publication={"stage": "private_committed", "private_commit": private_commit, "error": str(error)})
            else:
                try:
                    git(project_root, "restore", "--staged", "--", *(str(path.relative_to(project_root)) for path in changed_paths))
                except RuntimeError:
                    pass
                pack_path.write_bytes(original_pack_bytes)
                for path, content in backups.items():
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(content)
                update_operation(ledger_path, operation_id, state="pending", blocker=str(error),
                                 publication={"stage": "private_failed", "error": str(error)})
            raise
        operation = update_operation(ledger_path, operation_id, state="publishing", blocker=None,
                                     publication={"stage": "private_published", "private_commit": private_commit})
        stage = "private_published"
    else:
        private_commit = publication["private_commit"]
        pack_path = next(path for path in (project_root / "packs").glob("*.prepflow.json")
                         if load_pack(path)["pack_id"] == operation["pack_id"])

    relative_pack = pack_path.relative_to(project_root)
    public_pack = public_worktree / relative_pack
    public_allowed = {str(relative_pack), "web/data/pack-catalog.json", "web/pack-precache.js"}
    unrelated = _changed_paths(public_worktree) - public_allowed
    if unrelated:
        raise RuntimeError("Public worktree contains unrelated changes: " + ", ".join(sorted(unrelated)))

    if stage == "public_committed":
        public_commit = publication["public_commit"]
        if git(public_worktree, "rev-parse", "HEAD") != public_commit:
            raise RuntimeError("Public committed recovery state no longer matches HEAD")
        git(public_worktree, "push", public_remote, f"HEAD:{public_branch}")
    else:
        public_commit = None
        try:
            public_pack.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack_path, public_pack)
            write_catalog(public_worktree / "packs", public_worktree / "web" / "data" / "pack-catalog.json")
            if public_pack.read_bytes() != pack_path.read_bytes():
                raise RuntimeError("Private/public Pack byte equality failed")
            git(public_worktree, "add", "--", str(relative_pack), "web/data/pack-catalog.json", "web/pack-precache.js")
            verb = {"repair": "Repaired", "addition": "Added", "deletion": "Deleted"}[operation["operation_type"]]
            git(public_worktree, "commit", "-m", f"{verb} {operation['question_id']}")
            public_commit = git(public_worktree, "rev-parse", "HEAD")
            git(public_worktree, "push", public_remote, f"HEAD:{public_branch}")
        except Exception as error:
            recovery = {"stage": "public_committed" if public_commit else "private_published",
                        "private_commit": private_commit, "error": str(error)}
            if public_commit:
                recovery["public_commit"] = public_commit
            update_operation(ledger_path, operation_id, state="publishing", blocker=str(error), publication=recovery)
            raise

    result = {"stage": "published", "private_commit": private_commit, "public_commit": public_commit,
              "pack_sha256": hashlib.sha256(pack_path.read_bytes()).hexdigest(), "published_at": utc_now()}
    update_operation(ledger_path, operation_id, state="published", blocker=None, publication=result)
    return result
