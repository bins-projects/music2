from compiler.intake_attribution import attribute_drift


def pack(value: str) -> dict:
    return {
        "questions": [
            {
                "id": "PFQ-test-000000001",
                "chapter": 1,
                "chapter_title": "Test",
                "type": "mc",
                "stem": value,
                "choices": [],
                "correct_answers": [],
                "rationale": "",
            }
        ]
    }


def test_attribution_separates_cleaning_from_persistent_drift() -> None:
    isolated = pack("Generalized result")
    canonical = pack("Canonical result")
    candidate = pack("Approved result")

    reaches = attribute_drift(isolated, candidate, canonical, candidate, [], [], [])
    persists = attribute_drift(isolated, isolated, canonical, candidate, [], [], [])

    assert reaches["field_category_counts"] == {
        "legacy_cleaning_reaches_candidate_24": {"stem": 1}
    }
    assert persists["field_category_counts"] == {
        "persists_after_legacy_cleaning": {"stem": 1}
    }
    assert reaches["legacy_cleaner_used_for_diagnostics_only"] is True
