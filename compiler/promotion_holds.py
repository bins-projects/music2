import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


QUESTION_ID_RE = re.compile(r"^PFQ-[a-z0-9][a-z0-9-]*-\d{9}$")
HOLD_FIELDS = {
    "hold_id",
    "pack_id",
    "question_id",
    "category",
    "reason",
    "status",
}


class PromotionHoldError(ValueError):
    """Raised when a promotion-hold registry is invalid."""


@dataclass(frozen=True)
class PromotionHold:
    hold_id: str
    pack_id: str
    question_id: str
    category: str
    reason: str
    status: str


def load_promotion_holds(
    path: str | Path,
    *,
    pack: dict | None = None,
) -> tuple[PromotionHold, ...]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PromotionHoldError(f"Cannot load promotion holds: {source}") from error

    if not isinstance(value, dict) or value.get("format") != "prepflow_promotion_holds":
        raise PromotionHoldError("Expected a PrepFlow promotion-hold registry")
    if value.get("version") != "1.0" or not isinstance(value.get("holds"), list):
        raise PromotionHoldError("Unsupported or malformed promotion-hold registry")

    known_ids = None
    expected_pack_id = None
    if pack is not None:
        expected_pack_id = pack.get("pack_id")
        questions = pack.get("questions")
        if not isinstance(questions, list):
            raise PromotionHoldError("Pack questions must be a list")
        known_ids = {question.get("id") for question in questions}

    holds = []
    seen = set()
    for raw in value["holds"]:
        if not isinstance(raw, dict) or set(raw) != HOLD_FIELDS:
            raise PromotionHoldError("Promotion hold has unsupported or missing fields")
        if any(not isinstance(raw[field], str) or not raw[field] for field in HOLD_FIELDS):
            raise PromotionHoldError("Promotion hold fields must be non-empty strings")
        if not QUESTION_ID_RE.fullmatch(raw["question_id"]):
            raise PromotionHoldError(f"Unstable question ID: {raw['question_id']}")
        if raw["status"] not in {"unresolved", "resolved"}:
            raise PromotionHoldError(f"Unsupported hold status: {raw['status']}")
        if raw["hold_id"] in seen:
            raise PromotionHoldError(f"Duplicate hold ID: {raw['hold_id']}")
        if expected_pack_id is not None and raw["pack_id"] != expected_pack_id:
            raise PromotionHoldError(f"Hold pack does not match: {raw['hold_id']}")
        if known_ids is not None and raw["question_id"] not in known_ids:
            raise PromotionHoldError(f"Unknown question ID: {raw['question_id']}")
        seen.add(raw["hold_id"])
        holds.append(PromotionHold(**raw))

    return tuple(sorted(holds, key=lambda item: (item.question_id, item.hold_id)))


def promotion_hold_summary(holds: tuple[PromotionHold, ...]) -> dict:
    unresolved = tuple(item for item in holds if item.status == "unresolved")
    return {
        "promotion_ready": not unresolved,
        "unresolved_count": len(unresolved),
        "unresolved_holds": [asdict(item) for item in unresolved],
    }
