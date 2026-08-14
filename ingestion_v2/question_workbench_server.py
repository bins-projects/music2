"""HTTP surface for the private Repair and Add Questions Workbench."""
from __future__ import annotations

import argparse
import copy
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from compiler.repair import load_pack
from ingestion_v2.question_publisher import publication_readiness, publish_saved_operation
from ingestion_v2.question_workbench import (
    QuestionWorkbenchError, canonical_type_inventory, chapter_inventory, evaluate_answer,
    list_operations, operation_by_id, save_operation, search_questions, update_operation,
)
from ingestion_v2.workbench_server import WorkbenchHandler, PROJECT_DIRECTORY
from tools.pack_catalog import installed_pack_registry


UI_DIRECTORY = Path(__file__).with_name("question_workbench_ui")
LEDGER_PATH = Path(os.environ.get("PREPFLOW_QUESTION_LEDGER", PROJECT_DIRECTORY / "output" / "question-workbench" / "operations.json"))


def installed_packs() -> tuple[dict[str, Path], dict[str, dict]]:
    registry = installed_pack_registry(PROJECT_DIRECTORY / "packs")
    return registry, {pack_id: load_pack(path) for pack_id, path in registry.items()}


def configured_public_worktree() -> Path | None:
    value = os.environ.get("PREPFLOW_PUBLIC_WORKTREE")
    return Path(value).resolve() if value else None


class QuestionWorkbenchHandler(WorkbenchHandler):
    def __init__(self, *args, **kwargs):
        super(WorkbenchHandler, self).__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def _readiness(self) -> dict:
        return publication_readiness(PROJECT_DIRECTORY, configured_public_worktree())

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "scope": "local_only"}); return
        if parsed.path == "/api/question-workbench":
            registry, packs = installed_packs()
            readiness = self._readiness()
            operations = list_operations(LEDGER_PATH)
            self._send_json({
                "packs": [{"id": pack_id, "title": pack.get("title", pack_id),
                           "chapters": chapter_inventory(pack), "question_count": len(pack["questions"])}
                          for pack_id, pack in packs.items()],
                "types": canonical_type_inventory(packs), "operations": operations,
                "readiness": readiness,
            }); return
        if parsed.path == "/api/question-workbench/readiness":
            self._send_json(self._readiness()); return
        if parsed.path == "/api/question-workbench/search":
            query = parse_qs(parsed.query)
            pack_id, text = query.get("pack_id", [""])[0], query.get("q", [""])[0]
            _, packs = installed_packs()
            if pack_id not in packs:
                self._send_json({"error": "Selected Pack is unavailable"}, status=400); return
            self._send_json({"results": search_questions(pack_id, packs[pack_id], text)}); return
        if parsed.path == "/api/question-workbench/question":
            query = parse_qs(parsed.query)
            pack_id, question_id = query.get("pack_id", [""])[0], query.get("question_id", [""])[0]
            registry, packs = installed_packs()
            question = next((copy.deepcopy(item) for item in packs.get(pack_id, {}).get("questions", []) if item.get("id") == question_id), None)
            if question is None:
                self._send_json({"error": "Question was not found"}, status=404); return
            self._send_json({"pack_id": pack_id, "question": question,
                             "pack_sha256": hashlib.sha256(registry[pack_id].read_bytes()).hexdigest()}); return
        if parsed.path == "/api/question-workbench/operation":
            operation_id = parse_qs(parsed.query).get("operation_id", [""])[0]
            try: self._send_json(operation_by_id(LEDGER_PATH, operation_id))
            except QuestionWorkbenchError as error: self._send_json({"error": str(error)}, status=404)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if not self.path.startswith("/api/question-workbench/"):
            super().do_POST(); return
        try:
            body = self._read_json()
            if self.path == "/api/question-workbench/grade":
                self._send_json(evaluate_answer(body.get("question") or {}, body.get("answer"))); return
            if self.path in {"/api/question-workbench/save", "/api/question-workbench/action"}:
                registry, packs = installed_packs()
                pack_id = str(body.get("pack_id") or "")
                if pack_id not in packs: raise QuestionWorkbenchError("Selected Pack is unavailable")
                operation_type = str(body.get("operation_type") or "")
                original = None
                if operation_type == "repair":
                    question_id = str((body.get("question") or {}).get("id") or "")
                    original = next((copy.deepcopy(item) for item in packs[pack_id]["questions"] if item.get("id") == question_id), None)
                    existing_id = body.get("operation_id")
                    if existing_id:
                        original = operation_by_id(LEDGER_PATH, str(existing_id)).get("original_question")
                    if original is None: raise QuestionWorkbenchError("Repair target was not found")
                readiness = self._readiness()
                operation = save_operation(
                    LEDGER_PATH, operation_type=operation_type, pack_id=pack_id, pack=packs[pack_id],
                    question=body.get("question") or {}, original_question=original,
                    operation_id=body.get("operation_id"), blocker=readiness.get("reason"),
                )
                if self.path.endswith("/action"):
                    readiness = self._readiness()
                    if readiness["ready"]:
                        result = publish_saved_operation(PROJECT_DIRECTORY, configured_public_worktree(), LEDGER_PATH,
                                                         operation["operation_id"], readiness=readiness)
                        operation = operation_by_id(LEDGER_PATH, operation["operation_id"])
                        self._send_json({"operation": operation, "readiness": self._readiness(), "publication": result}); return
                    operation = update_operation(LEDGER_PATH, operation["operation_id"], blocker=readiness.get("reason"))
                self._send_json({"operation": operation, "readiness": readiness}, status=201); return
            if self.path == "/api/question-workbench/publish":
                operation_id = str(body.get("operation_id") or "")
                operation = operation_by_id(LEDGER_PATH, operation_id)
                stage = (operation.get("publication") or {}).get("stage")
                recovering = operation.get("state") == "publishing" and stage in {"private_committed", "private_published", "public_committed"}
                readiness = self._readiness()
                if not readiness["ready"] and not recovering:
                    self._send_json({"error": readiness["reason"], "readiness": readiness}, status=409); return
                result = publish_saved_operation(PROJECT_DIRECTORY, configured_public_worktree(), LEDGER_PATH,
                                                 operation_id, readiness={"ready": True} if recovering else readiness)
                self._send_json({"operation": operation_by_id(LEDGER_PATH, operation_id), "publication": result,
                                 "readiness": self._readiness()}); return
            self._send_json({"error": "Unknown question Workbench action"}, status=404)
        except (QuestionWorkbenchError, ValueError, RuntimeError) as error:
            self._send_json({"error": str(error)}, status=400)


def main() -> None:
    from http.server import ThreadingHTTPServer
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), QuestionWorkbenchHandler)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
