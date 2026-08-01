from compiler.repair import Finding
from compiler.pack_qa import audit_typography, typography_repair_findings
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
            item.balanced_after,
        )
        for item in results
    ] == [
        ("Q1", "stem", 1, 1, True),
        ("Q2", "stem", 1, 0, False),
    ]

    findings = typography_repair_findings(pack)
    assert len(findings) == 1
    assert findings[0].question_id == "Q2"
    assert findings[0].field == "stem"
    assert findings[0].damage_type == (
        "unbalanced directional quotation marks"
    )
