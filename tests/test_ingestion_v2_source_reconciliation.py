from ingestion_v2.parser import ParseBatch, ParsedRecord
import pytest

from ingestion_v2.source_reconciliation import (
    _normalize_source_spacing,
    apply_recovery_plan,
    reconcile_corroborated_fields,
    recovery_plan,
)


def _record(record_id: str, *, stem: str, rationale: str) -> ParsedRecord:
    return ParsedRecord(
        record_id=record_id,
        chapter=1,
        chapter_title="Fundamentals",
        source_question_number=1,
        question_type="multiple_choice",
        stem=stem,
        choices=(("A", "First"), ("B", "Second")),
        correct_answers=("A",),
        rationale=rationale,
    )


def _batch(record: ParsedRecord) -> ParseBatch:
    return ParseBatch((record,), (), "test_parser")


def test_reconciliation_uses_a_clean_matching_source_reading_for_watermark_damage() -> None:
    primary = _batch(_record(
        "PFV2-REC-000001",
        stem="The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?",
        rationale="A correct rationale.",
    ))
    clean = "The nurse follows the nursing process?"
    result = reconcile_corroborated_fields(
        primary,
        (
            _batch(_record("ALT-1", stem=clean, rationale="A correct rationale.")),
        ),
    )

    assert result.records[0].stem == clean
    assert result.records[0].rationale == "A correct rationale."
    assert result.automatic_repairs == 1


def test_reconciliation_does_not_choose_a_still_damaged_reading() -> None:
    primary = _batch(_record(
        "PFV2-REC-000001",
        stem="The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?",
        rationale="A correct rationale.",
    ))
    result = reconcile_corroborated_fields(
        primary,
        (
            _batch(_record("ALT-1", stem="The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?", rationale="A correct rationale.")),
        ),
    )

    assert result.records[0].stem == primary.records[0].stem
    assert result.automatic_repairs == 0


def test_reconciliation_rejects_clean_alternate_that_absorbs_next_question() -> None:
    primary = _batch(_record(
        "PFV2-REC-000001",
        stem="The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?",
        rationale="A concise rationale about assessment.",
    ))
    result = reconcile_corroborated_fields(
        primary,
        (_batch(_record(
            "ALT-1",
            stem="The nurse follows the nursing process?",
            rationale=(
                "A concise rationale about assessment. "
                "2. A neighboring question and its full rationale were also extracted here."
            ),
        )),),
    )

    assert result.records[0].stem == "The nurse follows the nursing process?"
    assert result.records[0].rationale == primary.records[0].rationale


def test_reconciliation_replaces_choices_and_answer_only_as_one_complete_structure() -> None:
    primary = _batch(ParsedRecord(
        "PFV2-REC-000001", 1, "Fundamentals", 1, "multiple_choice",
        "Which action?", (("B", "Second"), ("C", "Third")), ("C",), "Reason.",
    ))
    replacement = ParsedRecord(
        "ALT-1", 1, "Fundamentals", 1, "multiple_choice", "Which action?",
        (("A", "First"), ("B", "Second"), ("C", "Third")), ("B",), "Reason.",
    )

    result = reconcile_corroborated_fields(primary, (_batch(replacement),))

    assert result.records[0].choices == replacement.choices
    assert result.records[0].correct_answers == ("B",)
    assert result.automatic_repairs == 2


def test_recovery_plan_replays_only_against_the_exact_original_parse() -> None:
    primary = _batch(_record(
        "PFV2-REC-000001", stem="The nurse NfoUllRowSsIthNeGnTuBrsi.ngCprMocess?", rationale="Reason.",
    ))
    recovered = reconcile_corroborated_fields(primary, (_batch(_record(
        "ALT-1", stem="The nurse follows the nursing process?", rationale="Reason.",
    )),))

    assert apply_recovery_plan(primary, recovery_plan(primary, recovered)).records == recovered.records

    changed = _batch(_record(
        "PFV2-REC-000001", stem="A different source parse", rationale="Reason.",
    ))
    with pytest.raises(ValueError, match="does not match"):
        apply_recovery_plan(changed, recovery_plan(primary, recovered))


