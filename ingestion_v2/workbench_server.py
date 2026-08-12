from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pypdf import PdfReader
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ingestion_v2.domain import DomainError
from ingestion_v2.recovery import list_completed_runs, list_recoverable_runs
from ingestion_v2.workbench_session import SyntheticWorkbenchSession
from compiler.repair import load_pack
from ingestion_v2.repair_desk import load_json, reconcile_repairs, repair_desk_lookup


WORKBENCH_DIRECTORY = Path(__file__).with_name("workbench")
PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
PACK_REGISTRY = {
    "fundamentals": PROJECT_DIRECTORY / "packs" / "fundamentals.prepflow.json",
    "medical_surgical": PROJECT_DIRECTORY / "packs" / "medical_surgical.prepflow.json",
    "pharmacy": PROJECT_DIRECTORY / "packs" / "pharmacy.prepflow.json",
}
IDENTITY_PACKS = PACK_REGISTRY
SOURCE_ONLY_PRESETS = {
    "peds": {"display_name": "Pediatrics", "slug": "pediatrics", "prefix": "Peds"},
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


def validated_existing_extraction(path: Path, filename: str) -> tuple[str, str, int] | None:
    """Return a reusable extraction only when its source identity is exact."""
    benchmark = PRIVATE_SOURCE_DIRECTORY / "pediatrics-ocr-source-only-20260809-091026" / "extraction-benchmark.json"
    text_path = benchmark.parent / "tesseract_ocr_v1.txt"
    if filename != "pediatrics.pdf" or not benchmark.is_file() or not text_path.is_file():
        return None
    try:
        record = json.loads(benchmark.read_text(encoding="utf-8"))
        source = record["source_pdf"]
        summary = record["candidates"]["tesseract_ocr_v1"]["summary"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pages = len(PdfReader(str(path)).pages)
    except Exception:
        return None
    if not (
        source.get("filename") == filename
        and source.get("sha256") == digest
        and source.get("bytes") == path.stat().st_size
        and summary.get("page_count") == pages
    ):
        return None
    text = text_path.read_text(encoding="utf-8")
    if not text or len(text.split("\f")) != pages:
        return None
    return text, "tesseract_ocr_v1", pages
REPAIR_WORKBENCH_DIRECTORY = PROJECT_DIRECTORY / "output" / "repair-workbench" / "fundamentals"


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
            canonical = [load_pack(path) for path in IDENTITY_PACKS.values()]
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
            self._send_json({"packs": [{"id": key, "source_only": False} for key in PACK_REGISTRY] + [{"id": key, "source_only": True, "metadata": value} for key, value in SOURCE_ONLY_PRESETS.items()] + [{"id": "new_source", "source_only": True}]})
            return
        if self.path == "/api/review":
            self._send_json(self.session.view())
            return
        if self.path == "/api/runs/resumable":
            self._send_json(
                {"runs": list(list_recoverable_runs(RUNS_DIRECTORY, set(IDENTITY_PACKS)))}
            )
            return
        if self.path == "/api/runs":
            protected = set(IDENTITY_PACKS)
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
                        payload = self.session.materialize_source_only(
                            filename_metadata(filename),
                            registered_preset=filename == "pediatrics.pdf",
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
            if self.path == "/api/actions":
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
                resumed = (SyntheticWorkbenchSession.resume_source_only_run(run_directory)
                    if pack_id == "source_only" else SyntheticWorkbenchSession.resume_run(run_directory, load_pack(IDENTITY_PACKS[pack_id])) if pack_id in IDENTITY_PACKS else None)
                if resumed is None:
                    raise DomainError("Unknown protected Pack selection")
                type(self).session = resumed
                payload = resumed.view()
            elif self.path == "/api/identity/existing-pack":
                pack_id = body.get("pack_id")
                if pack_id not in IDENTITY_PACKS:
                    raise DomainError("Unknown protected Pack selection")
                payload = self.session.match_existing_pack(load_pack(IDENTITY_PACKS[pack_id]))
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkbenchHandler)
    print(f"PrepFlow v2 private workbench: http://127.0.0.1:{args.port}/")
    print("Private checkpoints enabled; no canonical Pack writes or promotion.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
