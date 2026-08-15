"""Unified Workbench entry point with trusted-operator question actions."""
from __future__ import annotations

import copy
from http.server import ThreadingHTTPServer
from pathlib import Path

from ingestion_v2 import workbench_server as base
from ingestion_v2.one_click_question_actions import (
    apply_canonical_operation,
    discard_pending_operation,
    publication_status,
    publish_applied_operation,
    reconcile_saved_operations,
)
from ingestion_v2.prepflow_question_workbench_launcher import (
    _prepare_public_with_recovery,
    ensure_public_remote,
    public_worktree_destination,
)
from ingestion_v2.question_review_service import (
    QuestionReviewServiceError,
    clear_report,
    configuration as review_service_configuration,
    list_reports,
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


_RUNTIME_PUBLIC_WORKTREE: Path | None = None


def _remove_completed_operation(operation_id: str) -> None:
    """Successful operations live in the audit log/Git history, not the action queue."""
    with locked_ledger(base.QUESTION_LEDGER_PATH) as ledger:
        ledger["operations"] = [
            item for item in ledger["operations"]
            if item.get("operation_id") != operation_id
        ]


def _assert_no_publishing_conflict(question_id: str, operation_id: str | None = None) -> None:
    """Never stack a new canonical decision on top of an in-flight publication."""
    if not question_id:
        return
    conflicts = [
        item for item in list_operations(base.QUESTION_LEDGER_PATH)
        if item.get("question_id") == question_id
        and item.get("operation_id") != operation_id
        and item.get("state") == "publishing"
    ]
    if conflicts:
        raise QuestionWorkbenchError(
            "This question already has publication in progress. Finish recovery before changing it again."
        )


def _supersede_older_operations(operation_id: str, question_id: str) -> None:
    """Canonical truth wins; obsolete drafts/applied rows must not remain replayable."""
    if not question_id:
        return
    with locked_ledger(base.QUESTION_LEDGER_PATH) as ledger:
        kept = []
        for item in ledger["operations"]:
            same_question = item.get("question_id") == question_id
            different_operation = item.get("operation_id") != operation_id
            superseded_state = item.get("state") in {"pending", "applied"}
            if same_question and different_operation and superseded_state:
                continue
            kept.append(item)
        ledger["operations"] = kept


def _known_public_worktree() -> Path | None:
    configured = base.configured_public_worktree()
    if configured is not None and configured.is_dir():
        return configured
    if _RUNTIME_PUBLIC_WORKTREE is not None and _RUNTIME_PUBLIC_WORKTREE.is_dir():
        return _RUNTIME_PUBLIC_WORKTREE
    destination = public_worktree_destination(base.PROJECT_DIRECTORY)
    if destination.is_dir():
        return destination
    return None


def _prepare_public_for_action(operation: dict) -> Path | None:
    """Recover publication delivery at click time instead of depending on startup timing."""
    global _RUNTIME_PUBLIC_WORKTREE
    known = _known_public_worktree()
    if known is not None:
        _RUNTIME_PUBLIC_WORKTREE = known
        return known
    # Never recreate an unknown worktree while an operation is already mid-publish.
    if operation.get("state") == "publishing":
        return None
    ensure_public_remote(base.PROJECT_DIRECTORY)
    prepared = _prepare_public_with_recovery(base.PROJECT_DIRECTORY)
    path = Path(str(prepared["path"]))
    _RUNTIME_PUBLIC_WORKTREE = path
    return path


def _workbench_readiness(operations: list[dict], packs: dict[str, dict]) -> dict:
    active = next((item for item in operations if item.get("state") in {"applied", "publishing"}), None)
    if active is None:
        first_pack_id = next(iter(packs), "")
        active = {"pack_id": first_pack_id, "question_id": "", "operation_type": "repair"}
    return publication_status(
        base.PROJECT_DIRECTORY,
        _known_public_worktree(),
        active,
    )


def _enrich_review_reports(reports: list[dict], packs: dict[str, dict]) -> list[dict]:
    by_id = {}
    for pack_id, pack in packs.items():
        for question in pack.get("questions", []):
            question_id = question.get("id")
            if question_id:
                by_id[question_id] = (pack_id, pack, question)

    enriched = []
    for report in reports:
        item = dict(report)
        match = by_id.get(item.get("question_id"))
        if match is None:
            item["available"] = False
        else:
            pack_id, pack, question = match
            item.update({
                "available": True,
                "pack_id": pack_id,
                "pack_title": pack.get("title", pack_id),
                "chapter": question.get("chapter"),
                "chapter_title": question.get("chapter_title", ""),
                "stem": question.get("stem", ""),
                "type": question.get("type", question.get("question_type", "")),
            })
        enriched.append(item)
    return enriched


class OneClickWorkbenchHandler(base.WorkbenchHandler):
    """Keep the existing Workbench while replacing only question-action lifecycle."""

    def _handle_question_get(self, parsed) -> bool:
        if parsed.path == "/api/question-review-reports":
            config = review_service_configuration()
            if not config["configured"]:
                self._send_json({"configured": False, "reports": []})
                return True
            try:
                _, packs = base.installed_question_packs()
                self._send_json({
                    "configured": True,
                    "reports": _enrich_review_reports(list_reports(), packs),
                })
            except QuestionReviewServiceError as error:
                self._send_json({"configured": True, "reports": [], "error": str(error)}, status=503)
            return True

        if parsed.path in {"/api/question-workbench", "/api/question-workbench/readiness"}:
            _, packs = base.installed_question_packs()
            operations = list_operations(base.QUESTION_LEDGER_PATH)
            # A threaded GET may arrive while an action is between saving its
            # pending ledger row and advancing that row to applied. Never let
            # reconciliation infer away an operation that is actively pending.
            if not any(item.get("state") == "pending" for item in operations):
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
                "review_service_configured": review_service_configuration()["configured"],
            })
            return True
        return super()._handle_question_get(parsed)

    def _handle_question_post(self) -> bool:
        if self.path == "/api/question-review-reports/resolve":
            try:
                body = self._read_json()
                question_id = str(body.get("question_id") or "")
                if not question_id:
                    raise QuestionWorkbenchError("question_id is required")
                self._send_json({"question_id": question_id, "cleared": clear_report(question_id)})
            except (QuestionWorkbenchError, QuestionReviewServiceError, ValueError, RuntimeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return True

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
            resolving_report_id = ""
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
                submitted_question_id = str(submitted.get("id") or "")
                _assert_no_publishing_conflict(submitted_question_id, str(existing_id) if existing_id else None)
                if operation_type == "repair":
                    question_id = submitted_question_id
                    resolving_report_id = question_id
                    original = next((
                        copy.deepcopy(item) for item in packs[pack_id]["questions"]
                        if item.get("id") == question_id
                    ), None)
                    if existing_id:
                        original = operation_by_id(base.QUESTION_LEDGER_PATH, str(existing_id)).get("original_question")
                    if original is None:
                        raise QuestionWorkbenchError("Repair target was not found")
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
                _supersede_older_operations(operation["operation_id"], operation["question_id"])

            report_resolution_error = None
            if resolving_report_id and review_service_configuration()["configured"]:
                try:
                    clear_report(resolving_report_id)
                except QuestionReviewServiceError as error:
                    report_resolution_error = str(error)

            publication = None
            publication_error = None
            public_worktree = None
            try:
                public_worktree = _prepare_public_for_action(operation)
                publication = publish_applied_operation(
                    base.PROJECT_DIRECTORY,
                    public_worktree,
                    base.QUESTION_LEDGER_PATH,
                    operation["operation_id"],
                )
            except RuntimeError as error:
                publication_error = str(error)

            operation = operation_by_id(base.QUESTION_LEDGER_PATH, operation["operation_id"])
            readiness = publication_status(
                base.PROJECT_DIRECTORY,
                public_worktree or _known_public_worktree(),
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
                "report_resolution_error": report_resolution_error,
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
