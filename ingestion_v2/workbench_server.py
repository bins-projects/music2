from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from ingestion_v2.domain import DomainError
from ingestion_v2.workbench_session import SyntheticWorkbenchSession


WORKBENCH_DIRECTORY = Path(__file__).with_name("workbench")


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
