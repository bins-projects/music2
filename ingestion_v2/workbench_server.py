from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import os
import tempfile
from pypdf import PdfReader
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ingestion_v2.domain import DomainError
from ingestion_v2.recovery import list_completed_runs, list_recoverable_runs
from ingestion_v2.workbench_session import SyntheticWorkbenchSession
from compiler.repair import RepairError, find_question, load_pack, validate_candidate_question
from ingestion_v2.repair_desk import load_json, reconcile_repairs, repair_desk_lookup
from ingestion_v2.repair_publish import append_repair_log, repair_log_entry
from ingestion_v2.repair_publish import live_publish_enabled, publish_pack_repair, publish_preflight
from tools.pack_catalog import installed_pack_registry


WORKBENCH_DIRECTORY = Path(__file__).with_name("workbench")
PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
PACK_DIRECTORY = PROJECT_DIRECTORY / "packs"
REPAIR_LOG_PATH = PROJECT_DIRECTORY / "docs" / "REPAIR_LOG.md"


def installed_identity_packs() -> dict[str, Path]:
    """Discover the same validated installed Packs used by the study app."""
    try:
        return installed_pack_registry(PACK_DIRECTORY)
    except ValueError as error:
        raise DomainError(str(error)) from error
SOURCE_ONLY_PRESETS = {
    "peds": {"display_name": "Pediatrics", "slug": "pediatrics", "prefix": "Peds"},
}
APPROVED_SOURCE_METADATA = {
    # These are source names only; content continues through the generic
    # source-first workflow and never inherits wording from an old Pack.
    "fundimentals.pdf": {"display_name": "Fundamentals", "slug": "fundamentals", "prefix": "Fundamentals"},
    "medsurg.pdf": {"display_name": "Medical-Surgical", "slug": "medical_surgical", "prefix": "Med-Surg"},
    "pharmfinal.pdf": {"display_name": "Pharmacy", "slug": "pharmacy", "prefix": "Pharm"},
    "pediatrics.pdf": {"display_name": "Pediatrics", "slug": "pediatrics", "prefix": "Peds"},
}
RUNS_DIRECTORY = PROJECT_DIRECTORY / "output" / "v2-runs"
PRIVATE_SOURCE_DIRECTORY = PROJECT_DIRECTORY / "private_sources"
CENTRAL_SOURCE_DIRECTORY = Path("/home/charliekeila/projects/prepflow-sources")


def approved_pdf_sources(
    roots: tuple[Path, ...] | Path = (CENTRAL_SOURCE_DIRECTORY, PRIVATE_SOURCE_DIRECTORY),
) -> tuple[tuple[str, Path, str, int | None, str], ...]:
    """List approved local PDFs without exposing their filesystem paths."""
    if isinstance(roots, Path):
        roots = (roots,)
    sources = []
    for root in roots:
        if not root.is_dir():
            continue
        location = "Central source book" if root == CENTRAL_SOURCE_DIRECTORY else "Approved sample"
        for path in sorted(root.rglob("*.pdf"), key=lambda item: item.name.casefold()):
            if path.is_symlink() or not path.is_file():
                continue
            token = hashlib.sha256(f"{root.name}/{path.relative_to(root)}".encode("utf-8")).hexdigest()[:16]
            try:
                page_count = len(PdfReader(str(path)).pages)
            except Exception:
                page_count = None
            sources.append((token, path, path.name, page_count, location))
    return tuple(sorted(sources, key=lambda item: (item[4] != "Central source book", item[2].casefold())))


def filename_metadata(filename: str) -> dict:
    stem = Path(filename).stem
    display_name = " ".join(part for part in stem.replace("_", " ").replace("-", " ").split() if part).title() or "New source"
    slug = "".join(character for character in stem.casefold().replace("-", "_") if character.isalnum() or character == "_").strip("_")[:40] or "new_source"
    return {"display_name": display_name, "slug": slug, "prefix": display_name[:32]}


def approved_source_metadata(filename: str) -> tuple[dict, bool]:
    metadata = APPROVED_SOURCE_METADATA.get(filename.casefold())
    return (dict(metadata), True) if metadata else (filename_metadata(filename), False)


def _artifact_priority(path: Path) -> tuple[int, str]:
    """Prefer explicitly stabilized extraction artifacts when duplicates exist."""
    name = path.parent.name.casefold()
    if "-final-" in name or name.endswith("-final"):
        return (0, name)
    if "cleaner-ab" in name or "ocr-source-only" in name:
        return (1, name)
    if "source-only" in name:
        return (2, name)
    return (3, name)


