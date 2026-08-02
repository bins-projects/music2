from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ingestion_v2.domain import DomainError


@dataclass(frozen=True)
class ParsedRecord:
    record_id: str
    chapter: int | None
    chapter_title: str
    source_question_number: int | None
    question_type: str
    stem: str
    choices: tuple[tuple[str, str], ...]
    correct_answers: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ParserFinding:
    finding_id: str
    record_id: str
    field: str
    damage_type: str
    explanation: str
    blocking: bool = True


@dataclass(frozen=True)
class ParseBatch:
    records: tuple[ParsedRecord, ...]
    findings: tuple[ParserFinding, ...]
    parser_name: str
    automatic_repairs: int = 0


class Parser(Protocol):
    def parse(self, text: str) -> ParseBatch: ...


class ExistingParserAdapter:
    """Run proven structure recognition behind v2's conservative boundary."""

    parser_name = "existing_source_parser_without_broad_missing_a_recovery"

    def parse(self, text: str) -> ParseBatch:
        if not isinstance(text, str) or not text.strip():
            raise DomainError("Parser input must be non-empty extracted text")

        # The dependency stays behind this adapter; v2 domain and review code do
        # not import legacy parser structures.
        from compiler.normalizer import normalize_questions
        from compiler.source_parser import parse_source_questions

        legacy_records = normalize_questions(
            parse_source_questions(text, allow_missing_a_recovery=False)
        )
        records = []
        findings = []
        finding_number = 1
        for index, item in enumerate(legacy_records, start=1):
            record_id = f"PFV2-REC-{index:06d}"
            choices = tuple(
                (str(choice.get("label") or "").upper(), str(choice.get("text") or ""))
                for choice in item.get("choices") or ()
            )
            answers = tuple(str(answer) for answer in item.get("correct_answers") or ())
            record = ParsedRecord(
                record_id=record_id,
                chapter=_chapter_number(item.get("chapter")),
                chapter_title=str(item.get("chapter_title") or ""),
                source_question_number=_optional_int(item.get("question_number")),
                question_type=str(item.get("question_type") or ""),
                stem=str(item.get("stem") or ""),
                choices=choices,
                correct_answers=answers,
                rationale=str(item.get("rationale") or ""),
            )
            records.append(record)

            record_findings = _structural_findings(record)
            for field, damage_type, explanation in record_findings:
                findings.append(
                    ParserFinding(
                        finding_id=f"PFV2-PARSE-FIND-{finding_number:06d}",
                        record_id=record_id,
                        field=field,
                        damage_type=damage_type,
                        explanation=explanation,
                    )
                )
                finding_number += 1

        return ParseBatch(
            records=tuple(records),
            findings=tuple(findings),
            parser_name=self.parser_name,
            automatic_repairs=0,
        )


def _structural_findings(record: ParsedRecord) -> list[tuple[str, str, str]]:
    findings = []
    if not record.stem:
        findings.append(("stem", "missing_stem", "No question stem was parsed."))
    if not record.question_type:
        findings.append(("stem", "missing_question_type", "No question type was parsed."))

    choice_required = record.question_type in {
        "multiple_choice",
        "multiple_response",
        "ordered_response",
    }
    labels = tuple(label for label, _ in record.choices)
    if choice_required and not record.choices:
        findings.append(("choices", "missing_choices", "This question type requires choices."))
    if labels:
        expected = tuple(chr(ord("A") + index) for index in range(len(labels)))
        if labels != expected:
            findings.append(
                (
                    "choices",
                    "noncanonical_choice_sequence",
                    f"Parsed choice labels are not contiguous from A ({len(labels)} labels).",
                )
            )
    if not record.correct_answers:
        findings.append(
            ("correct_answers", "missing_correct_answer", "No correct answer was parsed.")
        )
    elif choice_required and any(answer not in labels for answer in record.correct_answers):
        findings.append(
            (
                "correct_answers",
                "correct_answer_without_choice",
                "At least one parsed answer has no corresponding parsed choice.",
            )
        )
    return findings


def _chapter_number(value) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re

        match = re.match(r"^Chapter\s+(\d+)", value, re.IGNORECASE)
        return int(match.group(1)) if match else None
    return None


def _optional_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
