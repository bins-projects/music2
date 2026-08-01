from compiler.repair import Finding
from compiler.pack_qa import (
    audit_choice_structure,
    audit_interleaving,
    audit_typography,
    classify_interleaving,
    interleaving_repair_findings,
    typography_repair_findings,
)
from compiler.repair_audit_cli import audit_split_findings


def test_split_audit_separates_approved_review_and_blocked_findings() -> None:
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test-pack",
        "questions": [
            {
                "id": "Q1",
                "stem": "The nurse will call and as k for another route.",
            },
            {
                "id": "Q2",
                "stem": "The patient receives an intravenou s medication.",
            },
            {
                "id": "Q3",
                "stem": "Damaged abCdEf g h j medication s text.",
            },
        ],
    }
    findings = [
        Finding("F1", "Q1", "stem", "possible split suffix"),
        Finding("F2", "Q2", "stem", "possible split suffix"),
        Finding("F3", "Q3", "stem", "possible split suffix"),
    ]

    results = audit_split_findings(pack, findings)

    assert [item["classification"] for item in results] == [
        "approved_repair_candidate",
        "review_split_candidate",
        "blocked_interleaving",
    ]


def test_typography_audit_reports_only_affected_fields() -> None:
    pack = {
        "questions": [
            {
                "id": "Q1",
                "chapter_title": "Communication",
                "stem": "The patient states, ―I understand.‖",
                "choices": [{"text": "No artifact"}],
                "rationale": "A real em dash — remains unchanged.",
            },
            {
                "id": "Q2",
                "stem": "The patient states, ―I understand.",
            },
        ]
    }

    results = audit_typography(pack)

    assert [
        (
            item.question_id,
            item.field,
            item.opening_marks,
            item.closing_marks,
            item.apostrophes,
            item.balanced_after,
        )
        for item in results
    ] == [
        ("Q1", "stem", 1, 1, 0, True),
        ("Q2", "stem", 1, 0, 0, False),
    ]

    findings = typography_repair_findings(pack)
    assert len(findings) == 1
    assert findings[0].question_id == "Q2"
    assert findings[0].field == "stem"
    assert findings[0].damage_type == (
        "unbalanced directional quotation marks"
    )


def test_interleaving_audit_scans_every_question_text_field() -> None:
    pack = {
        "questions": [
            {
                "id": "Q1",
                "stem": "Clean stem",
                "choices": [
                    {"text": "Damaged abCdEf xyZaBc g h j fragments"},
                ],
                "rationale": "Clean rationale",
            }
        ]
    }

    results = audit_interleaving(pack)
    findings = interleaving_repair_findings(pack)

    assert len(results) == 1
    assert results[0].field == "choices[0].text"
    assert "combined_interleaving" in results[0].blocker_codes
    assert results[0].severity == "severe_interleaving"
    assert findings[0].finding_id == "PFQA-INTERLEAVE-Q1-CHOICES-0-TEXT"


def test_interleaving_severity_prioritizes_without_rewriting() -> None:
    assert classify_interleaving(
        ("fragment_density", "mixed_case_interleaving")
    ) == "severe_interleaving"
    assert classify_interleaving(
        ("combined_interleaving",)
    ) == "probable_interleaving"
    assert classify_interleaving(
        ("fragment_density",)
    ) == "fragment_review"


def test_choice_structure_audit_detects_choice_absorbed_into_stem() -> None:
    pack = {
        "questions": [
            {
                "id": "Q1",
                "type": "mc",
                "stem": "Which item? A. First choice",
                "choices": [
                    {"label": "B", "text": "Second choice"},
                    {"label": "C", "text": "Third choice"},
                    {"label": "D", "text": "Fourth choice"},
                ],
                "correct_answers": ["C"],
            }
        ]
    }

    results = audit_choice_structure(pack)

    assert len(results) == 1
    assert results[0].missing_labels == ("A",)
    assert results[0].absorbed_markers == ("A",)
    assert "possible_choice_absorbed_in_stem" in results[0].issue_codes


def test_choice_structure_audit_accepts_contiguous_choices() -> None:
    pack = {
        "questions": [
            {
                "id": "Q1",
                "type": "mc",
                "stem": "Which item?",
                "choices": [
                    {"label": "A", "text": "First choice"},
                    {"label": "B", "text": "Second choice"},
                ],
                "correct_answers": ["A"],
            }
        ]
    }

    assert audit_choice_structure(pack) == []
