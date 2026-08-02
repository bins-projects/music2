import argparse
import json
from pathlib import Path

from compiler.candidate import build_candidate
from compiler.cleaner import clean_text_generalized
from compiler.noise_profile import preview_remove_profiled_noise
from compiler.normalizer import normalize_questions
from compiler.record_match import match_ordered_records
from compiler.repair import load_pack
from compiler.source_parser import parse_source_questions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview repeated-noise removal fully in memory.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--id-pack", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    return parser


def candidate_from_alignment(records: list[dict], alignment: dict, target: dict) -> dict:
    by_id = {item["target_question_id"]: records[item["parsed_index"]] for item in alignment["matches"]}
    questions = []
    for target_question in target["questions"]:
        record = by_id[target_question["id"]]
        question_type = record.get("question_type")
        questions.append(
            {
                "id": target_question["id"],
                "chapter": record.get("chapter"),
                "chapter_title": record.get("chapter_title") or "",
                "type": "mc" if question_type == "multiple_choice" else question_type,
                "stem": record.get("stem") or "",
                "choices": record.get("choices") or [],
                "correct_answers": record.get("correct_answers") or [],
                "rationale": record.get("rationale") or "",
            }
        )
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": target.get("pack_id"),
        "title": target.get("title"),
        "questions": questions,
    }


def evaluate(raw: str, id_pack: dict, benchmark: dict) -> dict:
    cleaned = clean_text_generalized(raw)
    records = normalize_questions(
        parse_source_questions(cleaned, allow_missing_a_recovery=False)
    )
    alignment = match_ordered_records(records, id_pack)
    if alignment["target_only_count"]:
        return {
            "records": len(records),
            "matched": alignment["matched_count"],
            "parsed_only": alignment["parsed_only_count"],
            "target_only": alignment["target_only_count"],
            "field_differences": None,
            "blockers": None,
        }
    candidate = build_candidate(candidate_from_alignment(records, alignment, id_pack), [])
    target = build_candidate(benchmark, [])
    current = {question["id"]: question for question in candidate.candidate["questions"]}
    expected = {question["id"]: question for question in target.candidate["questions"]}
    fields = ("chapter", "chapter_title", "type", "stem", "choices", "correct_answers", "rationale")
    differences = sum(
        current[question_id].get(field) != expected[question_id].get(field)
        for question_id in current
        for field in fields
    )
    current_blockers = {
        (item.question_id, item.field) for item in candidate.promotion_blockers
    }
    expected_blockers = {
        (item.question_id, item.field) for item in target.promotion_blockers
    }
    return {
        "records": len(records),
        "matched": alignment["matched_count"],
        "parsed_only": alignment["parsed_only_count"],
        "target_only": alignment["target_only_count"],
        "field_differences": differences,
        "blockers": len(candidate.promotion_blockers),
        "benchmark_blockers": len(expected_blockers),
        "added_blocker_keys": len(current_blockers - expected_blockers),
        "missing_blocker_keys": len(expected_blockers - current_blockers),
    }


def main() -> None:
    args = build_parser().parse_args()
    raw = (args.run_directory / "artifacts" / "01_raw.txt").read_text(encoding="utf-8")
    id_pack = load_pack(args.id_pack)
    benchmark = load_pack(args.benchmark)
    before = evaluate(raw, id_pack, benchmark)
    preview = preview_remove_profiled_noise(raw)
    after = evaluate(preview.text, id_pack, benchmark)
    result = {
        "before": before,
        "after": after,
        "removed_whole_lines": preview.removed_whole_lines,
        "stripped_suffixes": preview.stripped_suffixes,
        "protected_candidates": preview.protected_candidates,
        "persisted": False,
        "promotion_ready": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
