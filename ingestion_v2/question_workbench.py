"""Durable single-operator question repair and addition workbench.

The ledger is intentionally private and lives below ``output``.  Pack mutation
is deferred until guarded publication is available; saving never changes a Pack.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator
from uuid import uuid4

from compiler.repair import RepairError, validate_candidate_question


TYPE_DEFINITIONS = {
    "mc": {"label": "Multiple choice", "kind": "single_choice"},
    "multiple_choice": {"label": "Multiple choice", "kind": "single_choice"},
    "multiple_response": {"label": "Select all that apply", "kind": "multiple_choice"},
    "completion": {"label": "Fill in the blank", "kind": "text"},
    "ordered_response": {"label": "Put in order", "kind": "ordered"},
}
ID_RE = re.compile(r"^PFQ-([a-z0-9_]+)-(\d{9})$", re.IGNORECASE)
NAMESPACE_RE = re.compile(r"[^a-z0-9_]+")
LEDGER_FORMAT = "prepflow_question_operation_ledger"
LEDGER_VERSION = "1.0"
FINAL_STATES = {"published"}


class QuestionWorkbenchError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def empty_ledger() -> dict[str, Any]:
    return {"format": LEDGER_FORMAT, "version": LEDGER_VERSION, "namespaces": {}, "operations": []}


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_ledger()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuestionWorkbenchError(f"Operation ledger could not be read: {error}") from error
    if payload.get("format") != LEDGER_FORMAT or not isinstance(payload.get("operations"), list):
        raise QuestionWorkbenchError("Operation ledger has an unsupported format")
    payload.setdefault("namespaces", {})
    return payload


@contextmanager
def locked_ledger(path: Path) -> Iterator[dict[str, Any]]:
    """Serialize ID reservation and operation writes across server threads/processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        ledger = load_ledger(path)
        yield ledger
        _atomic_json(path, ledger)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def canonical_type_inventory(packs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for pack in packs.values():
        for question in pack.get("questions", []):
            stored = question.get("type") or question.get("question_type")
            if isinstance(stored, str):
                counts[stored] = counts.get(stored, 0) + 1
    inventory = []
    for stored in sorted(counts):
        definition = TYPE_DEFINITIONS.get(stored)
        inventory.append({
            "stored_type": stored,
            "count": counts[stored],
            "supported": definition is not None,
            "label": definition["label"] if definition else stored.replace("_", " ").title(),
            "kind": definition["kind"] if definition else "legacy_unsupported",
        })
    return inventory


def chapter_inventory(pack: dict[str, Any]) -> list[dict[str, Any]]:
    chapters: dict[tuple[Any, str], None] = {}
    for question in pack.get("questions", []):
        chapters[(question.get("chapter"), str(question.get("chapter_title") or ""))] = None
    def natural_key(item: tuple[Any, str]) -> tuple[Any, ...]:
        number, title = item
        parts = re.split(r"(\d+)", str(number))
        normalized = tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in parts if part
        )
        return normalized + ((2, title.casefold()),)

    return [
        {"chapter": number, "chapter_title": title}
        for number, title in sorted(chapters, key=natural_key)
    ]


def _derived_namespace(pack_id: str) -> str:
    stable = NAMESPACE_RE.sub("_", pack_id.casefold()).strip("_")
    return stable or f"pack_{hashlib.sha256(pack_id.encode()).hexdigest()[:12]}"


def namespace_for(pack_id: str, pack: dict[str, Any], ledger: dict[str, Any]) -> str:
    persisted = ledger["namespaces"].get(pack_id)
    if isinstance(persisted, str) and persisted:
        return persisted
    namespaces = []
    for question in pack.get("questions", []):
        match = ID_RE.fullmatch(str(question.get("id") or ""))
        if match:
            namespaces.append(match.group(1).casefold())
    if namespaces:
        namespace = max(set(namespaces), key=lambda item: (namespaces.count(item), item))
    else:
        namespace = _derived_namespace(str(pack.get("pack_id") or pack_id))
    ledger["namespaces"][pack_id] = namespace
    return namespace


def reserve_question_id(pack_id: str, pack: dict[str, Any], ledger: dict[str, Any]) -> str:
    namespace = namespace_for(pack_id, pack, ledger)
    used: set[int] = set()
    used_ids: set[str] = set()
    for question in pack.get("questions", []):
        used_ids.add(str(question.get("id") or "").casefold())
    for operation in ledger["operations"]:
        question_id = str(operation.get("question_id") or "")
        used_ids.add(question_id.casefold())
    for question_id in used_ids:
        match = ID_RE.fullmatch(question_id)
        if match and match.group(1).casefold() == namespace.casefold():
            used.add(int(match.group(2)))
    number = max(used, default=0) + 1
    while True:
        candidate = f"PFQ-{namespace}-{number:09d}"
        if candidate.casefold() not in used_ids:
            return candidate
        number += 1


