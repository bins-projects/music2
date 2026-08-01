from compiler.duplicate_choice_batch import plan_exact_duplicate_choice_blocks
from compiler.repair import apply_repairs


def question(choices: list[dict], *, answers: list[str] | None = None) -> dict:
    return {
        "id": "PFQ-test-pack-000000001",
        "chapter": 1,
        "chapter_title": "Safety",
        "type": "mc",
        "stem": "Which response is appropriate?",
        "choices": choices,
        "correct_answers": answers or ["D"],
        "rationale": "The retained answer remains correct.",
    }


def pack_with(choices: list[dict], *, answers: list[str] | None = None) -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [question(choices, answers=answers)],
    }


def clean_block() -> list[dict]:
    return [
        {"label": "A", "text": "First response"},
        {"label": "B", "text": "Second response"},
        {"label": "C", "text": "Third response"},
        {"label": "D", "text": "Fourth response"},
    ]


def test_batch_plans_and_applies_one_exact_duplicate_block() -> None:
    block = clean_block()
    pack = pack_with(block + [dict(choice) for choice in block])

    plan = plan_exact_duplicate_choice_blocks(pack, [])
    candidate = apply_repairs(pack, list(plan.proposals))

    assert len(plan.proposals) == 1
    assert candidate["questions"][0]["choices"] == block
    assert pack["questions"][0]["choices"] == block + block
    assert candidate["questions"][0]["correct_answers"] == ["D"]


def test_batch_rejects_repeated_labels_with_different_text() -> None:
    block = clean_block()
    changed = [dict(choice) for choice in block]
    changed[2]["text"] = "Different third response"

    plan = plan_exact_duplicate_choice_blocks(pack_with(block + changed), [])

    assert plan.proposals == ()


def test_batch_rejects_noncanonical_or_invalid_retained_shape() -> None:
    noncanonical = [
        {"label": "B", "text": "Second response"},
        {"label": "A", "text": "First response"},
    ]
    missing_answer = clean_block()

    assert plan_exact_duplicate_choice_blocks(
        pack_with(noncanonical + [dict(choice) for choice in noncanonical]),
        [],
    ).proposals == ()
    assert plan_exact_duplicate_choice_blocks(
        pack_with(
            missing_answer + [dict(choice) for choice in missing_answer],
            answers=["E"],
        ),
        [],
    ).proposals == ()


def test_batch_skips_malformed_choices_for_review_elsewhere() -> None:
    malformed = clean_block()
    malformed[1] = {"label": "B"}

    plan = plan_exact_duplicate_choice_blocks(
        pack_with(malformed + [dict(choice) for choice in malformed]),
        [],
    )

    assert plan.proposals == ()
