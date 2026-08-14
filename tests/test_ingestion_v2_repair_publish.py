from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

from ingestion_v2.repair_publish import append_repair_log, live_publish_enabled, publish_pack_repair, publish_preflight, repair_log_entry


ROOT = Path(__file__).resolve().parents[1]


def _run(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def _commit(root: Path, message: str) -> None:
    _run(root, "add", ".")
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", message], cwd=root, check=True, text=True, capture_output=True)


def test_private_repair_log_preserves_before_after_questions(tmp_path) -> None:
    entry = repair_log_entry(
        pack_id="pediatrics",
        question_id="PFQ-pediatrics-000000001",
        previous_question={"id": "PFQ-pediatrics-000000001", "stem": "Before?"},
        replacement_question={"id": "PFQ-pediatrics-000000001", "stem": "After?"},
        pack_sha256_before="before",
        pack_sha256_after="after",
        timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    log = tmp_path / "REPAIR_LOG.md"
    append_repair_log(log, entry)

    content = log.read_text(encoding="utf-8")
    assert "# Published Pack Repair Log" in content
    assert '"stem": "Before?"' in content
    assert '"stem": "After?"' in content
    assert "PFQ-pediatrics-000000001" in content


def test_publish_preflight_is_dry_run_and_blocks_dirty_private_tree(tmp_path) -> None:
    result = publish_preflight(tmp_path)

    assert result["mode"] == "dry_run_only"
    assert result["ready"] is False
    assert result["public_worktree_configured"] is False


def test_live_publish_requires_explicit_environment_opt_in() -> None:
    assert live_publish_enabled({}) is False
    assert live_publish_enabled({"PREPFLOW_ENABLE_REPAIR_PUBLISH": "1"}) is True


def test_publisher_dry_run_never_writes_or_pushes(tmp_path) -> None:
    private = tmp_path / "private"; public = tmp_path / "public"
    for root in (private, public):
        root.mkdir()
        import subprocess
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    pack = private / "packs" / "pediatrics.prepflow.json"
    pack.parent.mkdir(); pack.write_text("{}", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "packs/pediatrics.prepflow.json"], cwd=private, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Initial"], cwd=private, check=True, capture_output=True)
    pack.write_text('{"repaired": true}', encoding="utf-8")
    result = publish_pack_repair(private, public, pack, environment={"PREPFLOW_ENABLE_REPAIR_PUBLISH": "1"}, dry_run=True)
    assert result["mode"] == "dry_run"
    assert not (public / "packs").exists()


def test_publisher_commits_and_pushes_only_the_repaired_pack_release(tmp_path) -> None:
    private_remote = tmp_path / "private.git"; public_remote = tmp_path / "public.git"
    for remote in (private_remote, public_remote):
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    private = tmp_path / "private"; public = tmp_path / "public"
    for remote, worktree in ((private_remote, private), (public_remote, public)):
        subprocess.run(["git", "clone", remote, worktree], check=True, capture_output=True)
    for root in (private, public):
        (root / "packs").mkdir(); (root / "web" / "data").mkdir(parents=True)
        shutil.copyfile(ROOT / "packs" / "pediatrics.prepflow.json", root / "packs" / "pediatrics.prepflow.json")
    (private / "docs").mkdir(); (private / "docs" / "REPAIR_LOG.md").write_text("# Published Pack Repair Log\n", encoding="utf-8")
    (private / "web" / "pack-precache.js").write_text("baseline\n", encoding="utf-8")
    for root in (private, public):
        _commit(root, "Initial")
        _run(root, "push", "origin", "HEAD:master")
    repaired = json.loads((private / "packs" / "pediatrics.prepflow.json").read_text(encoding="utf-8"))
    repaired["title"] = "Pediatrics Corrected"
    (private / "packs" / "pediatrics.prepflow.json").write_text(json.dumps(repaired), encoding="utf-8")
    (private / "docs" / "REPAIR_LOG.md").write_text("# Published Pack Repair Log\n\nRepair.\n", encoding="utf-8")
    (private / "web" / "pack-precache.js").write_text("changed\n", encoding="utf-8")

    result = publish_pack_repair(private, public, private / "packs" / "pediatrics.prepflow.json", environment={"PREPFLOW_ENABLE_REPAIR_PUBLISH": "1"})

    assert result["private_commit"] == _run(private_remote, "rev-parse", "master")
    assert result["public_commit"] == _run(public_remote, "rev-parse", "master")
    assert (private / "packs" / "pediatrics.prepflow.json").read_bytes() == (public / "packs" / "pediatrics.prepflow.json").read_bytes()
    assert (public / "web" / "data" / "pack-catalog.json").is_file()
    assert (public / "web" / "pack-precache.js").is_file()
