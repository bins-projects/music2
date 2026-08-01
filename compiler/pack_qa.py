import re
from dataclasses import dataclass

from compiler.repair import Finding
from compiler.text_repairs import (
    interleaving_blockers,
    normalize_extraction_typography,
)


@dataclass(frozen=True)
class TypographyAuditResult:
    question_id: str
    field: str
    opening_marks: int
    closing_marks: int
    apostrophes: int
    balanced_after: bool


@dataclass(frozen=True)
class InterleavingAuditResult:
    question_id: str
    field: str
    blocker_codes: tuple[str, ...]
    severity: str


INTERLEAVING_SEVERITIES = (
    "severe_interleaving",
    "probable_interleaving",
    "fragment_review",
)


def classify_interleaving(blocker_codes: tuple[str, ...]) -> str:
    codes = set(blocker_codes)
    if {"fragment_density", "mixed_case_interleaving"} <= codes:
        return "severe_interleaving"
    if "mixed_case_interleaving" in codes or "combined_interleaving" in codes:
        return "probable_interleaving"
    return "fragment_review"


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
                or normalization.apostrophes_replaced
            ):
                continue

            results.append(
                TypographyAuditResult(
                    question_id=question["id"],
                    field=field,
                    opening_marks=normalization.opening_marks_replaced,
                    closing_marks=normalization.closing_marks_replaced,
                    apostrophes=normalization.apostrophes_replaced,
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


def audit_interleaving(pack: dict) -> list[InterleavingAuditResult]:
    results = []
    for question in pack["questions"]:
        for field, text in iter_question_text(question):
            blockers = interleaving_blockers(text)
            if blockers:
                results.append(
                    InterleavingAuditResult(
                        question_id=question["id"],
                        field=field,
                        blocker_codes=blockers,
                        severity=classify_interleaving(blockers),
                    )
                )
    return results


def finding_id_for_interleaving(result: InterleavingAuditResult) -> str:
    safe_question = re.sub(r"[^A-Za-z0-9]+", "-", result.question_id)
    safe_field = re.sub(r"[^A-Za-z0-9]+", "-", result.field)
    return f"PFQA-INTERLEAVE-{safe_question}-{safe_field}".upper()


def interleaving_repair_findings(
    pack: dict,
    *,
    severity: str | None = None,
) -> list[Finding]:
    if severity is not None and severity not in INTERLEAVING_SEVERITIES:
        raise ValueError(f"Unsupported interleaving severity: {severity}")

    return [
        Finding(
            finding_id=finding_id_for_interleaving(result),
            question_id=result.question_id,
            field=result.field,
            damage_type=(
                result.severity.replace("_", " ")
                + " ("
                + ", ".join(result.blocker_codes)
                + ")"
            ),
        )
        for result in audit_interleaving(pack)
        if severity is None or result.severity == severity
    ]