def test_reconciliation_recovers_the_verified_wide_interwoven_watermark() -> None:
    damaged = _record(
        "PFV2-REC-000001",
        stem="Which degree?",
        rationale=(
            "Courses be yo n d Nt hUo Rs eSpIr oNv iGdTe dBi.nCa nOa "
            "s s o c i at e degree program, w hich is current."
        ),
    )
    vocabulary = ParsedRecord(
        "PFV2-REC-000002", 1, "Fundamentals", 2, "multiple_choice", "Stem",
        (("A", "First"),), ("A",),
        "Beyond those provided in an associate degree program which is current.",
    )
    primary = ParseBatch((damaged, vocabulary), (), "test_parser")
    still_damaged = _record(
        "ALT-1", stem="Which degree?", rationale=damaged.rationale,
    )

    result = reconcile_corroborated_fields(primary, (_batch(still_damaged),))

    assert result.records[0].rationale == (
        "Courses beyond those provided in an associate degree program, which is current."
    )
    assert result.automatic_repairs == 1


def test_reconciliation_does_not_repair_an_incomplete_overlay_signature() -> None:
    primary = _batch(_record(
        "PFV2-REC-000001", stem="Which NtUhReSaIcNtGiToBn.C?", rationale="Reason.",
    ))

    result = reconcile_corroborated_fields(primary, ())

    assert result.records[0].stem == primary.records[0].stem


def test_source_spacing_normalization_uses_only_attested_words() -> None:
    vocabulary = {
        "beyond": 3, "those": 5, "provided": 4, "in": 20, "an": 6,
        "associate": 3, "controlled": 3, "environment": 4,
    }

    assert _normalize_source_spacing(
        "be yo n d t h o s e provided in an associate degree", vocabulary
    ) == "beyond those provided in an associate degree"
    assert _normalize_source_spacing("a controlledenvironment", vocabulary) == "a controlled environment"
    # Unattested terms are left exactly as the source reader supplied them.
    assert _normalize_source_spacing("unknownclinicalcompound", vocabulary) == "unknownclinicalcompound"


def test_source_spacing_normalization_joins_overlay_letter_fragments() -> None:
    vocabulary = {"be": 20, "the": 20, "blood": 4, "pressure": 4}

    assert _normalize_source_spacing(
        "perfusion could be c o m p r o m i s e d . T he b loo d pressure",
        vocabulary,
    ) == "perfusion could be compromised. The blood pressure"


def test_reconciliation_recovers_only_clean_same_structure_choice_text() -> None:
    primary = _batch(ParsedRecord(
        "PFV2-REC-000001", 1, "Fundamentals", 1, "multiple_choice", "Which?",
        (("A", "First"), ("B", "r e a d Ni nUe sRs S")), ("A",), "Reason.",
    ))
    vocabulary = ParsedRecord(
        "PFV2-REC-000002", 1, "Fundamentals", 2, "multiple_choice", "Other?",
        (("A", "First"),), ("A",), "Readiness is important.",
    )
    primary = ParseBatch((primary.records[0], vocabulary), (), "test_parser")
    alternate = ParsedRecord(
        "ALT-1", 1, "Fundamentals", 1, "multiple_choice", "Which?",
        (("A", "First"), ("B", "r e a d i ne ss")), ("A",), "Reason.",
    )

    result = reconcile_corroborated_fields(primary, (_batch(alternate),))

    assert result.records[0].choices == (("A", "First"), ("B", "readiness"))
    assert result.automatic_repairs == 1


def test_reconciliation_repairs_source_attested_primary_spacing_without_an_alternate() -> None:
    damaged = _record(
        "PFV2-REC-000001",
        stem="Which action?",
        rationale="The nurse addresses sclero sis before discharge.",
    )
    vocabulary = _record(
        "PFV2-REC-000002",
        stem="Other?",
        rationale="Multiple sclerosis requires coordinated discharge planning.",
    )

    result = reconcile_corroborated_fields(
        ParseBatch((damaged, vocabulary), (), "test_parser"), ()
    )

    assert result.records[0].rationale == "The nurse addresses sclerosis before discharge."
    assert result.automatic_repairs == 1


def test_reconciliation_repairs_source_attested_prefix_split_without_an_alternate() -> None:
    damaged = _record(
        "PFV2-REC-000001", stem="The p atient needs care.", rationale="Reason."
    )
    vocabulary = _record(
        "PFV2-REC-000002", stem="Other patient?", rationale="Reason."
    )

    result = reconcile_corroborated_fields(
        ParseBatch((damaged, vocabulary), (), "test_parser"), ()
    )

    assert result.records[0].stem == "The patient needs care."
