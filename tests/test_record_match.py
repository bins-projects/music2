import json

from compiler.record_match import match_ordered_records


def parsed(stem: str, number: int) -> dict:
    return {
        "chapter": 1,
        "question_number": number,
        "question_type": "multiple_choice",
        "stem": stem,
        "choices": [{"label": "A", "text": "Choice"}],
        "correct_answers": ["A"],
        "rationale": "Rationale",
    }


def target(stem: str, number: int) -> dict:
    value = parsed(stem, number)
    value["id"] = f"PFQ-test-00000000{number}"
    value["type"] = value.pop("question_type")
    value.pop("question_number")
    return value


def test_ordered_match_identifies_exact_changed_and_parsed_only_without_text() -> None:
    source = [
        parsed("First stem", 1),
        parsed("Parser-only material", 99),
        parsed("Middle anchor", 4),
        parsed("Changed second stem", 2),
        parsed("Third stem", 3),
    ]
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [
            target("First stem", 1),
            target("Middle anchor", 4),
            target("Original second stem", 2),
            target("Third stem", 3),
        ],
    }

    result = match_ordered_records(source, pack)

    assert result["matched_count"] == 4
    assert result["exact_stem_count"] == 3
    assert result["changed_stem_count"] == 1
    assert result["parsed_only_count"] == 1
    assert result["target_only_count"] == 0
    assert all("type" not in item["changed_fields"] for item in result["matches"])
    report = json.dumps(result)
    assert "Parser-only material" not in report
    assert "Changed second stem" not in report
    assert result["parsed_only"][0]["record_id"].startswith("PFIR-")
    assert result["parsed_only"][0]["finding_code"] == "unmatched_parser_boundary"
