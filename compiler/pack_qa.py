import re
from dataclasses import dataclass

from compiler.repair import Finding
from compiler.text_repairs import normalize_extraction_typography


@dataclass(frozen=True)
class TypographyAuditResult:
    question_id: str
    field: str
    opening_marks: int
    closing_marks: int
    balanced_after: bool


def iter_question_text(question: dict):
    for field in ("chapter_title", "stem", "rationale"):
        value = question.get(field)
        if isinstance(value, str):
            yield field, value

    choices = question.get("choices")
    if isinstance(choices, list):
        for index, choice in enumerate(choices):
            if isinstance(choice, dict) and isinstance(choice.get("text"), str):
                yield f"choices[{index}].text", choice["text"]


def audit_typography(pack: dict) -> list[TypographyAuditResult]:
    results = []
    for question in pack["questions"]:
        for field, text in iter_question_text(question):
            normalization = normalize_extraction_typography(text)
            if not (
                normalization.opening_marks_replaced
                or normalization.closing_marks_replaced
            ):
                continue

            results.append(
                TypographyAuditResult(
                    question_id=question["id"],
                    field=field,
                    opening_marks=normalization.opening_marks_replaced,
                    closing_marks=normalization.closing_marks_replaced,
                    balanced_after=normalization.balanced,
                )
            )

    return results


def finding_id_for_typography(result: TypographyAuditResult) -> str:
    safe_question = re.sub(r"[^A-Za-z0-9]+", "-", result.question_id)
    safe_field = re.sub(r"[^A-Za-z0-9]+", "-", result.field)
    return f"PFQA-QUOTE-{safe_question}-{safe_field}".upper()


def typography_repair_findings(pack: dict) -> list[Finding]:
    return [
        Finding(
            finding_id=finding_id_for_typography(result),
            question_id=result.question_id,
            field=result.field,
            damage_type="unbalanced directional quotation marks",
        )
        for result in audit_typography(pack)
        if not result.balanced_after
    ]
