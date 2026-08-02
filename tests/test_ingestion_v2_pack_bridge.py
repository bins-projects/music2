import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.pack_bridge import pack_questions_to_domain


def test_pack_bridge_creates_immutable_source_neutral_benchmark_records() -> None:
    pack = {
        "format": "prepflow_pack",
        "pack_id": "test",
        "questions": [
            {
                "id": "PFQ-test-000000001",
                "chapter": 1,
                "chapter_title": "Chapter",
                "type": "mc",
                "stem": "Stem",
                "choices": [{"label": "a", "text": "Choice"}],
                "correct_answers": ["A"],
                "rationale": "Rationale",
            }
        ],
    }

    questions = pack_questions_to_domain(pack)

    assert questions[0].question_type == "multiple_choice"
    assert questions[0].choices == (("A", "Choice"),)
    assert questions[0].question_id == "PFQ-test-000000001"


def test_pack_bridge_rejects_non_pack_and_malformed_choices() -> None:
    with pytest.raises(DomainError):
        pack_questions_to_domain({})
    with pytest.raises(DomainError, match="choices"):
        pack_questions_to_domain(
            {
                "format": "prepflow_pack",
                "questions": [
                    {"id": "PFQ-test-000000001", "type": "mc", "stem": "Stem", "choices": {}}
                ],
            }
        )
