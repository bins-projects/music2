import argparse
import json
from pathlib import Path

from compiler.promotion_holds import PromotionHoldError, load_promotion_holds
from compiler.workbench_compare import WorkbenchComparisonError, compare_workbenches


DEFAULT_HOLDS = Path("config/promotion-holds.prepflow.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two PrepFlow workbench snapshots read-only.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--holds", type=Path, default=DEFAULT_HOLDS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def render_text(result: dict) -> str:
    pack = result["pack"]
    blockers = result["blockers"]
    holds = result["promotion_holds"]
    lines = [
        "PrepFlow workbench comparison (read-only)",
        f"Checksums verified: baseline={result['snapshots']['baseline']['checksums_verified']}, current={result['snapshots']['current']['checksums_verified']}",
        f"Questions: {pack['baseline_question_count']} -> {pack['current_question_count']}",
        f"Changed questions: {len(pack['changed_questions'])}",
    ]
    for item in pack["changed_questions"]:
        lines.append(f"  {item['question_id']} | {', '.join(item['fields'])}")
    lines.extend(
        [
            f"Blockers: {blockers['baseline_count']} -> {blockers['current_count']}",
            f"Removed: {len(blockers['removed'])}",
        ]
    )
    for item in blockers["removed"]:
        lines.append(f"  {item['question_id']} | {item['field']} | {item['damage_type']}")
    lines.append(f"Added: {len(blockers['added'])}")
    for item in blockers["added"]:
        lines.append(f"  {item['question_id']} | {item['field']} | {item['damage_type']}")
    lines.append(f"Reclassified: {len(blockers['reclassified'])}")
    for item in blockers["reclassified"]:
        before, after = item["before"], item["after"]
        lines.append(f"  {before['question_id']} | {before['field']}")
        lines.append(f"    before: {before['damage_type']}")
        lines.append(f"    after:  {after['damage_type']}")
    lines.append("Current blocker inventory by damage:")
    for category, count in blockers["current_inventory_by_damage"].items():
        lines.append(f"  {count}: {category}")
    lines.append(f"Unresolved promotion holds: {holds['unresolved_count']}")
    for hold in holds["unresolved_holds"]:
        lines.append(f"  {hold['question_id']} | {hold['category']} | {hold['reason']}")
    lines.append(f"Promotion ready: {holds['promotion_ready']}")
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    try:
        current_dir = args.current / "fundamentals" if (args.current / "fundamentals").is_dir() else args.current
        current_pack = json.loads((current_dir / "candidate.prepflow.json").read_text(encoding="utf-8"))
        holds = load_promotion_holds(args.holds, pack=current_pack)
        result = compare_workbenches(args.baseline, args.current, holds=holds)
    except (OSError, json.JSONDecodeError, PromotionHoldError, WorkbenchComparisonError) as error:
        raise SystemExit(f"Workbench comparison stopped: {error}") from error
    print(json.dumps(result, indent=2) if args.as_json else render_text(result))


if __name__ == "__main__":
    main()