def validated_existing_extraction(
    path: Path, filename: str, *, artifact_root: Path = PRIVATE_SOURCE_DIRECTORY,
) -> tuple[str, str, int] | None:
    """Reuse only saved text proven identical to the selected PDF.

    Filename is not identity: SHA-256, byte size, page count, and saved text
    page structure must agree. Historical Pack content is not consulted.
    """
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        byte_count = path.stat().st_size
        pages = len(PdfReader(str(path)).pages)
    except Exception:
        return None
    matches = []
    for benchmark in artifact_root.rglob("extraction-benchmark.json"):
        if benchmark.is_symlink() or not benchmark.is_file():
            continue
        try:
            record = json.loads(benchmark.read_text(encoding="utf-8"))
            source = record["source_pdf"]
            if source.get("sha256") != digest or source.get("bytes") != byte_count:
                continue
            for adapter_name, candidate in record.get("candidates", {}).items():
                summary = candidate.get("summary", {})
                text_path = benchmark.parent / candidate.get("raw_text_file", "")
                if (candidate.get("status") != "completed" or summary.get("page_count") != pages
                    or text_path.is_symlink() or not text_path.is_file()):
                    continue
                text = text_path.read_text(encoding="utf-8")
                if text and len(text.split("\f")) == pages:
                    matches.append((_artifact_priority(benchmark), adapter_name, text))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    if not matches:
        return None
    _, adapter_name, text = min(matches, key=lambda item: (item[0], item[1]))
    return text, adapter_name, pages
REPAIR_WORKBENCH_DIRECTORY = PROJECT_DIRECTORY / "output" / "repair-workbench" / "fundamentals"


def canonical_pack_question(question_id: str) -> tuple[str, Path, dict, dict]:
    """Resolve one immutable ID to exactly one installed canonical Pack."""
    matches = []
    for pack_id, path in installed_identity_packs().items():
        pack = load_pack(path)
        try:
            question = find_question(pack, question_id)
        except RepairError as error:
            if str(error).startswith("Question not found:"):
                continue
            raise DomainError(str(error)) from error
        matches.append((pack_id, path, pack, question))
    if not matches:
        raise DomainError(f"Installed Pack question not found: {question_id}")
    if len(matches) != 1:
        raise DomainError(f"Question ID is not unique across installed Packs: {question_id}")
    return matches[0]


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def replace_canonical_pack_question(
    question_id: str,
    values: dict,
    expected_pack_sha256: str,
    *,
    registry: dict[str, Path] | None = None,
    backup_root: Path | None = None,
    repair_log_path: Path | None = None,
) -> dict:
    """Atomically replace one canonical question while preserving ID and order."""
    registry = installed_identity_packs() if registry is None else registry
    matches = []
    for pack_id, path in registry.items():
        pack = load_pack(path)
        try:
            question = find_question(pack, question_id)
        except RepairError as error:
            if str(error).startswith("Question not found:"):
                continue
            raise DomainError(str(error)) from error
        matches.append((pack_id, path, pack, question))
    if len(matches) != 1:
        message = "not found" if not matches else "not unique"
        raise DomainError(f"Installed Pack question is {message}: {question_id}")
    pack_id, path, pack, original = matches[0]
    original_bytes = path.read_bytes()
    current_sha256 = hashlib.sha256(original_bytes).hexdigest()
    if expected_pack_sha256 != current_sha256:
        raise DomainError("Pack changed after lookup; search again before replacing the question")
    if not isinstance(values, dict):
        raise DomainError("Complete replacement values are required")

    replacement = copy.deepcopy(original)
    for field in ("stem", "rationale"):
        if not isinstance(values.get(field), str):
            raise DomainError(f"Replacement {field} must be text")
        replacement[field] = values[field].strip()
    choices = values.get("choices")
    answers = values.get("correct_answers")
    if not isinstance(choices, list) or not all(
        isinstance(item, dict) and isinstance(item.get("label"), str)
        and isinstance(item.get("text"), str) for item in choices
    ):
        raise DomainError("Replacement choices are malformed")
    if not isinstance(answers, list) or not all(isinstance(item, str) for item in answers):
        raise DomainError("Replacement correct answers are malformed")
    replacement["choices"] = [
        {"label": item["label"].strip().upper(), "text": item["text"].strip()}
        for item in choices
    ]
    replacement["correct_answers"] = [item.strip() for item in answers]
    replacement["id"] = question_id
    try:
        validate_candidate_question(replacement)
    except RepairError as error:
        raise DomainError(str(error)) from error

    updated = copy.deepcopy(pack)
    indexes = [
        index for index, question in enumerate(updated["questions"])
        if question.get("id") == question_id
    ]
    if len(indexes) != 1:
        raise DomainError(f"Question ID is not unique inside Pack: {question_id}")
    updated["questions"][indexes[0]] = replacement
    ids = [question.get("id") for question in updated["questions"]]
    if len(ids) != len(set(ids)):
        raise DomainError("Pack contains duplicate question IDs")
    try:
        for question in updated["questions"]:
            validate_candidate_question(question)
    except RepairError as error:
        raise DomainError(f"Pack validation failed: {error}") from error

    encoded = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    backup_directory = backup_root or (PROJECT_DIRECTORY / "output" / "pack-backups")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_directory / f"{pack_id}-{stamp}-{current_sha256[:12]}.prepflow.json"
    _atomic_write_bytes(backup_path, original_bytes)
    _atomic_write_bytes(path, encoded)
    log_path = repair_log_path or REPAIR_LOG_PATH
    append_repair_log(log_path, repair_log_entry(
        pack_id=pack_id,
        question_id=question_id,
        previous_question=original,
        replacement_question=replacement,
        pack_sha256_before=current_sha256,
        pack_sha256_after=hashlib.sha256(encoded).hexdigest(),
    ))
    backup_label = (
        str(backup_path.relative_to(PROJECT_DIRECTORY))
        if backup_path.is_relative_to(PROJECT_DIRECTORY)
        else str(backup_path)
    )
    return {
        "status": "replaced_in_pack",
        "pack_id": pack_id,
        "question_id": question_id,
        "question": replacement,
        "question_count": len(updated["questions"]),
        "pack_sha256": hashlib.sha256(encoded).hexdigest(),
        "backup": backup_label,
        "repair_log": str(log_path.relative_to(PROJECT_DIRECTORY)) if log_path.is_relative_to(PROJECT_DIRECTORY) else str(log_path),
    }


