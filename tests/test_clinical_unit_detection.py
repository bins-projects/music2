from compiler.text_repairs import interleaving_blockers


def test_valid_clinical_units_do_not_look_like_interleaving() -> None:
    text = (
        "Report potassium 6.8 mEq/L and compare with sodium 134 mEq/L."
    )

    assert interleaving_blockers(text) == ()


def test_multiple_supported_clinical_units_remain_valid_prose() -> None:
    text = "Infuse 5 mg/mL at 2 mL/min and monitor 3 mmol/L and 4 mcg/kg."

    assert interleaving_blockers(text) == ()


def test_temperature_units_and_choice_shorthand_do_not_look_like_interleaving() -> None:
    text = (
        "T: 100.5 °F (38 °C), P: 96 beats/min. "
        "A DAR note records data (D), action (A), and response (R); "
        "SBAR item: S. Document diagnosis r/t dehydration."
    )

    assert interleaving_blockers(text) == ()


def test_fragmented_unit_and_overlay_still_block() -> None:
    text = "Serum sodium level 134 m UE q / LS NT O"

    assert interleaving_blockers(text)


def test_valid_unit_does_not_hide_real_interleaving() -> None:
    text = "Potassium is 6.8 mEq/L with fragments UE NT O and miXedCaSe foRmat."

    assert interleaving_blockers(text)


def test_malformed_unit_spacing_is_not_exempted() -> None:
    text = "Values include m E q / L plus UE NT O fragments."

    assert interleaving_blockers(text)


def test_mixed_case_near_miss_is_not_exempted() -> None:
    text = "Values include mEQ/l and mEq/Li with UE NT O fragments."

    assert interleaving_blockers(text)


def test_common_nursing_notation_does_not_trigger_interleaving() -> None:
    assert interleaving_blockers(
        "Generation Y and Generation Z use e-mail and LinkedIn."
    ) == ()
    assert interleaving_blockers(
        "Patient report: S. Assessment: A. Recommendation: R."
    ) == ()
    assert interleaving_blockers(
        "Type O blood and a B antigen are documented."
    ) == ()
    assert interleaving_blockers(
        "Periods after Q can be mistaken for I, and the O mistaken for I. "
        "Write as X mg or 0.X mg."
    ) == ()
