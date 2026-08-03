from __future__ import annotations

from ingestion_v2.domain import DomainError, Finding, FindingSeverity, QuestionRecord
from ingestion_v2.parser import ParseBatch


def materialize_matched_batch(
    batch: ParseBatch,
    stable_id_by_record_id: dict[str, str],
) -> tuple[tuple[QuestionRecord, ...], tuple[Finding, ...]]:
    """Attach externally matched stable IDs without repairing parser output."""
    record_ids = {record.record_id for record in batch.records}
    if set(stable_id_by_record_id) != record_ids:
        raise DomainError("Stable-ID mapping must cover exactly the parsed records")

    questions = tuple(
        QuestionRecord(
            question_id=stable_id_by_record_id[record.record_id],
            chapter=record.chapter,
            chapter_title=record.chapter_title,
            question_type=record.question_type,
            stem=record.stem,
            choices=record.choices,
            correct_answers=record.correct_answers,
            rationale=record.rationale,
            source_record_id=record.record_id,
        )
        for record in batch.records
    )
    question_id_by_record = {
        record.record_id: stable_id_by_record_id[record.record_id]
        for record in batch.records
    }
    findings = tuple(
        Finding(
            finding_id=f"PFV2-FIND-PARSE-{index:06d}",
            question_id=question_id_by_record[item.record_id],
            field=item.field,
            damage_type=item.damage_type,
            severity=(
                FindingSeverity.BLOCKING if item.blocking else FindingSeverity.ADVISORY
            ),
            explanation=item.explanation,
        )
        for index, item in enumerate(batch.findings, start=1)
    )
    return questions, findings
