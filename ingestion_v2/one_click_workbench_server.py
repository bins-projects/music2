"""Unified Workbench entry point with trusted-operator question actions."""
from __future__ import annotations

import copy
from http.server import ThreadingHTTPServer

from ingestion_v2 import workbench_server as base
from ingestion_v2.one_click_question_actions import (
    apply_canonical_operation,
    discard_pending_operation,
    publication_status,
    publish_applied_operation,
    reconcile_saved_operations,
)
from ingestion_v2.question_workbench import (
    QuestionWorkbenchError,
    canonical_type_inventory,
    chapter_inventory,
    list_operations,
    locked_ledger,
    needs_review_inventory,
    operation_by_id,
    save_operation,
)


def _remove_completed_operation(operation_id: str) -> None:
    """Successful operations live in the audit log/Git history, not the action queue."""
    with locked_ledger(base.QUESTION_LEDGER_PATH) as ledger:
        ledger["operations"] = [
            item for item in ledger["operations"]
            if item.get("operation_id") != operation_id
        ]


def _workbench_readiness(operations: list[dict], packs: dict[str, dict]) -> dict:
    active = next((item for item in operations if item.get("state") in {"applied", "publishing"}), None)
    if active is None:
        first_pack_id = next(iter(packs), "")
        active = {"pack_id": first_pack_id, "question_id": "", "operation_type": "repair"}
    return publication_status(
        base.PROJECT_DIRECTORY,
        base.configured_public_worktree(),
        active,
    )


class OneClickWorkbenchHandler(base.WorkbenchHandler):
    """Keep the existing Workbench while replacing only question-action lifecycle."""

    def _handle_question_get(self, parsed) -> bool:
        if parsed.path in {"/api/question-workbench", "/api/question-workbench/readiness"}:
            _, packs = base.installed_question_packs()
            reconcile_saved_operations(base.QUESTION_LEDGER_PATH, packs)
            operations = list_operations(base.QUESTION_LEDGER_PATH)
            readiness = _workbench_readiness(operations, packs)
            if parsed.path.endswith("/readiness"):
                self._send_json(readiness)
                return True
            self._send_json({
                "packs": [
                    {
                        "id": pack_id,
                        "title": pack.get("title", pack_id),
                        "chapters": chapter_inventory(pack),
                        "question_count": len(pack["questions"]),
                    }
                    for pack_id, pack in packs.items()
                ],
                "types": canonical_type_inventory(packs),
                "operations": operations,
                "needs_review": needs_review_inventory(packs, operations),
                "readiness": readiness,
            })
            return True
        return super()._handle_question_get(parsed)

    def _handle_question_post(self) -> bool:
        if self.path == "/api/question-workbench/discard":
            try:
                body = self._read_json()
                operation_id = str(body.get("operation_id") or "")
                if not operation_id:
                    raise QuestionWorkbenchError("operation_id is required")
                removed = discard_pending_operation(base.QUESTION_LEDGER_PATH, operation_id)
                self._send_json({"discarded": removed["operation_id"]})
            except (QuestionWorkbenchError, ValueError, RuntimeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return True

        if self.path not in {"/api/question-workbench/action", "/api/question-workbench/publish"}:
            return super()._handle_question_post()

        try:
            body = self._read_json()
            if self.path.endswith("/publish"):
                operation_id = str(body.get("operation_id") or "")
                if not operation_id:
                    raise QuestionWorkbenchError("operation_id is required")
                operation = operation_by_id(base.QUESTION_LEDGER_PATH, operation_id)
            else:
                _, packs = base.installed_question_packs()
                pack_id = str(body.get("pack_id") or "")
                if pack_id not in packs:
                    raise QuestionWorkbenchError("Selected Pack is unavailable")
                operation_type = str(body.get("operation_type") or "")
                submitted = body.get("question") or {}
                if not isinstance(submitted, dict):
                    raise QuestionWorkbenchError("Complete question values are required")

                original = None
                existing_id = body.get("operation_id")
                if operation_type == "repair":
                    question_id = str(submitted.get("id") or "")
                    original = next((
                        copy.deepcopy(item) for item in packs[pack_id]["questions"]
                        if item.get("id") == question_id
                    ), None)
                    if existing_id:
                        original = operation_by_id(base.QUESTION_LEDGER_PATH, str(existing_id)).get("original_question")
                    if original is None:
                        raise QuestionWorkbenchError("Repair target was not found")
                    # The editor exposes authoring fields only. Merge them over
                    # canonical truth so supported provenance fields survive.
                    question = copy.deepcopy(original)
                    question.update(submitted)
                else:
                    question = submitted

                operation = save_operation(
                    base.QUESTION_LEDGER_PATH,
                    operation_type=operation_type,
                    pack_id=pack_id,
                    pack=packs[pack_id],
                    question=question,
                    original_question=original,
                    operation_id=existing_id,
                    blocker=None,
                )
                operation = apply_canonical_operation(
                    base.PROJECT_DIRECTORY,
                    base.QUESTION_LEDGER_PATH,
                    operation["operation_id"],
                )

            publication = None
            publication_error = None
            try:
                publication = publish_applied_operation(
                    base.PROJECT_DIRECTORY,
                    base.configured_public_worktree(),
                    base.QUESTION_LEDGER_PATH,
                    operation["operation_id"],
                )
            except RuntimeError as error:
                publication_error = str(error)

            operation = operation_by_id(base.QUESTION_LEDGER_PATH, operation["operation_id"])
            readiness = publication_status(
                base.PROJECT_DIRECTORY,
                base.configured_public_worktree(),
                operation,
            )
            if operation.get("state") == "published":
                readiness = {
                    "ready": True,
                    "operator_state": "Published",
                    "reason": None,
                    "reasons": [],
                    "details": readiness.get("details", {}),
                }
                completed_id = operation["operation_id"]
                _remove_completed_operation(completed_id)

            self._send_json({
                "operation": operation,
                "publication": publication,
                "publication_error": publication_error,
                "readiness": readiness,
                "canonical_saved": operation.get("state") in {"applied", "publishing", "published"},
            }, status=201 if self.path.endswith("/action") else 200)
        except (QuestionWorkbenchError, ValueError, RuntimeError) as error:
            self._send_json({"error": str(error)}, status=400)
        return True


def main() -> None:
    args = base.build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535")
    server = ThreadingHTTPServer((args.host, args.port), OneClickWorkbenchHandler)
    print(f"PrepFlow unified private workbench: http://{args.host}:{args.port}/")
    print("Trusted-operator question actions write canonical Pack truth before publication.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
