from compiler.source_audit import audit_private_source


def test_private_source_audit_reports_parser_and_identity_findings() -> None:
    source = """Chapter 1: Safety
MULTIPLE CHOICE
1. Which answer is present?
a. First
b. Second
ANS: B
Explanation.
2. Which answer is incomplete?
b. Second
ANS: A
Explanation.
"""
    pack = {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "fundamentals",
        "questions": [
            {
                "id": "PFQ-fundamentals-000000001",
                "chapter": 1,
                "stem": "Which answer is present?",
                "choices": [],
                "correct_answers": [],
                "rationale": "",
            }
        ],
    }

    report = audit_private_source(source, pack)

    assert report["safety"]["pack_write_available"] is False
    assert report["parse"]["parsed_records"] == 2
    assert report["parse"]["parser_findings_by_type"] == {
        "correct_answer_without_choice": 1,
        "noncanonical_choice_sequence": 1,
    }
    assert report["identity"]["exact_matches"] == 1
    assert report["identity"]["source_review_required"] == 1
    assert report["identity"]["pack_only_records"] == 0
