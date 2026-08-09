from compiler.source_audit import audit_private_source


def test_private_source_audit_reports_parser_and_identity_findings() -> None:
    source = """Chapter 1: Safety
MULTIPLE CHOICE
1. Which answer is present?
a. First
b. Second
ANS: B
Explanation.
DIF: Understanding
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



def test_private_source_audit_without_pack_preserves_chapter_titles() -> None:
    source = """Chapter 1: Growth and Development
MULTIPLE CHOICE
1. Which response is expected?
A. First
B. Second
ANS: B
Explanation.
Chapter 2: Pediatric Assessment
MULTIPLE CHOICE
1. Which assessment is expected?
A. First
B. Second
ANS: A
Explanation.
"""

    report = audit_private_source(source)

    assert report["mode"] == "source_only"
    assert report["safety"]["target_pack_supplied"] is False
    assert report["identity"] is None
    assert report["parse"]["parsed_records"] == 2
    assert report["parse"]["chapters"] == [
        {
            "chapter": 1,
            "chapter_title": "Growth and Development",
            "parsed_records": 1,
            "parser_findings": 0,
        },
        {
            "chapter": 2,
            "chapter_title": "Pediatric Assessment",
            "parsed_records": 1,
            "parser_findings": 0,
        },
    ]
