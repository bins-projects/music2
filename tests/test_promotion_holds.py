import json
from pathlib import Path

import pytest

from compiler.promotion_holds import (
    HOLD_FIELDS,
    PromotionHoldError,
    load_promotion_holds,
    promotion_hold_summary,
)


def pack() -> dict:
    return {
        "format": "prepflow_pack",
        "pack_id": "fundamentals",
        "questions": [{"id": "PFQ-fundamentals-000000108"}],
    }


def write_registry(path: Path, *, question_id: str = "PFQ-fundamentals-000000108") -> Path:
    value = {
        "format": "prepflow_promotion_holds",
        "version": "1.0",
        "holds": [
            {
                "hold_id": "PFH-FUNDAMENTALS-000000108-ANSWER",
                "pack_id": "fundamentals",
                "question_id": question_id,
                "category": "source_verification_required",
                "reason": "Verify an answer-map change before promotion.",
                "status": "unresolved",
            }
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_question_108_hold_blocks_promotion_readiness() -> None:
    path = Path("config/promotion-holds.prepflow.json")

    holds = load_promotion_holds(path, pack=pack())
    summary = promotion_hold_summary(holds)

    assert holds[0].question_id == "PFQ-fundamentals-000000108"
    assert holds[0].category == "source_verification_required"
    assert summary["promotion_ready"] is False
    assert summary["unresolved_count"] == 1


def test_hold_schema_is_source_neutral() -> None:
    raw = json.loads(Path("config/promotion-holds.prepflow.json").read_text())

    assert set(raw["holds"][0]) == HOLD_FIELDS
    serialized = json.dumps(raw).lower()
    for forbidden in ("filename", "source_path", "publisher", "page_number", "hash"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("question_id", "message"),
    [
        ("question-108", "Unstable question ID"),
        ("PFQ-fundamentals-000000999", "Unknown question ID"),
    ],
)
def test_hold_rejects_unstable_or_unknown_question_ids(tmp_path, question_id, message) -> None:
    path = write_registry(tmp_path / "holds.json", question_id=question_id)

    with pytest.raises(PromotionHoldError, match=message):
        load_promotion_holds(path, pack=pack())