def _normalized_choices(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise QuestionWorkbenchError("Choices or response items must be a list")
    choices = []
    labels: set[str] = set()
    texts: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise QuestionWorkbenchError("Every choice or response item must be an object")
        label = str(item.get("label") or chr(65 + index)).strip().upper()
        text = str(item.get("text") or "").strip()
        if not label or not text:
            raise QuestionWorkbenchError("Every choice or response item needs a label and text")
        if label in labels:
            raise QuestionWorkbenchError(f"Duplicate choice label: {label}")
        if text.casefold() in texts:
            raise QuestionWorkbenchError(f"Duplicate choice text: {text}")
        labels.add(label); texts.add(text.casefold())
        choices.append({"label": label, "text": text})
    return choices


def validate_question(question: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate exactly the representations consumed by PrepFlow."""
    normalized = copy.deepcopy(question)
    stored_type = str(normalized.get("type") or "")
    if stored_type not in TYPE_DEFINITIONS:
        raise QuestionWorkbenchError(f"Legacy question type is not fully supported: {stored_type or 'missing'}")
    for field in ("id", "chapter_title", "stem", "rationale"):
        if not isinstance(normalized.get(field), str) or not normalized[field].strip():
            raise QuestionWorkbenchError(f"Question {field.replace('_', ' ')} is required")
        normalized[field] = normalized[field].strip()
    if normalized.get("chapter") is None:
        raise QuestionWorkbenchError("Question chapter is required")
    answers = normalized.get("correct_answers")
    if not isinstance(answers, list) or not answers:
        raise QuestionWorkbenchError("At least one correct or accepted answer is required")
    answers = [str(answer).strip() for answer in answers if str(answer).strip()]
    if len(answers) != len({answer.casefold() for answer in answers}):
        raise QuestionWorkbenchError("Correct or accepted answers must not be duplicated")
    kind = TYPE_DEFINITIONS[stored_type]["kind"]
    if kind == "text":
        normalized["choices"] = []
        normalized["correct_answers"] = answers
    else:
        choices = _normalized_choices(normalized.get("choices"))
        if len(choices) < 2:
            raise QuestionWorkbenchError("At least two choices or response items are required")
        labels = [item["label"] for item in choices]
        answers = [answer.upper() for answer in answers]
        if any(answer not in labels for answer in answers):
            raise QuestionWorkbenchError("A correct answer references an unknown choice or response item")
        if kind == "single_choice" and len(answers) != 1:
            raise QuestionWorkbenchError("Multiple choice requires exactly one correct answer")
        if kind == "multiple_choice" and len(answers) < 2:
            raise QuestionWorkbenchError("Select all that apply requires multiple correct selections")
        if kind == "ordered" and (len(answers) != len(labels) or set(answers) != set(labels)):
            raise QuestionWorkbenchError("The correct sequence must contain every response item exactly once")
        normalized["choices"] = choices
        normalized["correct_answers"] = answers
    try:
        validate_candidate_question(normalized)
    except RepairError as error:
        raise QuestionWorkbenchError(str(error)) from error
    return normalized


def evaluate_answer(question: dict[str, Any], selected: Any) -> dict[str, Any]:
    kind = TYPE_DEFINITIONS.get(question.get("type"), {}).get("kind")
    correct = [str(item).strip() for item in question.get("correct_answers", [])]
    supplied = selected if isinstance(selected, list) else [selected]
    supplied = [str(item).strip() for item in supplied if item is not None and str(item).strip()]
    if kind == "text":
        is_correct = len(supplied) == 1 and supplied[0].casefold() in {item.casefold() for item in correct}
    elif kind == "ordered":
        is_correct = [item.upper() for item in supplied] == [item.upper() for item in correct]
    else:
        is_correct = {item.upper() for item in supplied} == {item.upper() for item in correct}
    return {"is_correct": is_correct, "correct_answers": correct}


def concise_question_reference(pack_title: str, question_id: str) -> str:
    match = ID_RE.fullmatch(str(question_id or ""))
    if not match:
        return "Reference unavailable"
    return f"{pack_title} • Ref {int(match.group(2))}"


def search_questions(
    pack_id: str,
    pack: dict[str, Any],
    query: str,
    *,
    chapter: str | None = None,
    page: int = 1,
    page_size: int = 40,
) -> dict[str, Any]:
    """Return one predictable, scoped page of installed canonical records."""
    needle = query.strip().casefold()
    reference_match = re.search(r"(?:^|\b)ref\s*#?\s*(\d+)\b", needle)
    numeric_reference = int(needle) if needle.isdigit() else (
        int(reference_match.group(1)) if reference_match else None
    )
    pack_title = str(pack.get("title") or pack_id)
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for index, question in enumerate(pack.get("questions", [])):
        if chapter not in (None, "") and str(question.get("chapter")) != str(chapter):
            continue
        question_id = str(question.get("id") or "")
        suffix = question_id.rsplit("-", 1)[-1]
        exact_reference = (
            numeric_reference is not None
            and suffix.isdigit()
            and int(suffix) == numeric_reference
        )
        exact_id = bool(needle) and question_id.casefold() == needle
        stem = str(question.get("stem") or "")
        exact_stem = bool(needle) and stem.casefold() == needle
        partial_id = bool(needle) and needle in question_id.casefold()
        partial_stem = bool(needle) and needle in stem.casefold()
        if needle and not (exact_reference or exact_id or exact_stem or partial_id or partial_stem):
            continue
        rank = 0 if (exact_reference or exact_id or exact_stem) else 1
        matches.append((rank, index, {
            "pack_id": pack_id,
            "pack_title": pack_title,
            "question_id": question_id,
            "reference": concise_question_reference(pack_title, question_id),
            "chapter": question.get("chapter"),
            "chapter_title": question.get("chapter_title"),
            "type": question.get("type") or question.get("question_type"),
            "stem": stem,
        }))
    matches.sort(key=lambda item: (item[0], item[1]))
    total = len(matches)
    page_size = max(1, min(int(page_size), 100))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * page_size
    return {
        "results": [item[2] for item in matches[start:start + page_size]],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": page < total_pages,
    }


def save_operation(
    ledger_path: Path, *, operation_type: str, pack_id: str, pack: dict[str, Any],
    question: dict[str, Any], original_question: dict[str, Any] | None = None,
    operation_id: str | None = None, blocker: str | None = None,
) -> dict[str, Any]:
    if operation_type not in {"repair", "addition"}:
        raise QuestionWorkbenchError("Operation must be a repair or addition")
    with locked_ledger(ledger_path) as ledger:
        existing = next((item for item in ledger["operations"] if item.get("operation_id") == operation_id), None)
        if existing and existing.get("state") != "pending":
            raise QuestionWorkbenchError("Publication has started; resume it without editing the reserved operation")
        if operation_type == "addition":
            stable_id = existing["question_id"] if existing else reserve_question_id(pack_id, pack, ledger)
            question = {**question, "id": stable_id}
        elif original_question is None:
            raise QuestionWorkbenchError("A repair requires the complete original question")
        else:
            stable_id = str(original_question.get("id") or "")
            question = {**question, "id": stable_id}
        normalized = validate_question(question)
        now = utc_now()
        if existing:
            existing.update({"pack_id": pack_id, "question_id": stable_id, "question": normalized,
                             "original_question": copy.deepcopy(original_question), "updated_at": now,
                             "blocker": blocker, "state": "pending"})
            operation = existing
        else:
            operation = {
                "operation_id": f"PFOP-{uuid4().hex}", "operation_type": operation_type,
                "state": "pending", "pack_id": pack_id, "question_id": stable_id,
                "question": normalized, "original_question": copy.deepcopy(original_question),
                "created_at": now, "updated_at": now, "blocker": blocker,
                "publication": None,
            }
            ledger["operations"].append(operation)
        return copy.deepcopy(operation)


def list_operations(path: Path) -> list[dict[str, Any]]:
    return copy.deepcopy(load_ledger(path)["operations"])


def operation_by_id(path: Path, operation_id: str) -> dict[str, Any]:
    operation = next((item for item in load_ledger(path)["operations"] if item.get("operation_id") == operation_id), None)
    if operation is None:
        raise QuestionWorkbenchError("Saved operation was not found")
    return copy.deepcopy(operation)


def update_operation(path: Path, operation_id: str, **changes: Any) -> dict[str, Any]:
    with locked_ledger(path) as ledger:
        operation = next((item for item in ledger["operations"] if item.get("operation_id") == operation_id), None)
        if operation is None:
            raise QuestionWorkbenchError("Saved operation was not found")
        operation.update(copy.deepcopy(changes))
        operation["updated_at"] = utc_now()
        return copy.deepcopy(operation)


def apply_operation_to_pack(operation: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(pack)
    question = validate_question(operation["question"])
    matches = [index for index, item in enumerate(updated["questions"]) if item.get("id") == operation["question_id"]]
    if operation["operation_type"] == "repair":
        if len(matches) != 1:
            raise QuestionWorkbenchError("Repair target is missing or duplicated")
        original = operation.get("original_question")
        if not isinstance(original, dict) or updated["questions"][matches[0]] != original:
            raise QuestionWorkbenchError("Repair target changed after it was saved")
        replacement = copy.deepcopy(original)
        for field in ("chapter", "chapter_title", "type", "stem", "choices", "correct_answers", "rationale", "notes", "metadata"):
            if field in question:
                replacement[field] = copy.deepcopy(question[field])
        replacement["id"] = operation["question_id"]
        updated["questions"][matches[0]] = validate_question(replacement)
    else:
        if matches:
            raise QuestionWorkbenchError("Reserved question ID already exists in the Pack")
        updated["questions"].append(question)
    ids = [item.get("id") for item in updated["questions"]]
    if len(ids) != len(set(ids)):
        raise QuestionWorkbenchError("Pack contains duplicate question IDs")
    for item in updated["questions"]:
        try:
            validate_candidate_question(item)
        except RepairError as error:
            raise QuestionWorkbenchError(f"Pack validation failed: {error}") from error
    return updated
