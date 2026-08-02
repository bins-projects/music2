from compiler.text_repairs import interleaving_blockers


def test_valid_clinical_units_do_not_look_like_interleaving() -> None:
    text = (
        "Report potassium 6.8 mEq/L and compare with sodium 134 mEq/L."
    )

    assert interleaving_blockers(text) == ()


def test_fragmented_unit_and_overlay_still_block() -> None:
    text = "Serum sodium level 134 m UE q / LS NT O"

    assert interleaving_blockers(text)
