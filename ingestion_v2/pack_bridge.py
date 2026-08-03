from __future__ import annotations

from ingestion_v2.domain import DomainError, QuestionRecord


def pack_questions_to_domain(pack: dict) -> tuple[QuestionRecord, ...]:
    """Read a protected Pack into immutable v2 benchmark records."""
    questions = pack.get("questions") if isinstance(pack, dict) else None
    if pack.get("format") != "prepflow_pack" or not isinstance(questions, list):
        raise DomainError("Benchmark must be a PrepFlow Pack")
    result = []
    for item in questions:
        if not isinstance(item, dict):
            raise DomainError("Benchmark Pack question is malformed")
        raw_choices = item.get("choices")
        if raw_choices is None:
            raw_choices = []
        elif raw_choices == {} and _question_type(item.get("type")) == "completion":
            # Existing valid completion records use an empty object to express
            # that no choices apply. Normalize that legacy empty shape only.
            raw_choices = []
        if not isinstance(raw_choices, list):
            raise DomainError("Benchmark Pack choices must be a list")
        raw_answers = item.get("correct_answers")
        if raw_answers is None:
            raw_answers = []
        if not isinstance(raw_answers, list):
            raise DomainError("Benchmark Pack correct answers must be a list")
        result.append(
            QuestionRecord(
                question_id=str(item.get("id") or ""),
                chapter=_chapter(item.get("chapter")),
                chapter_title=str(item.get("chapter_title") or ""),
                question_type=_question_type(item.get("type")),
                stem=str(item.get("stem") or ""),
                choices=tuple(
                    (str(choice.get("label") or "").upper(), str(choice.get("text") or ""))
                    for choice in raw_choices
                    if isinstance(choice, dict)
                ),
                correct_answers=tuple(str(value) for value in raw_answers),
                rationale=str(item.get("rationale") or ""),
            )
        )
    return tuple(result)


def _question_type(value: object) -> str:
    return {
        "mc": "multiple_choice",
        "multiple_choice": "multiple_choice",
        "multiple_response": "multiple_response",
        "ordered_response": "ordered_response",
        "completion": "completion",
    }.get(str(value or ""), str(value or ""))


def _chapter(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
