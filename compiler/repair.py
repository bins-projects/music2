import copy
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


TEXT_FIELD_RE = re.compile(
    r"^(?:stem|rationale|chapter_title|choices\[(\d+)]\.text)$"
)
LEDGER_PATH_RE = re.compile(r"^\$\.questions\[\d+]\.(.+)$")
CHOICE_REQUIRED_TYPES = {"mc", "multiple_response", "ordered_response"}
REPAIR_DISPOSITIONS = {
    "one_question",
    "detector_candidate",
    "repair_rule_candidate",
    "parser_candidate",
    "validation_candidate",
    "promotion_blocker",
}


class RepairError(ValueError):
    """Raised when a repair cannot be applied safely."""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    question_id: str
    field: str
    damage_type: str


@dataclass(frozen=True)
class RepairRecord:
    format: str
    version: str
    repair_id: str
    pack_id: str
    question_id: str
    field: str
    before: str
    after: str
    damage_type: str
    approval: str
    disposition: str


@dataclass(frozen=True)
class StemChoiceSplitRecord:
    format: str
    version: str
    repair_id: str
    pack_id: str
    question_id: str
    before_stem: str
    after_stem: str
    expected_choice_labels: tuple[str, ...]
    insert_index: int
    insert_label: str
    insert_text: str
    damage_type: str
    approval: str
    disposition: str


@dataclass(frozen=True)
class DuplicateChoiceBlockRecord:
    format: str
    version: str
    repair_id: str
    pack_id: str
    question_id: str
    expected_choices: tuple[tuple[str, str], ...]
    retained_choices: tuple[tuple[str, str], ...]
    damage_type: str
    approval: str
    disposition: str


@dataclass(frozen=True)
class ChoiceStructureRepairRecord:
    format: str
    version: str
    repair_id: str
    pack_id: str
    question_id: str
    expected_choices: tuple[tuple[str, str], ...]
    replacement_choices: tuple[tuple[str, str], ...]
    expected_correct_answers: tuple[str, ...]
    replacement_correct_answers: tuple[str, ...]
    damage_type: str
    approval: str
    disposition: str


@dataclass(frozen=True)
class RepairDeltaAnalysis:
    classification: str
    removed_characters: int


REPAIR_RECORD_FIELDS = {
    field.name for field in RepairRecord.__dataclass_fields__.values()
}
STEM_CHOICE_SPLIT_FIELDS = {
    field.name for field in StemChoiceSplitRecord.__dataclass_fields__.values()
}
DUPLICATE_CHOICE_BLOCK_FIELDS = {
    field.name for field in DuplicateChoiceBlockRecord.__dataclass_fields__.values()
}
CHOICE_STRUCTURE_REPAIR_FIELDS = {
    field.name for field in ChoiceStructureRepairRecord.__dataclass_fields__.values()
}
RepairEntry = (
    RepairRecord
    | StemChoiceSplitRecord
    | DuplicateChoiceBlockRecord
    | ChoiceStructureRepairRecord
)


def load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise RepairError(f"Expected a JSON object: {path}")

    return value


def load_pack(path: str | Path) -> dict:
    pack = load_json(path)

    if pack.get("format") != "prepflow_pack":
        raise RepairError("Expected a PrepFlow Pack")
    if not isinstance(pack.get("pack_id"), str) or not pack["pack_id"]:
        raise RepairError("Pack is missing pack_id")
    if not isinstance(pack.get("questions"), list):
        raise RepairError("Pack questions must be a list")

    return pack


def ledger_path_to_field(json_path: str) -> str:
    match = LEDGER_PATH_RE.fullmatch(json_path)
    if not match:
        raise RepairError(f"Unsupported QA ledger path: {json_path}")

    field = match.group(1)
    require_text_field(field)
    return field


def load_findings(path: str | Path) -> list[Finding]:
    ledger = load_json(path)
    entries = ledger.get("entries")

    if not isinstance(entries, list):
        raise RepairError("QA ledger entries must be a list")

    findings = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RepairError("QA ledger entry must be an object")

        findings.append(
            Finding(
                finding_id=str(entry.get("repair_id") or "").strip(),
                question_id=str(entry.get("question_id") or "").strip(),
                field=ledger_path_to_field(
                    str(entry.get("json_path") or "")
                ),
                damage_type=str(entry.get("rule") or "unclassified").strip(),
            )
        )

    if any(not finding.finding_id for finding in findings):
        raise RepairError("Every QA finding must have an identifier")
    if any(not finding.question_id for finding in findings):
        raise RepairError("Every QA finding must have a question identifier")

    return findings


