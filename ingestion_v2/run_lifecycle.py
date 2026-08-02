from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid

from ingestion_v2.domain import DomainError


FAILURE_CODE_RE = re.compile(r"^[a-z0-9_]{1,80}$")


class RunLifecycle:
    """Manage source-bearing artifacts inside one verified private run workspace."""

    FORMAT = "prepflow_v2_run"
    VERSION = "1.0"

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory

    @classmethod
    def create(cls, workspace_root: str | Path) -> "RunLifecycle":
        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise DomainError("Run workspace root must be a real directory")
        run_id = "v2-run-" + uuid.uuid4().hex
        run = root / run_id
        run.mkdir(mode=0o700)
        (run / "incoming").mkdir(mode=0o700)
        (run / "artifacts").mkdir(mode=0o700)
        lifecycle = cls(run)
        lifecycle._write_manifest(
            {
                "format": cls.FORMAT,
                "version": cls.VERSION,
                "run_id": run_id,
                "stage": "created",
                "status": "running",
                "source_type": None,
                "staged_copy_present": False,
                "raw_text_present": False,
                "cleaned_text_present": False,
                "promotion_available": False,
            }
        )
        return lifecycle

    @classmethod
    def open(cls, run_directory: str | Path) -> "RunLifecycle":
        lifecycle = cls(Path(run_directory))
        lifecycle.manifest()
        return lifecycle

    def manifest(self) -> dict:
        run = self._validated_run()
        path = run / "run.json"
        if path.is_symlink() or not path.is_file():
            raise DomainError("Run manifest is missing or unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DomainError("Run manifest is malformed") from error
        if (
            value.get("format") != self.FORMAT
            or value.get("version") != self.VERSION
            or value.get("run_id") != run.name
        ):
            raise DomainError("Run manifest identity is invalid")
        return value

    def stage_disposable_copy(self, content: bytes, *, source_type: str) -> dict:
        manifest = self._require_stage("created")
        if not content:
            raise DomainError("Disposable staging copy cannot be empty")
        if source_type not in {"pdf", "synthetic_text"}:
            raise DomainError("Unsupported source adapter type")
        staged = self._owned_path("incoming", "source.bin")
        with staged.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        manifest.update(
            stage="staged",
            source_type=source_type,
            staged_copy_present=True,
        )
        self._write_manifest(manifest)
        return manifest

    def record_extraction(self, text: str) -> dict:
        manifest = self._require_stage("staged")
        if not text:
            raise DomainError("Extraction output cannot be empty")
        self._atomic_write_text(self._owned_path("artifacts", "raw.txt"), text)
        manifest.update(
            stage="extracted",
            raw_text_present=True,
            extracted_characters=len(text),
        )
        self._write_manifest(manifest)
        return manifest

    def record_cleaning(self, text: str) -> dict:
        manifest = self._require_stage("extracted")
        if not text:
            raise DomainError("Cleaning output cannot be empty")
        self._atomic_write_text(self._owned_path("artifacts", "cleaned.txt"), text)
        self._unlink_owned("incoming", "source.bin")
        manifest.update(
            stage="cleaned",
            staged_copy_present=False,
            cleaned_text_present=True,
            cleaned_characters=len(text),
        )
        self._write_manifest(manifest)
        return manifest

    def record_review_ready(self, *, parsed_records: int, finding_count: int) -> dict:
        manifest = self._require_stage("cleaned")
        if parsed_records < 0 or finding_count < 0:
            raise DomainError("Run counts cannot be negative")
        manifest.update(
            stage="review_ready",
            parsed_records=parsed_records,
            finding_count=finding_count,
        )
        self._write_manifest(manifest)
        return manifest

    def record_candidate(self, *, question_count: int, unresolved_findings: int) -> dict:
        manifest = self._require_stage("review_ready")
        if question_count < 0 or unresolved_findings < 0:
            raise DomainError("Candidate counts cannot be negative")
        manifest.update(
            stage="candidate_built",
            candidate_question_count=question_count,
            unresolved_findings=unresolved_findings,
        )
        self._write_manifest(manifest)
        return manifest

    def record_comparison(self, *, field_changes: int, id_accounting_complete: bool) -> dict:
        manifest = self._require_stage("candidate_built")
        if field_changes < 0:
            raise DomainError("Comparison counts cannot be negative")
        manifest.update(
            stage="compared",
            comparison_field_changes=field_changes,
            id_accounting_complete=bool(id_accounting_complete),
        )
        self._write_manifest(manifest)
        return manifest

    def complete_and_cleanup(self) -> dict:
        manifest = self._require_stage("compared")
        self._unlink_owned("artifacts", "raw.txt")
        self._unlink_owned("artifacts", "cleaned.txt")
        self._unlink_owned("incoming", "source.bin")
        manifest.update(
            stage="completed",
            status="success",
            staged_copy_present=False,
            raw_text_present=False,
            cleaned_text_present=False,
            source_bearing_artifacts_removed=True,
            promotion_available=False,
        )
        self._write_manifest(manifest)
        return manifest

    def fail(self, failure_code: str) -> dict:
        manifest = self.manifest()
        if manifest["stage"] in {"completed", "failed_cleaned"}:
            raise DomainError("Completed or cleaned run cannot be failed")
        if not FAILURE_CODE_RE.fullmatch(failure_code):
            raise DomainError("Failure code must be source-neutral")
        manifest.update(
            failed_stage=manifest["stage"],
            stage="failed",
            status="failed",
            failure_code=failure_code,
            promotion_available=False,
        )
        self._write_manifest(manifest)
        return manifest

    def cleanup_failed_run(self) -> dict:
        manifest = self.manifest()
        if manifest.get("stage") != "failed" or manifest.get("status") != "failed":
            raise DomainError("Run must be at stage failed")
        self._unlink_owned("incoming", "source.bin")
        self._unlink_owned("artifacts", "raw.txt")
        self._unlink_owned("artifacts", "cleaned.txt")
        manifest.update(
            stage="failed_cleaned",
            staged_copy_present=False,
            raw_text_present=False,
            cleaned_text_present=False,
            source_bearing_artifacts_removed=True,
        )
        self._write_manifest(manifest)
        return manifest

    def _require_stage(self, expected: str) -> dict:
        manifest = self.manifest()
        if manifest.get("stage") != expected or manifest.get("status") != "running":
            raise DomainError(f"Run must be at stage {expected}")
        return manifest

    def _validated_run(self) -> Path:
        run = self.run_directory
        if run.is_symlink() or not run.is_dir() or not run.name.startswith("v2-run-"):
            raise DomainError("Run directory is missing or unsafe")
        for child in (run / "incoming", run / "artifacts"):
            if child.is_symlink() or not child.is_dir():
                raise DomainError("Run workspace boundary is missing or unsafe")
        return run

    def _owned_path(self, directory: str, filename: str) -> Path:
        run = self._validated_run()
        if directory not in {"incoming", "artifacts"}:
            raise DomainError("Unknown run artifact directory")
        allowed = {
            ("incoming", "source.bin"),
            ("artifacts", "raw.txt"),
            ("artifacts", "cleaned.txt"),
        }
        if (directory, filename) not in allowed:
            raise DomainError("Unknown run artifact name")
        parent = run / directory
        if parent.resolve(strict=True).parent != run.resolve(strict=True):
            raise DomainError("Run artifact directory escaped its boundary")
        return parent / filename

    def _unlink_owned(self, directory: str, filename: str) -> None:
        path = self._owned_path(directory, filename)
        if path.is_symlink():
            raise DomainError("Refusing to delete a symbolic-link artifact")
        if path.exists():
            if not path.is_file():
                raise DomainError("Refusing to delete a non-file artifact")
            path.unlink()

    def _atomic_write_text(self, path: Path, text: str) -> None:
        if path.exists() or path.is_symlink():
            raise DomainError("Run artifact already exists")
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists() or temporary.is_symlink():
            raise DomainError("Temporary run artifact already exists")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    def _write_manifest(self, value: dict) -> None:
        run = self._validated_run()
        path = run / "run.json"
        temporary = run / "run.json.tmp"
        if temporary.is_symlink():
            raise DomainError("Temporary manifest path is unsafe")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
