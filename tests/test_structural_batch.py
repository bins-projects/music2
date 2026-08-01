from compiler.repair import Finding, create_repair_record
from compiler.structural_batch import (
    plan_clear_absorbed_choices,
    remove_near_contiguous_signature,
)
from tests.test_repair import sample_pack


def absorbed_pack(stem: str) -> dict:
    pack = sample_pack()
    question = pack["questions"][0]
    question["stem"] = stem
    question["choices"] = [
        {"label": "B", "text": "Second action"},
        {"label": "C", "text": "Third action"},
    ]
    question["correct_answers"] = ["B"]
    return pack


def overlay_training_record(pack: dict):
    before = "CleanNURSINGTB.COMtext"
    pack["questions"][0]["rationale"] = before
    return create_repair_record(
        pack,
        Finding("TRAIN", pack["questions"][0]["id"], "rationale", "overlay"),
        "Cleantext",
        disposition="parser_candidate",
    )


def test_batch_plans_clean_absorbed_choice_without_writing() -> None:
    pack = absorbed_pack("Which action? A. First action")
    plan = plan_clear_absorbed_choices(pack, [])

    assert len(plan.proposals) == 1
    assert plan.proposals[0].after_stem == "Which action?"
    assert plan.proposals[0].insert_text == "First action"
    assert pack["questions"][0]["choices"][0]["label"] == "B"


def test_batch_uses_only_tightly_grouped_learned_overlay() -> None:
    pack = absorbed_pack(
        "Which actNURSINGTB.COMion? A. First action"
    )
    training = overlay_training_record(pack)
    plan = plan_clear_absorbed_choices(pack, [training])

    assert len(plan.proposals) == 1
    assert plan.proposals[0].after_stem == "Which action?"
    assert remove_near_contiguous_signature(
        "damNURSINGTB.COMaged", "NURSINGTB.COM"
    ) == "damaged"


def test_batch_leaves_widely_interleaved_or_damaged_choice_for_review() -> None:
    pack = absorbed_pack(
        "Which NtUhReSaIcNtGiToBn.C?OM A. DamAagBed choice"
    )
    training = overlay_training_record(pack)
    plan = plan_clear_absorbed_choices(pack, [training])

    assert plan.proposals == ()
    assert plan.review_question_ids == ("PFQ-test-pack-000000001",)