def select_finding(
    findings: list[Finding],
    *,
    finding_id: str | None = None,
    question_id: str | None = None,
) -> Finding:
    if finding_id:
        matches = [item for item in findings if item.finding_id == finding_id]
    elif question_id:
        matches = [item for item in findings if item.question_id == question_id]
    else:
        if not findings:
            raise RepairError("QA ledger contains no findings")
        return findings[0]

    if not matches:
        label = finding_id or question_id
        raise RepairError(f"Finding not found: {label}")

    return matches[0]


def find_question(pack: dict, question_id: str) -> dict:
    matches = [
        question
        for question in pack["questions"]
        if question.get("id") == question_id
    ]

    if not matches:
        raise RepairError(f"Question not found: {question_id}")
    if len(matches) > 1:
        raise RepairError(f"Duplicate question identifier: {question_id}")

    return matches[0]


def require_text_field(field: str) -> re.Match:
    match = TEXT_FIELD_RE.fullmatch(field)
    if not match:
        raise RepairError(f"Unsupported repair field: {field}")
    return match


def get_text_field(question: dict, field: str) -> str:
    match = require_text_field(field)
    choice_index = match.group(1)

    if choice_index is None:
        value = question.get(field)
    else:
        choices = question.get("choices")
        if not isinstance(choices, list):
            raise RepairError("Question choices must be a list")

        index = int(choice_index)
        if index >= len(choices):
            raise RepairError(f"Choice index is out of range: {index}")
        value = choices[index].get("text")

    if not isinstance(value, str):
        raise RepairError(f"Repair field is not text: {field}")

    return value


def set_text_field(question: dict, field: str, value: str) -> None:
    match = require_text_field(field)
    choice_index = match.group(1)

    if choice_index is None:
        question[field] = value
    else:
        question["choices"][int(choice_index)]["text"] = value


def validate_candidate_question(question: dict) -> None:
    required_text = {"id", "chapter_title", "type", "stem", "rationale"}
    for field in required_text:
        if not isinstance(question.get(field), str):
            raise RepairError(f"Question {field} must be text")

    if not question["id"].strip():
        raise RepairError("Question ID must not be empty")
    if not question["stem"].strip():
        raise RepairError("Question stem must not be empty")

    answers = question.get("correct_answers")
    if not isinstance(answers, list) or not answers:
        raise RepairError("Question must have at least one correct answer")

    choices = question.get("choices")
    if question["type"] in CHOICE_REQUIRED_TYPES:
        if not isinstance(choices, list) or not choices:
            raise RepairError(
                f"Question type {question['type']} requires choices"
            )

        labels = set()
        for choice in choices:
            if not isinstance(choice, dict):
                raise RepairError("Each choice must be an object")
            label = choice.get("label")
            text = choice.get("text")
            if not isinstance(label, str) or not label:
                raise RepairError("Each choice must have a label")
            if not isinstance(text, str) or not text.strip():
                raise RepairError("Each choice must have text")
            if label in labels:
                raise RepairError(f"Duplicate choice label: {label}")
            labels.add(label)

        missing = [answer for answer in answers if answer not in labels]
        if missing:
            raise RepairError(
                "Correct answer references missing choice: "
                + ", ".join(str(answer) for answer in missing)
            )


def create_repair_record(
    pack: dict,
    finding: Finding,
    replacement: str,
    *,
    disposition: str = "one_question",
) -> RepairRecord:
    if disposition not in REPAIR_DISPOSITIONS:
        raise RepairError(f"Unsupported repair disposition: {disposition}")

    replacement = normalize_replacement_text(replacement)
    if not replacement:
        raise RepairError("Replacement text must not be empty")

    question = find_question(pack, finding.question_id)
    before = get_text_field(question, finding.field)
    if before == replacement:
        raise RepairError("Replacement text is unchanged")

    return RepairRecord(
        format="prepflow_repair_record",
        version="1.0",
        repair_id=finding.finding_id,
        pack_id=pack["pack_id"],
        question_id=finding.question_id,
        field=finding.field,
        before=before,
        after=replacement,
        damage_type=finding.damage_type,
        approval="approved",
        disposition=disposition,
    )


