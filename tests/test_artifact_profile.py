from compiler.artifact_profile import (
    classify_evidence,
    evidence_score,
    learn_overlay_signature,
    shortest_common_supersequence,
)
from compiler.repair import Finding, create_repair_record
from tests.test_repair import sample_pack


def overlay_record(fragment: str, repair_id: str):
    pack = sample_pack()
    before = "beyondthoseprovided"
    damaged = "beyond" + fragment + "thoseprovided"
    pack["questions"][0]["stem"] = damaged
    return create_repair_record(
        pack,
        Finding(repair_id, "PFQ-test-pack-000000001", "stem", "overlay"),
        before,
    )


def test_temporary_profile_learns_signature_without_hardcoding_it() -> None:
    records = [
        overlay_record("NURSINGTB.CO", "R1"),
        overlay_record("NRIGB.CM", "R2"),
        overlay_record("NURSINGTB.O", "R3"),
    ]

    signature, examples = learn_overlay_signature(records)

    assert examples == 3
    assert len(signature) == 13
    assert all(
        shortest_common_supersequence(signature, fragment) == signature
        for fragment in ("NURSINGTB.CO", "NRIGB.CM", "NURSINGTB.O")
    )


def test_profile_scores_evidence_without_rewriting_text() -> None:
    signature = "NURSINGTB.COM"
    text = "The nurNsUeRisScaIrNinGgTfBor.tCheOpMatient."

    score = evidence_score(text, signature)

    assert score == len(signature)
    assert classify_evidence(score, len(signature)) == (
        "full_signature_evidence"
    )
