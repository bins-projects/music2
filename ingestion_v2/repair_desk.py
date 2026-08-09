"""Read-only repair decision reconciliation and stable-ID lookup.

This module deliberately treats Packs and private workbench artifacts as inputs.
It never applies a repair or writes a candidate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


QUESTION_ID_RE = re.compile(r"^PFQ-[a-z0-9_]+-\d{9}$", re.IGNORECASE)
SUFFIX_RE = re.compile(r"^(?:\d{1,9}|PFQ-[a-z0-9_]+-(\d{9})|([a-z][a-z _-]*?)\s*(\d{1,9}))$", re.IGNORECASE)
DISPLAY_SLUGS = {"fundamentals": "fund", "medical_surgical": "medsurg", "pharmacy": "pharm", "pediatrics": "peds"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_value(value: Any) -> Any:
    """Use one comparable representation for choice objects and repair tuples."""
    if isinstance(value, list):
        if all(isinstance(item, dict) and {"label", "text"} <= set(item) for item in value):
            return [[item["label"], item["text"]] for item in value]
        return [normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_value(item) for item in value]
    return value


def _field(question: dict[str, Any], name: str) -> Any:
    value: Any = question
    for part in name.replace("]", "").replace("[", ".").split("."):
        value = value[int(part)] if part.isdigit() else value[part]
    return normalize_value(value)


def _targets(record: dict[str, Any]) -> Iterable[tuple[str, Any, Any]]:
    if "field" in record:
        yield record["field"], record.get("before"), record.get("after")
    if "after_stem" in record:
        yield "stem", record.get("before_stem"), record["after_stem"]
    for name in ("stem", "choices", "correct_answers", "rationale"):
        replacement = record.get(f"replacement_{name}")
        if replacement is not None:
            yield name, record.get(f"expected_{name}"), replacement
    if "retained_choices" in record:
        yield "choices", record.get("expected_choices"), record["retained_choices"]


def reconcile_repairs(
    repair_records: dict[str, Any],
    canonical_pack: dict[str, Any],
    candidate_pack: dict[str, Any],
    current_questions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Classify every repair field without replacing any record.

    ``current_questions`` may be a newer parser product.  Its disagreement is
    surfaced as a conflict rather than overwritten from an older repair record.
    """
    canonical = {item["id"]: item for item in canonical_pack.get("questions", ())}
    candidate = {item["id"]: item for item in candidate_pack.get("questions", ())}
    result = []
    for record in repair_records.get("repairs", ()):
        question_id = record["question_id"]
        fields = []
        for field, before, after in _targets(record):
            expected = normalize_value(after)
            candidate_value = _field(candidate[question_id], field)
            canonical_value = _field(canonical[question_id], field)
            current_value = _field(current_questions[question_id], field) if current_questions and question_id in current_questions else None
            if candidate_value == expected:
                status = "represented"
            elif current_value is not None and current_value != expected:
                status = "conflicts_with_newer_parser"
            elif candidate_value == normalize_value(before) or canonical_value == candidate_value:
                status = "still_applicable"
            else:
                status = "candidate_diverged"
            fields.append({"field": field, "status": status, "canonical_value": canonical_value, "candidate_value": candidate_value, "approved_value": expected, "current_value": current_value})
        result.append({"repair_id": record["repair_id"], "question_id": question_id, "fields": fields})
    return result


def _matches(question_id: str, query: str, friendly_prefixes: dict[str, str] | None = None) -> bool:
    query = query.strip()
    if QUESTION_ID_RE.fullmatch(query):
        return question_id.casefold() == query.casefold()
    match = SUFFIX_RE.fullmatch(query)
    if not match:
        return False
    slug, number = match.group(2), match.group(3)
    if slug:
        pack_id = question_id.removeprefix("PFQ-").rsplit("-", 1)[0]
        prefixes = friendly_prefixes or {}
        if slug.casefold() not in {pack_id.casefold(), DISPLAY_SLUGS.get(pack_id, "").casefold(), prefixes.get(pack_id, "").casefold()}:
            return False
    return question_id.endswith(f"-{(match.group(1) or number or query).zfill(9)}")


def display_reference(question_id: str) -> str:
    """Human locator only; storage retains the immutable PFQ ID."""
    match = re.fullmatch(r"PFQ-([a-z0-9_]+)-(\d{9})", question_id, re.IGNORECASE)
    if not match:
        return question_id
    label = {"fundamentals": "Fundamentals", "medical_surgical": "Med-Surg", "pharmacy": "Pharm", "pediatrics": "Peds"}.get(match.group(1), match.group(1).replace("_", " ").title())
    return f"{label} {int(match.group(2))}"


def repair_desk_lookup(
    query: str,
    *,
    canonical_packs: Iterable[dict[str, Any]],
    candidate_pack: dict[str, Any] | None = None,
    repair_records: dict[str, Any] | None = None,
    unresolved: Iterable[dict[str, Any]] = (),
    excluded: Iterable[dict[str, Any]] = (),
    friendly_prefixes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Find an ID across every read-only Repair Desk location."""
    matches: list[dict[str, Any]] = []
    for pack in canonical_packs:
        for question in pack.get("questions", ()):
            if _matches(question["id"], query, friendly_prefixes):
                matches.append({"location": "canonical_pack", "question_id": question["id"], "pack_id": pack.get("pack_id")})
    if candidate_pack:
        for question in candidate_pack.get("questions", ()):
            if _matches(question["id"], query, friendly_prefixes):
                matches.append({"location": "isolated_candidate", "question_id": question["id"], "pack_id": candidate_pack.get("pack_id")})
    for item in unresolved:
        if isinstance(item.get("question_id"), str) and _matches(item["question_id"], query, friendly_prefixes):
            matches.append({"location": "unresolved_queue", "question_id": item["question_id"], "finding_id": item.get("finding_id")})
    for item in excluded:
        if isinstance(item.get("question_id"), str) and _matches(item["question_id"], query, friendly_prefixes):
            matches.append({"location": "excluded_record", "question_id": item["question_id"], "finding_id": item.get("finding_id")})
    for record in (repair_records or {}).get("repairs", ()):
        if _matches(record["question_id"], query, friendly_prefixes):
            matches.append({"location": "repair_record", "question_id": record["question_id"], "repair_id": record["repair_id"]})
    return {"query": query, "matches": matches}