def create_stem_choice_split_record(
    pack: dict,
    finding: Finding,
    corrected_stem: str,
    *,
    insert_label: str,
    insert_text: str,
    insert_index: int = 0,
    disposition: str = "parser_candidate",
) -> StemChoiceSplitRecord:
    if disposition not in REPAIR_DISPOSITIONS:
        raise RepairError(f"Unsupported repair disposition: {disposition}")
    if finding.field != "stem":
        raise RepairError("Stem-choice split finding must target the stem")

    corrected_stem = normalize_replacement_text(corrected_stem)
    insert_text = normalize_replacement_text(insert_text)
    insert_label = insert_label.strip()
    if not corrected_stem or not insert_text or not insert_label:
        raise RepairError("Structural repair values must not be empty")

    question = find_question(pack, finding.question_id)
    choices = question.get("choices")
    if not isinstance(choices, list):
        raise RepairError("Question choices must be a list")
    labels = tuple(str(choice.get("label") or "") for choice in choices)
    if insert_label in labels:
        raise RepairError(f"Choice label already exists: {insert_label}")
    if insert_index < 0 or insert_index > len(choices):
        raise RepairError(f"Choice insertion index is out of range: {insert_index}")

    return StemChoiceSplitRecord(
        format="prepflow_stem_choice_split_record",
        version="1.0",
        repair_id=finding.finding_id,
        pack_id=pack["pack_id"],
        question_id=finding.question_id,
        before_stem=question["stem"],
        after_stem=corrected_stem,
        expected_choice_labels=labels,
        insert_index=insert_index,
        insert_label=insert_label,
        insert_text=insert_text,
        damage_type=finding.damage_type,
        approval="approved",
        disposition=disposition,
    )


def choice_pairs(question: dict) -> tuple[tuple[str, str], ...]:
    choices = question.get("choices")
    if not isinstance(choices, list):
        raise RepairError("Question choices must be a list")

    pairs = []
    for choice in choices:
        if not isinstance(choice, dict):
            raise RepairError("Each choice must be an object")
        label = choice.get("label")
        text = choice.get("text")
        if not isinstance(label, str) or not label:
            raise RepairError("Each choice must have a label")
        if not isinstance(text, str) or not text.strip():
            raise RepairError("Each choice must have text")
        pairs.append((label, text))
    return tuple(pairs)


def exact_duplicate_choice_block(
    question: dict,
) -> tuple[tuple[str, str], ...] | None:
    try:
        pairs = choice_pairs(question)
    except RepairError:
        return None
    if len(pairs) < 4 or len(pairs) % 2:
        return None

    midpoint = len(pairs) // 2
    retained = pairs[:midpoint]
    if retained != pairs[midpoint:]:
        return None

    labels = tuple(label for label, _ in retained)
    expected_labels = tuple(chr(ord("A") + index) for index in range(midpoint))
    if labels != expected_labels:
        return None

    answers = question.get("correct_answers")
    if not isinstance(answers, list) or not answers:
        return None
    if any(str(answer) not in labels for answer in answers):
        return None
    return retained


def create_duplicate_choice_block_record(
    pack: dict,
    *,
    question_id: str,
    repair_id: str,
    disposition: str = "repair_rule_candidate",
) -> DuplicateChoiceBlockRecord:
    if disposition not in REPAIR_DISPOSITIONS:
        raise RepairError(f"Unsupported repair disposition: {disposition}")

    question = find_question(pack, question_id)
    retained = exact_duplicate_choice_block(question)
    if retained is None:
        raise RepairError("Question does not contain one exact duplicate choice block")

    return DuplicateChoiceBlockRecord(
        format="prepflow_duplicate_choice_block_record",
        version="1.0",
        repair_id=repair_id,
        pack_id=pack["pack_id"],
        question_id=question_id,
        expected_choices=choice_pairs(question),
        retained_choices=retained,
        damage_type="choice structure: exact duplicate choice block",
        approval="approved",
        disposition=disposition,
    )


