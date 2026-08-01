from compiler.text_repairs import (
    analyze_text_repairs,
    apply_approved_text_repairs,
)


def test_reviewed_phrase_repairs_apply_together() -> None:
    text = (
        "The patient cannot take oral medication s, so the nurse will call "
        "and as k for another route."
    )

    result = apply_approved_text_repairs(text)

    assert result.text == (
        "The patient cannot take oral medications, so the nurse will call "
        "and ask for another route."
    )
    assert result.applied_rule_ids == (
        "join_medications_suffix",
        "join_ask_fragment",
    )


def test_legitimate_single_letter_phrases_remain_unchanged() -> None:
    text = "Use vitamin K for a patient with type A blood; express it as k."

    result = apply_approved_text_repairs(text)

    assert result.text == text
    assert result.applied_rule_ids == ()


def test_unreviewed_suffix_is_detected_but_not_repaired() -> None:
    text = "The patient receives an intravenou s medication."

    result = apply_approved_text_repairs(text)

    assert result.text == text
    assert result.applied_rule_ids == ()
    assert [
        (item.separated, item.mechanical_join)
        for item in result.analysis.split_candidates
    ] == [("intravenou s", "intravenous")]


def test_interleaving_blocks_approved_repairs() -> None:
    text = (
        "The patient needs medication s while abCdEf g h j fragments "
        "remain mixed into the field."
    )

    result = apply_approved_text_repairs(text)

    assert result.text == text
    assert result.applied_rule_ids == ()
    assert result.analysis.blocked is True


def test_clean_reviewed_text_is_not_blocked() -> None:
    analysis = analyze_text_repairs(
        "The nurse will call and as k for another route."
    )

    assert analysis.blocked is False
    assert analysis.approved_rule_ids == ("join_ask_fragment",)