class WorkbenchHandler(SimpleHTTPRequestHandler):
    session = SyntheticWorkbenchSession(workspace_root=RUNS_DIRECTORY)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WORKBENCH_DIRECTORY), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "scope": "local_only"})
            return
        if parsed.path == "/api/repair-desk":
            query = parse_qs(parsed.query).get("q", [""])[0]
            identity_packs = installed_identity_packs()
            canonical = [load_pack(path) for path in identity_packs.values()]
            candidate_path = REPAIR_WORKBENCH_DIRECTORY / "candidate.prepflow.json"
            records_path = REPAIR_WORKBENCH_DIRECTORY / "repair-records.json"
            candidate = load_json(candidate_path) if candidate_path.is_file() else None
            records = load_json(records_path) if records_path.is_file() else None
            prefixes = dict(SOURCE_ONLY_PRESETS)
            friendly_prefixes = {value["slug"]: value["prefix"] for value in prefixes.values()}
            if self.session._source_metadata:
                friendly_prefixes[self.session._source_metadata["slug"]] = self.session._source_metadata["prefix"]
            payload = repair_desk_lookup(query, canonical_packs=canonical, candidate_pack=candidate, repair_records=records, friendly_prefixes=friendly_prefixes)
            if candidate and records:
                payload["reconciliation"] = reconcile_repairs(records, canonical[0], candidate)
            self._send_json(payload)
            return
        if parsed.path == "/api/repair-desk/question":
            question_id = parse_qs(parsed.query).get("question_id", [""])[0]
            if not question_id:
                self._send_json({"error": "question_id is required"}, status=400)
                return
            try:
                pack_id, path, _, question = canonical_pack_question(question_id)
                self._send_json({
                    "pack_id": pack_id,
                    "question_id": question_id,
                    "question": question,
                    "pack_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
            except DomainError as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/candidate/inspection":
            self._send_json(self.session.candidate_inspection())
            return
        if parsed.path == "/api/private-sources":
            self._send_json(
                {
                    "sources": [
                        {
                            "id": token,
                            "filename": name,
                            "page_count": pages,
                            "kind": kind,
                            # This is only a readiness hint for the local UI.  The
                            # start route validates the source again before reuse.
                            "existing_extraction_available": bool(
                                validated_existing_extraction(path, name)
                            ),
                        }
                        for token, path, name, pages, kind in approved_pdf_sources()
                    ]
                }
            )
            return
        if parsed.path == "/api/pack-registry":
            self._send_json({"packs": [{"id": key, "source_only": False} for key in installed_identity_packs()] + [{"id": key, "source_only": True, "metadata": value} for key, value in SOURCE_ONLY_PRESETS.items()] + [{"id": "new_source", "source_only": True}]})
            return
        if parsed.path == "/api/repair-publish/preflight":
            configured = os.environ.get("PREPFLOW_PUBLIC_WORKTREE")
            self._send_json(publish_preflight(PROJECT_DIRECTORY, Path(configured) if configured else None))
            return
        if parsed.path == "/api/repair-publish/status":
            self._send_json({"live_publish_enabled": live_publish_enabled(dict(os.environ))})
            return
        if self.path == "/api/review":
            self._send_json(self.session.view())
            return
        if self.path == "/api/runs/resumable":
            self._send_json(
                {"runs": list(list_recoverable_runs(RUNS_DIRECTORY, set(installed_identity_packs())))}
            )
            return
        if self.path == "/api/runs":
            protected = set(installed_identity_packs())
            self._send_json(
                {
                    "resumable": list(list_recoverable_runs(RUNS_DIRECTORY, protected)),
                    "completed": list(list_completed_runs(RUNS_DIRECTORY, protected)),
                }
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            if self.path == "/api/run/start-pdf":
                payload = self.session.start_pdf_run(self._read_pdf_body())
                self._send_json(payload)
                return
            body = self._read_json()
            if self.path == "/api/run/start-approved-pdf":
                source_id = body.get("source_id")
                source = next((item for item in approved_pdf_sources() if item[0] == source_id), None)
                if source is None:
                    raise DomainError("Selected private PDF is unavailable")
                _, path, filename, _, _ = source
                reuse = validated_existing_extraction(path, filename)
                prior_run_id = self.session.view()["run"].get("run_id")
                try:
                    payload = (
                        self.session.start_pdf_run_from_existing_extraction(
                            path.read_bytes(), reuse[0], adapter_name=reuse[1], page_count=reuse[2]
                        )
                        if reuse else self.session.start_pdf_run(path.read_bytes())
                    )
                    if payload["run"]["state"] != "failed":
                        source_metadata, registered_preset = approved_source_metadata(filename)
                        payload = self.session.materialize_source_only(
                            source_metadata,
                            registered_preset=registered_preset,
                        )
                except Exception as error:
                    # This endpoint owns the newly created run.  Do not leave an
                    # unreviewable partial intake behind if post-extraction setup fails.
                    current_run = self.session.view()["run"]
                    if current_run.get("run_id") != prior_run_id and current_run["state"] not in {"not_started", "completed"}:
                        self.session.cleanup_run()
                    raise DomainError(f"Book setup failed; the temporary run was cleaned: {error}") from error
                payload["intake"] = {
                    "extraction": "reused_validated_existing" if reuse else "fresh_native_extraction",
                    "message": "Using existing extraction" if reuse else "No validated existing extraction; using fresh extraction",
                }
                self._send_json(payload)
                return
            if self.path == "/api/repair-desk/replace":
                question_id = body.get("question_id")
                pack_sha256 = body.get("pack_sha256")
                if not isinstance(question_id, str) or not isinstance(pack_sha256, str):
                    raise DomainError("question_id and pack_sha256 are required")
                payload = replace_canonical_pack_question(
                    question_id, body.get("values"), pack_sha256
                )
            elif self.path == "/api/repair-publish":
                pack_id = body.get("pack_id")
                configured = os.environ.get("PREPFLOW_PUBLIC_WORKTREE")
                packs = installed_identity_packs()
                if not isinstance(pack_id, str) or pack_id not in packs:
                    raise DomainError("Installed Pack selection is required")
                if not configured:
                    raise DomainError("Public release worktree is not configured")
                try:
                    payload = publish_pack_repair(
                        PROJECT_DIRECTORY, Path(configured), packs[pack_id], environment=dict(os.environ)
                    )
                except RuntimeError as error:
                    raise DomainError(str(error)) from error
            elif self.path == "/api/actions":
                finding_id = body.get("finding_id")
                if not isinstance(finding_id, str):
                    raise DomainError("finding_id is required")
                action = body.get("action")
                if not isinstance(action, str):
                    raise DomainError("action is required")
                payload = self.session.record_action(finding_id, action)
            elif self.path == "/api/verifications":
                finding_id = body.get("finding_id")
                if not isinstance(finding_id, str):
                    raise DomainError("finding_id is required")
                payload = self.session.record_verification(finding_id)
            elif self.path == "/api/dispositions":
                finding_id = body.get("finding_id")
                action = body.get("action")
                target_question_id = body.get("target_question_id")
                if not isinstance(finding_id, str) or not isinstance(action, str):
                    raise DomainError("finding_id and action are required")
                if target_question_id is not None and not isinstance(target_question_id, str):
                    raise DomainError("target_question_id must be a string")
                payload = self.session.record_disposition(
                    finding_id, action, target_question_id
                )
            elif self.path == "/api/candidate":
                payload = self.session.build_isolated_candidate()
            elif self.path == "/api/comparison":
                payload = self.session.compare_isolated_candidate()
            elif self.path == "/api/comparison/groups/approve":
                group_id = body.get("group_id")
                if not isinstance(group_id, str):
                    raise DomainError("group_id is required")
                payload = self.session.approve_comparison_group(group_id)
            elif self.path == "/api/comparison/categories/approve":
                category_id = body.get("category_id")
                action = body.get("action")
                if not isinstance(category_id, str) or not isinstance(action, str):
                    raise DomainError("category_id and action are required")
                payload = self.session.approve_comparison_category(category_id, action)
            elif self.path == "/api/comparison/categories/source-page":
                category_id = body.get("category_id")
                if not isinstance(category_id, str):
                    raise DomainError("category_id is required")
                payload = self.session.view_comparison_source(category_id)
            elif self.path == "/api/run/start":
                payload = self.session.start_run()
            elif self.path == "/api/run/complete":
                payload = self.session.complete_run()
            elif self.path == "/api/run/cleanup":
                payload = self.session.cleanup_run()
            elif self.path == "/api/run/resume":
                run_id = body.get("run_id")
                pack_id = body.get("pack_id")
                if not isinstance(run_id, str) or not isinstance(pack_id, str):
                    raise DomainError("A private run ID and intake type are required")
                run_directory = RUNS_DIRECTORY / run_id
                if run_directory.parent != RUNS_DIRECTORY or not run_id.startswith("v2-run-"):
                    raise DomainError("Private run ID is invalid")
                identity_packs = installed_identity_packs()
                resumed = (SyntheticWorkbenchSession.resume_source_only_run(run_directory)
                    if pack_id == "source_only" else SyntheticWorkbenchSession.resume_run(run_directory, load_pack(identity_packs[pack_id])) if pack_id in identity_packs else None)
                if resumed is None:
                    raise DomainError("Unknown protected Pack selection")
                type(self).session = resumed
                payload = resumed.view()
            elif self.path == "/api/identity/existing-pack":
                pack_id = body.get("pack_id")
                identity_packs = installed_identity_packs()
                if pack_id not in identity_packs:
                    raise DomainError("Unknown protected Pack selection")
                payload = self.session.match_existing_pack(load_pack(identity_packs[pack_id]))
            elif self.path == "/api/identity/source-only":
                metadata = body.get("metadata")
                if not isinstance(metadata, dict):
                    raise DomainError("source metadata is required")
                preset = body.get("preset")
                if preset is not None and preset not in SOURCE_ONLY_PRESETS:
                    raise DomainError("Unknown source-only preset")
                if preset is not None and metadata != SOURCE_ONLY_PRESETS[preset]:
                    raise DomainError("Registered source metadata cannot be changed")
                payload = self.session.materialize_source_only(metadata, registered_preset=bool(preset))
            elif self.path == "/api/identity/source-context":
                record_id = body.get("record_id")
                if not isinstance(record_id, str):
                    raise DomainError("record_id is required")
                payload = self.session.view_identity_source_context(record_id)
            elif self.path == "/api/identity/actions":
                record_id = body.get("record_id")
                action = body.get("action")
                target_question_id = body.get("target_question_id")
                if not isinstance(record_id, str) or not isinstance(action, str):
                    raise DomainError("record_id and action are required")
                if target_question_id is not None and not isinstance(target_question_id, str):
                    raise DomainError("target_question_id must be a string")
                payload = self.session.record_identity_action(record_id, action, target_question_id)
            elif self.path == "/api/identity/repairs":
                record_id = body.get("record_id")
                field = body.get("field")
                explanation = body.get("explanation")
                if not isinstance(record_id, str) or not isinstance(field, str) or not isinstance(explanation, str):
                    raise DomainError("record_id, field, and explanation are required")
                payload = self.session.draft_identity_field_repair(record_id, field, body.get("proposed_after"), explanation)
            elif self.path == "/api/identity/materialize":
                payload = self.session.materialize_identity_review()
            elif self.path == "/api/proposals":
                finding_id = body.get("finding_id")
                explanation = body.get("explanation")
                verification = body.get("requires_source_verification")
                if not isinstance(finding_id, str) or not isinstance(explanation, str):
                    raise DomainError("finding_id and explanation are required")
                payload = self.session.draft_user_proposal(
                    finding_id,
                    body.get("proposed_after"),
                    explanation,
                    requires_source_verification=verification,
                )
            elif self.path == "/api/question-repairs":
                question_id = body.get("question_id")
                values = body.get("values")
                if not isinstance(question_id, str) or not isinstance(values, dict):
                    raise DomainError("question_id and complete question values are required")
                payload = self.session.save_complete_question_repair(question_id, values)
            elif self.path == "/api/question-repairs/undo":
                question_id = body.get("question_id")
                if not isinstance(question_id, str):
                    raise DomainError("question_id is required")
                payload = self.session.undo_complete_question_repair(question_id)
            elif self.path == "/api/questions/accept-as-is":
                question_id = body.get("question_id")
                if not isinstance(question_id, str):
                    raise DomainError("question_id is required")
                payload = self.session.accept_question_as_is(question_id)
            elif self.path == "/api/chapters/edit":
                if not all(isinstance(body.get(key), int) for key in ("chapter", "new_chapter")) or not all(isinstance(body.get(key), str) for key in ("title", "new_title")):
                    raise DomainError("chapter, title, new_chapter, and new_title are required")
                payload = self.session.edit_chapter(body["chapter"], body["title"], body["new_chapter"], body["new_title"])
            elif self.path == "/api/chapters/undo":
                if not isinstance(body.get("original_chapter"), int) or not isinstance(body.get("original_title"), str):
                    raise DomainError("original_chapter and original_title are required")
                payload = self.session.undo_chapter_edit(body["original_chapter"], body["original_title"])
            elif self.path == "/api/questions/chapter":
                if not isinstance(body.get("question_id"), str) or not isinstance(body.get("chapter"), int) or not isinstance(body.get("title"), str):
                    raise DomainError("question_id, chapter, and title are required")
                payload = self.session.reassign_question_chapter(body["question_id"], body["chapter"], body["title"])
            elif self.path == "/api/source-page":
                finding_id = body.get("finding_id")
                if not isinstance(finding_id, str):
                    raise DomainError("finding_id is required")
                payload = self.session.view_source_page(finding_id)
            else:
                self._send_json({"error": "not_found"}, status=404)
                return
            self._send_json(payload)
        except (DomainError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)

    def log_message(self, format: str, *args) -> None:
        return

    def end_headers(self) -> None:
        # The private local workbench is actively developed and restores the
        # current checkpoint on restart.  Cached HTML/JavaScript can otherwise
        # present controls from a prior server version against that live run.
        # Never let a browser or a service worker retain a stale review UI.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 16_384:
            raise DomainError("Request body size is invalid")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise DomainError("Request body must be an object")
        return value

    def _read_pdf_body(self) -> bytes:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/pdf":
            raise DomainError("PDF intake requires application/pdf bytes")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise DomainError("PDF request size is invalid") from error
        if length <= 0 or length > 250 * 1024 * 1024:
            raise DomainError("PDF must be between 1 byte and 250 MiB")
        data = self.rfile.read(length)
        if len(data) != length:
            raise DomainError("PDF request ended before all bytes arrived")
        return data

    def _send_json(self, payload: dict, *, status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local private PrepFlow v2 workbench.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "0.0.0.0"),
        default="127.0.0.1",
        help="Bind address; use 0.0.0.0 only behind a private forwarded port.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535")
    if args.host == "127.0.0.1":
        # Keep the ordinary local launch loopback-only.
        server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkbenchHandler)
    else:
        # Codespaces requires an all-interface bind before its private port
        # forwarder can reach the process.
        server = ThreadingHTTPServer((args.host, args.port), WorkbenchHandler)
    print(f"PrepFlow v2 private workbench: http://{args.host}:{args.port}/")
    print("Private checkpoints enabled; direct Pack replacement requires explicit confirmation.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