def create_choice_structure_repair_record(
    pack: dict,
    *,
    question_id: str,
    repair_id: str,
    replacement_choices: tuple[tuple[str, str], ...],
    replacement_correct_answers: tuple[str, ...],
    damage_type: str,
    disposition: str = "one_question",
) -> ChoiceStructureRepairRecord:
    if disposition not in REPAIR_DISPOSITIONS:
        raise RepairError(f"Unsupported repair disposition: {disposition}")

    question = find_question(pack, question_id)
    expected_choices = choice_pairs(question)
    expected_answers = question.get("correct_answers")
    if not isinstance(expected_answers, list) or not expected_answers:
        raise RepairError("Question must have at least one correct answer")
    if not replacement_choices:
        raise RepairError("Structural repair must retain at least one choice")
    if not replacement_correct_answers:
        raise RepairError("Structural repair must retain a correct answer")
    if (
        expected_choices == replacement_choices
        and tuple(str(item) for item in expected_answers)
        == replacement_correct_answers
    ):
        raise RepairError("Structural replacement is unchanged")

    proposed = copy.deepcopy(question)
    proposed["choices"] = [
        {"label": label, "text": text}
        for label, text in replacement_choices
    ]
    proposed["correct_answers"] = list(replacement_correct_answers)
    validate_candidate_question(proposed)

    return ChoiceStructureRepairRecord(
        format="prepflow_choice_structure_repair_record",
        version="1.0",
        repair_id=repair_id,
        pack_id=pack["pack_id"],
        question_id=question_id,
        expected_choices=expected_choices,
        replacement_choices=replacement_choices,
        expected_correct_answers=tuple(str(item) for item in expected_answers),
        replacement_correct_answers=replacement_correct_answers,
        damage_type=damage_type,
        approval="approved",
        disposition=disposition,
    )


def normalize_replacement_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def deletion_subsequence(before: str, after: str) -> str | None:
    compact_before = re.sub(r"\s+", "", before)
    compact_after = re.sub(r"\s+", "", after)
    after_index = 0
    removed = []
    for character in compact_before:
        if (
            after_index < len(compact_after)
            and character == compact_after[after_index]
        ):
            after_index += 1
        else:
            removed.append(character)

    if after_index != len(compact_after):
        return None
    return "".join(removed)


def analyze_repair_delta(before: str, after: str) -> RepairDeltaAnalysis:
    compact_before = re.sub(r"\s+", "", before)
    compact_after = re.sub(r"\s+", "", after)
    if compact_before == compact_after:
        return RepairDeltaAnalysis("whitespace_only", 0)

    if compact_before.startswith(compact_after):
        return RepairDeltaAnalysis(
            "trailing_metadata_removed",
            len(compact_before) - len(compact_after),
        )

    removed_text = deletion_subsequence(before, after)
    if removed_text is None:
        return RepairDeltaAnalysis("manual_text_rewrite", 0)
    removed = list(removed_text)

    overlay_like = (
        len(removed) >= 4
        and any(character.isupper() for character in removed)
        and all(
            character.isupper() or not character.isalpha()
            for character in removed
        )
    )
    classification = (
        "uppercase_overlay_fragment_removed"
        if overlay_like
        else "character_deletion_candidate"
    )
    return RepairDeltaAnalysis(classification, len(removed))


def apply_repair(pack: dict, record: RepairEntry) -> dict:
    return apply_repairs(pack, [record])


def apply_repairs(pack: dict, records: list[RepairEntry]) -> dict:
    candidate = copy.deepcopy(pack)
    seen_ids = set()

    for record in records:
        if record.repair_id in seen_ids:
            raise RepairError(f"Duplicate repair identifier: {record.repair_id}")
        seen_ids.add(record.repair_id)

        if isinstance(record, StemChoiceSplitRecord):
            apply_stem_choice_split_to_candidate(candidate, record)
        elif isinstance(record, DuplicateChoiceBlockRecord):
            apply_duplicate_choice_block_to_candidate(candidate, record)
        elif isinstance(record, ChoiceStructureRepairRecord):
            apply_choice_structure_repair_to_candidate(candidate, record)
        else:
            apply_repair_to_candidate(candidate, record)

    return candidate


