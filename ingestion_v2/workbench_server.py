from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
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
