from difflib import SequenceMatcher

from compiler.text_repairs import normalize_extraction_typography


class RecordMatchError(ValueError):
    """Raised when ordered intake records cannot be matched safely."""


def _text(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(normalize_extraction_typography(value).text.split()).casefold()


def _choices(question: dict) -> tuple[tuple[str, str], ...]:
    value = question.get("choices") or []
    if isinstance(value, dict):
        pairs = value.items()
    elif isinstance(value, list):
        pairs = (
            (choice.get("label"), choice.get("text"))
            for choice in value
            if isinstance(choice, dict)
        )
    else:
        pairs = ()
    return tuple((str(label).upper(), _text(text)) for label, text in pairs)


def _type(question: dict) -> str:
    value = str(question.get("type") or question.get("question_type") or "")
    return {
        "multiple_choice": "mc",
        "multiple_response": "multiple_response",
        "ordered_response": "ordered_response",
        "completion": "completion",
    }.get(value, value)


def _changed_fields(parsed: dict, target: dict) -> list[str]:
    fields = []
    if parsed.get("chapter") != target.get("chapter"):
        fields.append("chapter")
    if _type(parsed) != _type(target):
        fields.append("type")
    if _text(parsed.get("stem")) != _text(target.get("stem")):
        fields.append("stem")
    if _choices(parsed) != _choices(target):
        fields.append("choices")
    if tuple(parsed.get("correct_answers") or ()) != tuple(target.get("correct_answers") or ()):
        fields.append("correct_answers")
    if _text(parsed.get("rationale")) != _text(target.get("rationale")):
        fields.append("rationale")
    return fields


def match_ordered_records(parsed: list[dict], target_pack: dict) -> dict:
    targets = target_pack.get("questions")
    if not isinstance(targets, list):
        raise RecordMatchError("Target Pack questions must be a list")
    ids = [question.get("id") for question in targets]
    if any(not isinstance(question_id, str) or not question_id for question_id in ids):
        raise RecordMatchError("Target Pack has an invalid question ID")
    if len(set(ids)) != len(ids):
        raise RecordMatchError("Target Pack has duplicate question IDs")

    parsed_stems = [_text(question.get("stem")) for question in parsed]
    target_stems = [_text(question.get("stem")) for question in targets]
    matcher = SequenceMatcher(None, parsed_stems, target_stems, autojunk=False)
    matches = []
    parsed_only = []
    target_only = []

    def add_pair(parsed_index: int, target_index: int, classification: str) -> None:
        parsed_question = parsed[parsed_index]
        target_question = targets[target_index]
        similarity = SequenceMatcher(
            None,
            parsed_stems[parsed_index],
            target_stems[target_index],
            autojunk=False,
        ).ratio()
        matches.append(
            {
                "record_id": f"PFIR-{parsed_index + 1:09d}",
                "parsed_index": parsed_index,
                "chapter": parsed_question.get("chapter"),
                "source_question_number": parsed_question.get("question_number"),
                "target_question_id": target_question["id"],
                "classification": classification,
                "stem_similarity": round(similarity, 6),
                "changed_fields": _changed_fields(parsed_question, target_question),
            }
        )

    for tag, parsed_start, parsed_end, target_start, target_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(parsed_end - parsed_start):
                add_pair(parsed_start + offset, target_start + offset, "exact_stem")
            continue
        if tag == "replace" and parsed_end - parsed_start == target_end - target_start:
            for offset in range(parsed_end - parsed_start):
                add_pair(parsed_start + offset, target_start + offset, "changed_stem")
            continue
        if tag in {"replace", "delete"}:
            for index in range(parsed_start, parsed_end):
                question = parsed[index]
                parsed_only.append(
                    {
                        "record_id": f"PFIR-{index + 1:09d}",
                        "finding_id": f"PFIQA-BOUNDARY-{index + 1:09d}",
                        "parsed_index": index,
                        "chapter": question.get("chapter"),
                        "source_question_number": question.get("question_number"),
                        "question_type": _type(question),
                        "finding_code": "unmatched_parser_boundary",
                    }
                )
        if tag in {"replace", "insert"}:
            for index in range(target_start, target_end):
                target_only.append({"target_question_id": targets[index]["id"]})

    matches.sort(key=lambda item: item["parsed_index"])
    parsed_only.sort(key=lambda item: item["parsed_index"])
    target_only.sort(key=lambda item: item["target_question_id"])
    return {
        "target_pack_id": target_pack.get("pack_id"),
        "parsed_count": len(parsed),
        "target_count": len(targets),
        "matched_count": len(matches),
        "exact_stem_count": sum(item["classification"] == "exact_stem" for item in matches),
        "changed_stem_count": sum(item["classification"] == "changed_stem" for item in matches),
        "parsed_only_count": len(parsed_only),
        "target_only_count": len(target_only),
        "matches": matches,
        "parsed_only": parsed_only,
        "target_only": target_only,
    }
