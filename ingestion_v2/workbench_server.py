from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from ingestion_v2.domain import DomainError
from ingestion_v2.workbench_session import SyntheticWorkbenchSession
from compiler.repair import load_pack


WORKBENCH_DIRECTORY = Path(__file__).with_name("workbench")
PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
IDENTITY_PACKS = {
    "fundamentals": PROJECT_DIRECTORY / "packs" / "fundamentals.prepflow.json",
    "medical_surgical": PROJECT_DIRECTORY / "packs" / "medical_surgical.prepflow.json",
}


class WorkbenchHandler(SimpleHTTPRequestHandler):
    session = SyntheticWorkbenchSession(workspace_root=Path("output/v2-runs"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WORKBENCH_DIRECTORY), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/review":
            self._send_json(self.session.view())
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
                if not isinstance(finding_id, str) or not isinstance(action, str):
                    raise DomainError("finding_id and action are required")
                payload = self.session.record_disposition(finding_id, action)
            elif self.path == "/api/candidate":
                payload = self.session.build_isolated_candidate()
            elif self.path == "/api/comparison":
                payload = self.session.compare_isolated_candidate()
            elif self.path == "/api/run/start":
                payload = self.session.start_run()
            elif self.path == "/api/run/complete":
                payload = self.session.complete_run()
            elif self.path == "/api/run/cleanup":
                payload = self.session.cleanup_run()
            elif self.path == "/api/identity/existing-pack":
                pack_id = body.get("pack_id")
                if pack_id not in IDENTITY_PACKS:
                    raise DomainError("Unknown protected Pack selection")
                payload = self.session.match_existing_pack(load_pack(IDENTITY_PACKS[pack_id]))
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
    parser = argparse.ArgumentParser(description="Run the local synthetic PrepFlow v2 workbench.")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkbenchHandler)
    print(f"PrepFlow v2 synthetic workbench: http://127.0.0.1:{args.port}/")
    print("In-memory synthetic mode; no persistence, Pack writes, or promotion.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
