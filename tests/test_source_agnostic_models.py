from dataclasses import fields

from compiler.models import Organization, Pack
from compiler.normalizer import normalize_question


def field_names(model: type) -> set[str]:
    return {field.name for field in fields(model)}


def test_question_organization_contains_only_source_neutral_fields() -> None:
    assert field_names(Organization) == {
        "chapter",
        "chapter_title",
        "question_number",
    }


def test_pack_model_has_no_source_provenance_field() -> None:
    assert "source" not in field_names(Pack)


def test_normalizer_discards_incoming_source_provenance() -> None:
    normalized = normalize_question(
        {
            "source": {
                "filename": "private-notes.docx",
                "publisher": "Example Publisher",
            },
            "chapter": 1,
            "chapter_title": "Safety",
            "question_number": 1,
            "question_type": "multiple_choice",
            "stem": "Which action is appropriate?",
            "choices": [
                {"label": "A", "text": "First action"},
                {"label": "B", "text": "Second action"},
            ],
            "correct_answers": ["A"],
            "rationale": "The first action is appropriate.",
        }
    )

    assert "source" not in normalized