def apply_repair_to_candidate(candidate: dict, record: RepairRecord) -> None:
    if record.pack_id != candidate.get("pack_id"):
        raise RepairError("Repair record belongs to a different Pack")

    question = find_question(candidate, record.question_id)
    current = get_text_field(question, record.field)
    if current != record.before:
        raise RepairError(
            "Repair no longer matches the current question field"
        )

    set_text_field(question, record.field, record.after)
    validate_candidate_question(question)


def apply_stem_choice_split_to_candidate(
    candidate: dict,
    record: StemChoiceSplitRecord,
) -> None:
    if record.pack_id != candidate.get("pack_id"):
        raise RepairError("Repair record belongs to a different Pack")

    question = find_question(candidate, record.question_id)
    if question.get("stem") != record.before_stem:
        raise RepairError("Structural repair no longer matches the current stem")
    choices = question.get("choices")
    if not isinstance(choices, list):
        raise RepairError("Question choices must be a list")
    labels = tuple(str(choice.get("label") or "") for choice in choices)
    if labels != record.expected_choice_labels:
        raise RepairError("Structural repair no longer matches current choices")

    question["stem"] = record.after_stem
    choices.insert(
        record.insert_index,
        {"label": record.insert_label, "text": record.insert_text},
    )
    validate_candidate_question(question)


def apply_duplicate_choice_block_to_candidate(
    candidate: dict,
    record: DuplicateChoiceBlockRecord,
) -> None:
    if record.pack_id != candidate.get("pack_id"):
        raise RepairError("Repair record belongs to a different Pack")

    question = find_question(candidate, record.question_id)
    if choice_pairs(question) != record.expected_choices:
        raise RepairError(
            "Duplicate-choice repair no longer matches current choices"
        )
    if record.expected_choices != record.retained_choices * 2:
        raise RepairError("Duplicate-choice repair is not an exact repeated block")
    if exact_duplicate_choice_block(question) != record.retained_choices:
        raise RepairError("Duplicate-choice repair is no longer mechanically safe")

    question["choices"] = [
        {"label": label, "text": text}
        for label, text in record.retained_choices
    ]
    validate_candidate_question(question)


def apply_choice_structure_repair_to_candidate(
    candidate: dict,
    record: ChoiceStructureRepairRecord,
) -> None:
    if record.pack_id != candidate.get("pack_id"):
        raise RepairError("Repair record belongs to a different Pack")

    question = find_question(candidate, record.question_id)
    if choice_pairs(question) != record.expected_choices:
        raise RepairError(
            "Choice-structure repair no longer matches current choices"
        )
    current_answers = question.get("correct_answers")
    if (
        not isinstance(current_answers, list)
        or tuple(str(item) for item in current_answers)
        != record.expected_correct_answers
    ):
        raise RepairError(
            "Choice-structure repair no longer matches current answers"
        )

    question["choices"] = [
        {"label": label, "text": text}
        for label, text in record.replacement_choices
    ]
    question["correct_answers"] = list(record.replacement_correct_answers)
    validate_candidate_question(question)


def choice_pair_tuple(value: object, *, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise RepairError(f"Duplicate-choice {field} must be a list")
    pairs = []
    for pair in value:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) for item in pair)
        ):
            raise RepairError(f"Duplicate-choice {field} is malformed")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)


