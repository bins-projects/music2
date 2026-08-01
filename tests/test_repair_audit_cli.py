from compiler.repair import Finding
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
