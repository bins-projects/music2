"""Conservative cross-extraction recovery for known PDF overlay damage.

The source document remains authoritative. We use another native text reading
of the *same PDF* only when it identifies the same chapter/question/type and
provides a structurally valid, cleaner field. This is source recovery, never
old-Pack comparison or wording import.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from difflib import SequenceMatcher
import hashlib
import json
import math
import re

from compiler.text_repairs import APPROVED_TEXT_REPAIRS, interleaving_blockers
from ingestion_v2.parser import ParseBatch, ParsedRecord, ParserFinding


# The colored source overlay is visibly and consistently rendered as this
# signature.  The final M is frequently outside the overprinted text run, so
# the complete, locally observable signature ends at `.CO`.
INTERWOVEN_WATERMARK_SIGNATURE = "NURSINGTB.CO"
WORD_RE = re.compile(r"[A-Za-z]+")
SPACED_FRAGMENT_RE = re.compile(r"\b(?:[A-Za-z]{1,2}\s+){2,}[A-Za-z]{1,2}\b")
SPLIT_WORD_RE = re.compile(r"\b([A-Za-z]{4,})\s+([A-Za-z]{1,3})\b")
PREFIX_SPLIT_WORD_RE = re.compile(r"\b([A-Za-z])\s+([A-Za-z]{4,})\b")
# This is deliberately narrower than ordinary whitespace normalization. It is
# a sequence of one/two-letter fragments containing lowercase text; it cannot
# be an A/B/C-style option list. It is produced when an overlaid PDF watermark
# forces the native text layer to emit every underlying letter as a fragment.
LETTER_FRAGMENT_RUN_RE = re.compile(r"\b(?:[A-Za-z]{1,3}\s+){3,}[A-Za-z]{1,3}\b")
ALLOWED_SHORT_WORDS = frozenset({"a", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we"})


def reconcile_corroborated_fields(
    primary: ParseBatch, alternatives: tuple[ParseBatch, ...]
) -> ParseBatch:
    indexes = tuple(_unique_records_by_source_key(batch.records) for batch in alternatives)
    # Overlay segmentation deliberately relies on the primary reading alone:
    # noisy OCR alternatives can contain accidental long pseudo-words that
    # would otherwise win the segmentation score.
    source_word_counts = _source_word_counts((primary,))
    repaired: list[ParsedRecord] = []
    repair_count = 0
    for record in primary.records:
        alternates = [
            index[_source_key(record)]
            for index in indexes
            if _source_key(record) in index
        ]
        changes = {}
        for field in ("stem", "rationale"):
            original = getattr(record, field)
            normalized_primary = _normalize_source_spacing(original, source_word_counts)
            if (
                normalized_primary != original
                and not interleaving_blockers(normalized_primary)
            ):
                changes[field] = normalized_primary
                continue
            if not interleaving_blockers(original):
                continue
            candidates = [
                normalized
                for item in alternates
                if not interleaving_blockers(
                    normalized := _normalize_source_spacing(
                        getattr(item, field), source_word_counts
                    )
                )
                and _compatible_source_field(original, normalized)
            ]
            replacement = _closest_source_reading(original, candidates)
            if replacement is not None and replacement != original:
                changes[field] = replacement
            # When every native reading contains the overlay, recover only a
            # complete, visibly distinctive watermark signature. The remaining
            # letters must be segmentable entirely into words already present
            # elsewhere in this same source reading; otherwise it stays queued.
            if field not in changes:
                recovered = _recover_interwoven_watermark(original, source_word_counts)
                if recovered is not None:
                    recovered = _apply_approved_fragments(recovered)
                if recovered is not None and not interleaving_blockers(recovered):
                    changes[field] = recovered
        if _choice_structure_is_damaged(record):
            candidates = [
                item for item in alternates
                if _choice_structure_is_complete(item)
                and _similarity(record.stem, item.stem) >= 0.70
            ]
            if candidates:
                replacement = max(
                    candidates,
                    key=lambda item: _similarity(record.stem, item.stem),
                )
                if replacement.choices != record.choices:
                    changes["choices"] = replacement.choices
                if replacement.correct_answers != record.correct_answers:
                    changes["correct_answers"] = replacement.correct_answers
        elif any(interleaving_blockers(text) for _, text in record.choices):
            normalized_primary_choices = tuple(
                (label, _normalize_source_spacing(text, source_word_counts))
                for label, text in record.choices
            )
            if (
                normalized_primary_choices != record.choices
                and all(
                    not interleaving_blockers(text)
                    for _, text in normalized_primary_choices
                )
            ):
                changes["choices"] = normalized_primary_choices
                repaired.append(replace(record, **changes))
                repair_count += len(changes)
                continue
            candidates = []
            for item in alternates:
                if tuple(label for label, _ in item.choices) != tuple(label for label, _ in record.choices):
                    continue
                if item.correct_answers != record.correct_answers:
                    continue
                choices = tuple(
                    (label, _normalize_source_spacing(text, source_word_counts))
                    for label, text in item.choices
                )
                if all(not interleaving_blockers(text) for _, text in choices):
                    candidates.append(choices)
            if candidates:
                replacement = max(
                    candidates,
                    key=lambda choices: _similarity(
                        " ".join(text for _, text in record.choices),
                        " ".join(text for _, text in choices),
                    ),
                )
                if replacement != record.choices:
                    changes["choices"] = replacement
        if changes:
            repaired.append(replace(record, **changes))
            repair_count += len(changes)
        else:
            repaired.append(record)
    rebuilt_findings = _structural_findings(tuple(repaired))
    return ParseBatch(
        records=tuple(repaired),
        findings=rebuilt_findings,
        parser_name=primary.parser_name + "+corroborated_source_fields_v1",
        automatic_repairs=primary.automatic_repairs + repair_count,
    )


def recovery_plan(primary: ParseBatch, recovered: ParseBatch) -> dict:
    """Return a private, replayable plan anchored to the original parse values."""
    if len(primary.records) != len(recovered.records):
        raise ValueError("Source recovery must preserve the parsed record count")
    changes = []
    for before, after in zip(primary.records, recovered.records):
        if before.record_id != after.record_id:
            raise ValueError("Source recovery changed record identity")
        fields = {
            field: getattr(after, field)
            for field in ("stem", "choices", "correct_answers", "rationale")
            if getattr(before, field) != getattr(after, field)
        }
        if fields:
            changes.append({
                "record_id": before.record_id,
                "before_sha256": _record_hash(before),
                "fields": {
                    key: list(value) if key in {"choices", "correct_answers"} else value
                    for key, value in fields.items()
                },
            })
    return {"format": "prepflow_v2_source_recovery", "version": "1.0", "changes": changes}


def apply_recovery_plan(batch: ParseBatch, plan: dict) -> ParseBatch:
    """Replay a saved source recovery only against its exact original parse."""
    if plan.get("format") != "prepflow_v2_source_recovery" or plan.get("version") != "1.0":
        raise ValueError("Source recovery plan is malformed")
    by_id = {record.record_id: record for record in batch.records}
    replacements = {}
    for item in plan.get("changes", []):
        record = by_id.get(item.get("record_id"))
        fields = item.get("fields")
        if record is None or not isinstance(fields, dict) or _record_hash(record) != item.get("before_sha256"):
            raise ValueError("Source recovery plan does not match this parsed source")
        allowed = {key: value for key, value in fields.items() if key in {"stem", "choices", "correct_answers", "rationale"}}
        if len(allowed) != len(fields):
            raise ValueError("Source recovery plan contains an unsupported field")
        if "choices" in allowed:
            allowed["choices"] = tuple(tuple(choice) for choice in allowed["choices"])
        if "correct_answers" in allowed:
            allowed["correct_answers"] = tuple(allowed["correct_answers"])
        replacements[record.record_id] = replace(record, **allowed)
    records = tuple(replacements.get(record.record_id, record) for record in batch.records)
    return ParseBatch(
        records=records,
        findings=_structural_findings(records),
        parser_name=batch.parser_name + "+saved_source_recovery_v1",
        automatic_repairs=batch.automatic_repairs + sum(len(item["fields"]) for item in plan.get("changes", [])),
    )


def _source_key(record: ParsedRecord) -> tuple[int | None, int | None, str]:
    return (record.chapter, record.source_question_number, record.question_type)


def _unique_records_by_source_key(records: tuple[ParsedRecord, ...]) -> dict:
    grouped: dict[tuple[int | None, int | None, str], list[ParsedRecord]] = defaultdict(list)
    for record in records:
        grouped[_source_key(record)].append(record)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def _closest_source_reading(original: str, values: list[str]) -> str | None:
    usable = [value for value in values if value.strip()]
    if not usable:
        return None
    return max(usable, key=lambda value: _similarity(original, value))


def _compatible_source_field(original: str, candidate: str) -> bool:
    """Reject a clean alternate that has absorbed neighboring source text."""
    baseline = len(_normalized(original))
    observed = len(_normalized(candidate))
    if not baseline or not observed:
        return False
    # A reading may repair spacing or lose an overlay, but a 25% expansion is
    # not a field repair—it is evidence of a parser boundary disagreement.
    return observed <= baseline * 1.25 and observed >= baseline * 0.55


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _source_word_counts(batches: tuple[ParseBatch, ...]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for batch in batches:
        for record in batch.records:
            for value in (record.stem, record.rationale, *(text for _, text in record.choices)):
                for word in WORD_RE.findall(value.casefold()):
                    counts[word] += 1
    return counts


def _recover_interwoven_watermark(text: str, word_counts: dict[str, int]) -> str | None:
    positions = _interwoven_signature_positions(text, INTERWOVEN_WATERMARK_SIGNATURE)
    if positions is None:
        return None
    without_signature = "".join(
        character for index, character in enumerate(text) if index not in set(positions)
    )
    insertion = positions[0] - sum(index < positions[0] for index in positions)
    left = _last_word_boundary(without_signature, insertion)
    right = _next_word_boundary(without_signature, insertion)
    if left is None or right is None:
        return None
    region = without_signature[left:right]
    if len(region) > 80 or not re.fullmatch(r"[A-Za-z\s]+", region) or region.count(" ") < 4:
        return None
    words = _segment_source_letters("".join(WORD_RE.findall(region.casefold())), word_counts)
    if words is None or len(words) < 2:
        return None
    return without_signature[:left] + " " + " ".join(words) + " " + without_signature[right:]


def _interwoven_signature_positions(text: str, signature: str) -> tuple[int, ...] | None:
    """Find one tight uppercase overlay run, never ordinary sentence text."""
    best: tuple[int, ...] | None = None
    for start, character in enumerate(text):
        if character != signature[0]:
            continue
        positions = [start]
        cursor = start + 1
        for target in signature[1:]:
            while cursor < len(text) and text[cursor] != target:
                cursor += 1
            if cursor == len(text):
                break
            positions.append(cursor)
            cursor += 1
        if len(positions) != len(signature) or positions[-1] - positions[0] + 1 > 45:
            continue
        if best is None or positions[-1] - positions[0] < best[-1] - best[0]:
            best = tuple(positions)
    return best


def _last_word_boundary(text: str, position: int) -> int | None:
    words = [match for match in WORD_RE.finditer(text) if match.end() <= position and len(match.group()) >= 5]
    return words[-1].end() if words else None


def _next_word_boundary(text: str, position: int) -> int | None:
    match = next((match for match in WORD_RE.finditer(text) if match.start() >= position and len(match.group()) >= 5), None)
    return match.start() if match else None


def _segment_source_letters(value: str, word_counts: dict[str, int]) -> list[str] | None:
    """Segment a short overlay-fragment run using only same-source vocabulary."""
    if not value:
        return None
    score: list[tuple[float, list[str]] | None] = [None] * (len(value) + 1)
    score[0] = (0.0, [])
    for start in range(len(value)):
        if score[start] is None:
            continue
        for end in range(start + 1, min(len(value), start + 24) + 1):
            word = value[start:end]
            count = word_counts.get(word, 0)
            if not count:
                continue
            # Long observed words beat a collection of incidental fragments;
            # frequency breaks ties without importing an external dictionary.
            candidate = score[start][0] + len(word) ** 1.5 - 0.5 * math.log(count + 1)
            if score[end] is None or candidate > score[end][0]:
                score[end] = (candidate, score[start][1] + [word])
    return score[-1][1] if score[-1] is not None else None


def _apply_approved_fragments(text: str) -> str:
    for rule in APPROVED_TEXT_REPAIRS:
        text = rule.pattern.sub(rule.replacement, text)
    return text


def _normalize_source_spacing(text: str, word_counts: dict[str, int]) -> str:
    """Normalize only source-attested spacing scars in an alternate reading.

    It never invents a word: joins/splits are accepted only when the result is
    observed elsewhere in the primary source reading. This is used only while
    evaluating a same-PDF alternate source layer, not as a global cleaner.
    """
    def join_letter_fragments(match: re.Match) -> str:
        parts = match.group().split()
        if (
            len(parts) >= 3
            and sum(len(part) for part in parts) >= 6
            and all(len(part) <= 3 for part in parts)
            and sum(len(part) == 1 for part in parts) >= 2
            and any(character.islower() for character in match.group())
        ):
            # This preserves exactly the extracted letters. It does not select
            # an answer or infer a missing term; later source-attested
            # segmentation may restore word boundaries when they are known.
            joined = "".join(parts)
            source_words = _segment_source_letters(joined.casefold(), word_counts)
            if source_words is not None and len(source_words) >= 1:
                value = " ".join(source_words)
                return value.capitalize() if joined[0].isupper() else value
            # Do not absorb an ordinary short word immediately before the
            # fragmented run (for example ``be c o m p r o m i s e d``).
            if parts[0].casefold() in ALLOWED_SHORT_WORDS:
                return parts[0] + " " + "".join(parts[1:])
            return joined
        return match.group()

    compacted = LETTER_FRAGMENT_RUN_RE.sub(join_letter_fragments, text)

    def join_fragments(match: re.Match) -> str:
        joined = "".join(match.group().split())
        if joined.casefold() in word_counts:
            return joined
        words = _segment_source_letters(joined.casefold(), word_counts)
        if (
            words is not None
            and len(words) >= 2
            and all(
                len(word) >= 3 or word in ALLOWED_SHORT_WORDS for word in words
            )
            and all(
                word_counts.get(word, 0) >= 2
                for word in words
                if word not in ALLOWED_SHORT_WORDS
            )
        ):
            return " ".join(words)
        return match.group()

    repaired = SPACED_FRAGMENT_RE.sub(join_fragments, compacted)

    def join_attested_split_word(match: re.Match) -> str:
        joined = match.group(1) + match.group(2)
        return joined if joined.casefold() in word_counts else match.group()

    repaired = SPLIT_WORD_RE.sub(join_attested_split_word, repaired)
    repaired = PREFIX_SPLIT_WORD_RE.sub(join_attested_split_word, repaired)

    def split_known_words(match: re.Match) -> str:
        token = match.group()
        if token.casefold() in word_counts or len(token) < 7:
            return token
        words = _segment_source_letters(token.casefold(), word_counts)
        if words is None or len(words) < 2 or any(
            len(word) < 3 and word not in ALLOWED_SHORT_WORDS for word in words
        ):
            return token
        # Do not turn an unfamiliar clinical or proper term into arbitrary
        # fragments. Each recovered component must be independently attested.
        if any(word_counts.get(word, 0) < 2 for word in words if word not in ALLOWED_SHORT_WORDS):
            return token
        value = " ".join(words)
        return value.capitalize() if token[0].isupper() else value

    return re.sub(r"\s+([,.;:!?])", r"\1", WORD_RE.sub(split_known_words, repaired))


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized(left), _normalized(right)).ratio()


def _choice_structure_is_complete(record: ParsedRecord) -> bool:
    labels = tuple(label for label, _ in record.choices)
    expected = tuple(chr(ord("A") + index) for index in range(len(labels)))
    return bool(labels) and labels == expected and bool(record.correct_answers) and set(record.correct_answers).issubset(labels)


def _choice_structure_is_damaged(record: ParsedRecord) -> bool:
    labels = tuple(label for label, _ in record.choices)
    expected = tuple(chr(ord("A") + index) for index in range(len(labels)))
    return labels != expected or not record.correct_answers or not set(record.correct_answers).issubset(labels)


def _structural_findings(records: tuple[ParsedRecord, ...]) -> tuple[ParserFinding, ...]:
    # Re-run the same conservative structural checks after a source-backed
    # field substitution, without attempting any new parser repair.
    from ingestion_v2.parser import _structural_findings as findings_for_record

    findings = []
    for record in records:
        for field, damage_type, explanation in findings_for_record(record):
            findings.append(ParserFinding(
                finding_id=f"PFV2-PARSE-FIND-{len(findings) + 1:06d}",
                record_id=record.record_id,
                field=field,
                damage_type=damage_type,
                explanation=explanation,
            ))
    return tuple(findings)


def _record_hash(record: ParsedRecord) -> str:
    value = {
        "record_id": record.record_id, "chapter": record.chapter,
        "chapter_title": record.chapter_title,
        "source_question_number": record.source_question_number,
        "question_type": record.question_type, "stem": record.stem,
        "choices": record.choices, "correct_answers": record.correct_answers,
        "rationale": record.rationale,
    }
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
