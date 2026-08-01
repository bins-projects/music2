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


@dataclass(frozen=True)
class ChoiceStructureAuditResult:
    question_id: str
    labels: tuple[str, ...]
    missing_labels: tuple[str, ...]
    absorbed_markers: tuple[str, ...]
    issue_codes: tuple[str, ...]


INTERLEAVING_SEVERITIES = (
    "severe_interleaving",
    "probable_interleaving",
    "fragment_review",
)
CHOICE_REQUIRED_TYPES = {"mc", "multiple_response", "ordered_response"}
CHOICE_MARKER_RE = re.compile(
    r"(?:^|\s)([A-Z])\s*[.):]\s+\S",
    flags=re.IGNORECASE,
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


def audit_choice_structure(pack: dict) -> list[ChoiceStructureAuditResult]:
    """Detect malformed choice sequences without rewriting question content."""
    results = []
    for question in pack["questions"]:
        if question.get("type") not in CHOICE_REQUIRED_TYPES:
            continue

        issues = []
        choices = question.get("choices")
        if not isinstance(choices, list) or not choices:
            results.append(
                ChoiceStructureAuditResult(
                    question_id=question["id"],
                    labels=(),
                    missing_labels=(),
                    absorbed_markers=(),
                    issue_codes=("missing_choice_collection",),
                )
            )
            continue

        labels = tuple(
            str(choice.get("label") or "").strip().upper()
            if isinstance(choice, dict)
            else ""
            for choice in choices
        )
        if any(not label for label in labels):
            issues.append("invalid_choice_label")
        if len(set(labels)) != len(labels):
            issues.append("duplicate_choice_label")

        alphabetical = all(
            len(label) == 1 and "A" <= label <= "Z" for label in labels
        )
        missing = ()
        if alphabetical:
            highest = max(ord(label) for label in labels)
            expected = tuple(chr(value) for value in range(ord("A"), highest + 1))
            missing = tuple(label for label in expected if label not in labels)
            present_expected = tuple(label for label in expected if label in labels)
            if missing:
                issues.append("missing_sequence_label")
            if labels != present_expected:
                issues.append("noncanonical_choice_order")

        answers = question.get("correct_answers")
        if isinstance(answers, list) and any(
            str(answer).strip().upper() not in labels for answer in answers
        ):
            issues.append("correct_answer_without_choice")

        stem = question.get("stem")
        markers = set()
        if isinstance(stem, str):
            markers = {
                match.group(1).upper()
                for match in CHOICE_MARKER_RE.finditer(stem)
            }
        absorbed = tuple(label for label in missing if label in markers)
        if absorbed:
            issues.append("possible_choice_absorbed_in_stem")

        if issues:
            results.append(
                ChoiceStructureAuditResult(
                    question_id=question["id"],
                    labels=labels,
                    missing_labels=missing,
                    absorbed_markers=absorbed,
                    issue_codes=tuple(dict.fromkeys(issues)),
                )
            )

    return results


def finding_id_for_choice_structure(
    result: ChoiceStructureAuditResult,
) -> str:
    safe_question = re.sub(r"[^A-Za-z0-9]+", "-", result.question_id)
    return f"PFQA-STRUCTURE-{safe_question}-STEM".upper()


def choice_structure_repair_findings(pack: dict) -> list[Finding]:
    return [
        Finding(
            finding_id=finding_id_for_choice_structure(result),
            question_id=result.question_id,
            field="stem",
            damage_type="choice structure: " + ", ".join(result.issue_codes),
        )
        for result in audit_choice_structure(pack)
    ]
