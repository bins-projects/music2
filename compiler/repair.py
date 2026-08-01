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
    replacement = replacement.strip()
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


def apply_repair(pack: dict, record: RepairRecord) -> dict:
    if record.pack_id != pack.get("pack_id"):
        raise RepairError("Repair record belongs to a different Pack")

    candidate = copy.deepcopy(pack)
    question = find_question(candidate, record.question_id)
    current = get_text_field(question, record.field)
    if current != record.before:
        raise RepairError(
            "Repair no longer matches the current question field"
        )

    set_text_field(question, record.field, record.after)
    validate_candidate_question(question)
    return candidate


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


def write_repair_record(
    record: RepairRecord,
    path: str | Path,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(asdict(record), file, indent=2, ensure_ascii=False)
        file.write("\n")

    return destination
