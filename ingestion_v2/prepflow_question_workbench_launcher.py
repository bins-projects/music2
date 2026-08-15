#!/usr/bin/env python3
"""Purpose-built launcher that prepares the PrepFlow Question Workbench."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from ingestion_v2.question_publisher import prepare_public_worktree


DEFAULT_REPOSITORY = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_WORKTREE_NAME = "prepflow-public-release"
PUBLIC_REMOTE_URL = "https://github.com/bins-projects/PrepFlow.git"


def public_worktree_destination(repository: Path) -> Path:
    return repository.parent / DEFAULT_PUBLIC_WORKTREE_NAME


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repository, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git verification failed")
    return result.stdout.strip()


def _remote_matches(url: str, repository_name: str) -> bool:
    normalized = url.rstrip("/").removesuffix(".git").casefold()
    return normalized.endswith("/" + repository_name.casefold()) or normalized.endswith(":" + repository_name.casefold())


def ensure_public_remote(repository: Path) -> None:
    """Keep Codespaces one-click: configure the known public mirror if absent."""
    try:
        current = _git(repository, "remote", "get-url", "public")
    except RuntimeError:
        _git(repository, "remote", "add", "public", PUBLIC_REMOTE_URL)
        return
    if not _remote_matches(current, "PrepFlow"):
        raise RuntimeError("Unexpected public remote")


def prepare(repository: Path) -> dict:
    """Prepare optional automated publication without blocking canonical editing."""
    try:
        if Path(_git(repository, "rev-parse", "--show-toplevel")).resolve() != repository.resolve():
            raise RuntimeError("Unexpected private repository")
        if _git(repository, "branch", "--show-current") != "master":
            raise RuntimeError("Private branch is not master")
        origin = _git(repository, "remote", "get-url", "origin")
        if not _remote_matches(origin, "prepflow-dev"):
            raise RuntimeError("Unexpected private remote")
        ensure_public_remote(repository)
        if _git(repository, "status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("Repository contains unrelated tracked changes")
        if _git(repository, "rev-parse", "HEAD") != _git(repository, "rev-parse", "origin/master"):
            raise RuntimeError("Private branch is out of date")
        result = prepare_public_worktree(repository, public_worktree_destination(repository))
        return {"available": True, **result}
    except Exception as error:
        # Publication setup is optional. The Workbench still starts and canonical
        # Pack edits remain available; failed delivery can be retried later.
        return {"available": False, "reason": str(error)}


def command(repository: Path, host: str, port: int) -> list[str]:
    python = repository / ".venv" / "bin" / "python"
    if not python.is_file():
        python = Path(sys.executable)
    return [str(python), "-m", "ingestion_v2.one_click_workbench_server", "--host", host, "--port", str(port)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the unified private PrepFlow Workbench")
    parser.add_argument("--repository", type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument("--host", default="0.0.0.0" if os.environ.get("CODESPACES") else "127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    repository = args.repository.resolve()
    if not (repository / ".git").exists():
        print("Expected private PrepFlow repository is unavailable", file=sys.stderr)
        return 2
    prepared = prepare(repository)
    state_path = repository / "output" / "question-workbench" / "launcher-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
    if args.prepare_only:
        print(json.dumps(prepared))
        return 0
    environment = dict(os.environ)
    if prepared["available"]:
        environment["PREPFLOW_PUBLIC_WORKTREE"] = prepared["path"]
    return subprocess.run(command(repository, args.host, args.port), cwd=repository, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