def repair_record_from_dict(value: object) -> RepairEntry:
    if not isinstance(value, dict):
        raise RepairError("Repair record must be an object")

    if value.get("format") == "prepflow_stem_choice_split_record":
        if set(value) != STEM_CHOICE_SPLIT_FIELDS:
            raise RepairError("Structural repair fields do not match the schema")
        converted = dict(value)
        labels = converted.get("expected_choice_labels")
        if not isinstance(labels, list):
            raise RepairError("Structural repair choice labels must be a list")
        converted["expected_choice_labels"] = tuple(labels)
        record = StemChoiceSplitRecord(**converted)
        if record.version != "1.0":
            raise RepairError("Unsupported structural repair format")
        if record.disposition not in REPAIR_DISPOSITIONS:
            raise RepairError(
                f"Unsupported repair disposition: {record.disposition}"
            )
        return record

    if value.get("format") == "prepflow_duplicate_choice_block_record":
        if set(value) != DUPLICATE_CHOICE_BLOCK_FIELDS:
            raise RepairError("Duplicate-choice repair fields do not match the schema")
        converted = dict(value)
        converted["expected_choices"] = choice_pair_tuple(
            converted.get("expected_choices"),
            field="expected choices",
        )
        converted["retained_choices"] = choice_pair_tuple(
            converted.get("retained_choices"),
            field="retained choices",
        )
        record = DuplicateChoiceBlockRecord(**converted)
        if record.version != "1.0":
            raise RepairError("Unsupported duplicate-choice repair format")
        if record.disposition not in REPAIR_DISPOSITIONS:
            raise RepairError(
                f"Unsupported repair disposition: {record.disposition}"
            )
        if record.expected_choices != record.retained_choices * 2:
            raise RepairError("Duplicate-choice repair is not an exact repeated block")
        return record

    if value.get("format") == "prepflow_choice_structure_repair_record":
        if set(value) != CHOICE_STRUCTURE_REPAIR_FIELDS:
            raise RepairError(
                "Choice-structure repair fields do not match the schema"
            )
        converted = dict(value)
        converted["expected_choices"] = choice_pair_tuple(
            converted.get("expected_choices"),
            field="expected choices",
        )
        converted["replacement_choices"] = choice_pair_tuple(
            converted.get("replacement_choices"),
            field="replacement choices",
        )
        for field in (
            "expected_correct_answers",
            "replacement_correct_answers",
        ):
            answers = converted.get(field)
            if (
                not isinstance(answers, list)
                or not answers
                or not all(isinstance(item, str) for item in answers)
            ):
                raise RepairError(
                    f"Choice-structure {field.replace('_', ' ')} must be a "
                    "non-empty text list"
                )
            converted[field] = tuple(answers)
        record = ChoiceStructureRepairRecord(**converted)
        if record.version != "1.0":
            raise RepairError("Unsupported choice-structure repair format")
        if record.disposition not in REPAIR_DISPOSITIONS:
            raise RepairError(
                f"Unsupported repair disposition: {record.disposition}"
            )
        return record

    if set(value) != REPAIR_RECORD_FIELDS:
        raise RepairError("Repair record fields do not match the schema")

    record = RepairRecord(**value)
    if record.format != "prepflow_repair_record" or record.version != "1.0":
        raise RepairError("Unsupported repair record format")
    if record.disposition not in REPAIR_DISPOSITIONS:
        raise RepairError(
            f"Unsupported repair disposition: {record.disposition}"
        )
    return record


def load_repair_records(path: str | Path) -> list[RepairEntry]:
    source = Path(path)
    if not source.exists():
        return []

    payload = load_json(source)
    if payload.get("format") == "prepflow_repair_record":
        return [repair_record_from_dict(payload)]
    if payload.get("format") != "prepflow_repair_set":
        raise RepairError("Unsupported repair collection format")
    if payload.get("version") != "1.0":
        raise RepairError("Unsupported repair collection version")

    values = payload.get("repairs")
    if not isinstance(values, list):
        raise RepairError("Repair collection must contain a repairs list")

    records = [repair_record_from_dict(value) for value in values]
    pack_id = payload.get("pack_id")
    if any(record.pack_id != pack_id for record in records):
        raise RepairError("Repair collection contains a different Pack ID")
    if len({record.repair_id for record in records}) != len(records):
        raise RepairError("Repair collection contains duplicate identifiers")
    return records


def write_candidate_pack(
    candidate: dict,
    *,
    canonical_path: str | Path,
    candidate_path: str | Path,
) -> Path:
    canonical = Path(canonical_path).resolve()
    destination = Path(candidate_path).resolve()

    if destination == canonical:
        raise RepairError("Candidate path must not overwrite the canonical Pack")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(candidate, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return destination


def write_repair_set(
    records: list[RepairEntry],
    path: str | Path,
) -> Path:
    if not records:
        raise RepairError("Cannot write an empty repair collection")
    pack_ids = {record.pack_id for record in records}
    if len(pack_ids) != 1:
        raise RepairError("Repair collection must belong to one Pack")
    if len({record.repair_id for record in records}) != len(records):
        raise RepairError("Repair collection contains duplicate identifiers")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = {
        "format": "prepflow_repair_set",
        "version": "1.0",
        "pack_id": next(iter(pack_ids)),
        "repairs": [asdict(record) for record in records],
    }
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")
    temporary.replace(destination)

    return destination
