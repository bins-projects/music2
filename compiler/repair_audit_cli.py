import argparse
from collections import Counter
from pathlib import Path

from compiler.repair import (
    RepairError,
    find_question,
    get_text_field,
    load_findings,
    load_pack,
)
from compiler.repair_cli import DEFAULT_LEDGER, DEFAULT_PACK
from compiler.pack_qa import audit_interleaving, audit_typography
from compiler.text_repairs import analyze_text_repairs


def classify_analysis(analysis) -> str:
    if analysis.blocked:
        return "blocked_interleaving"
    if analysis.approved_rule_ids:
        return "approved_repair_candidate"
    if analysis.split_candidates:
        return "review_split_candidate"
    return "no_safe_candidate"


def audit_split_findings(pack: dict, findings: list) -> list[dict]:
    results = []
    for finding in findings:
        if finding.damage_type != "possible split suffix":
            continue

        question = find_question(pack, finding.question_id)
        text = get_text_field(question, finding.field)
        analysis = analyze_text_repairs(text)
        results.append(
            {
                "finding_id": finding.finding_id,
                "question_id": finding.question_id,
                "field": finding.field,
                "classification": classify_analysis(analysis),
                "approved_rule_ids": analysis.approved_rule_ids,
                "blocker_codes": analysis.blocker_codes,
                "split_candidates": tuple(
                    (item.separated, item.mechanical_join)
                    for item in analysis.split_candidates
                ),
            }
        )

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run approved repairs and review-only split candidates."
    )
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--show-all", action="store_true")
    parser.add_argument(
        "--show-typography-details",
        action="store_true",
    )
    parser.add_argument(
        "--show-interleaving-details",
        action="store_true",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        pack = load_pack(args.pack)
        findings = load_findings(args.ledger)
        results = audit_split_findings(pack, findings)
        typography = audit_typography(pack)
        interleaving = audit_interleaving(pack)
    except (OSError, RepairError) as error:
        raise SystemExit(f"Repair audit stopped: {error}") from error

    counts = Counter(item["classification"] for item in results)
    print("PrepFlow split-repair dry run")
    print(f"Findings analyzed: {len(results)}")
    for classification in (
        "approved_repair_candidate",
        "review_split_candidate",
        "blocked_interleaving",
        "no_safe_candidate",
    ):
        print(f"{classification}: {counts[classification]}")

    visible = results if args.show_all else [
        item
        for item in results
        if item["classification"] == "approved_repair_candidate"
    ]

    if visible:
        print()
    for item in visible:
        print(
            f"{item['finding_id']} | {item['question_id']} | "
            f"{item['field']} | {item['classification']}"
        )
        if item["approved_rule_ids"]:
            print("  approved: " + ", ".join(item["approved_rule_ids"]))
        if item["blocker_codes"]:
            print("  blocked: " + ", ".join(item["blocker_codes"]))
        if item["split_candidates"]:
            joined = [
                f"{before!r} [mechanical join: {after!r}; not applied]"
                for before, after in item["split_candidates"]
            ]
            print("  review only: " + "; ".join(joined))

    print()
    print("Dry run only. No Pack or repair record was written.")

    opening_count = sum(item.opening_marks for item in typography)
    closing_count = sum(item.closing_marks for item in typography)
    unbalanced = [item for item in typography if not item.balanced_after]

    print()
    print("PrepFlow typography-normalization dry run")
    print(f"Fields affected: {len(typography)}")
    print(f"Horizontal bars to opening quotes: {opening_count}")
    print(f"Double vertical lines to closing quotes: {closing_count}")
    print(f"Unbalanced fields after normalization: {len(unbalanced)}")

    visible_typography = typography if args.show_typography_details else unbalanced
    if visible_typography:
        print()
    for item in visible_typography:
        status = "balanced" if item.balanced_after else "review_required"
        print(
            f"{item.question_id} | {item.field} | {status} | "
            f"open={item.opening_marks} close={item.closing_marks}"
        )

    print()
    print("Dry run only. No typography changes were written.")

    interleaving_counts = Counter(
        code
        for item in interleaving
        for code in item.blocker_codes
    )
    print()
    print("PrepFlow Pack-wide interleaving scan")
    print(f"Fields requiring review: {len(interleaving)}")
    print(
        "Questions affected: "
        f"{len({item.question_id for item in interleaving})}"
    )
    severity_counts = Counter(item.severity for item in interleaving)
    print("Review tiers:")
    for severity in (
        "severe_interleaving",
        "probable_interleaving",
        "fragment_review",
    ):
        print(f"  {severity}: {severity_counts[severity]}")
    print("Affected fields:")
    field_counts = Counter(
        "choice" if item.field.startswith("choices[") else item.field
        for item in interleaving
    )
    for field in ("stem", "choice", "rationale"):
        print(f"  {field}: {field_counts[field]}")
    print("Detector signals:")
    for code in (
        "fragment_density",
        "mixed_case_interleaving",
        "combined_interleaving",
    ):
        print(f"  {code}: {interleaving_counts[code]}")

    if args.show_interleaving_details and interleaving:
        print()
        for item in interleaving:
            print(
                f"{item.question_id} | {item.field} | "
                f"{item.severity} | "
                + ", ".join(item.blocker_codes)
            )

    print()
    print("Detection only. No interleaved text was rewritten.")


if __name__ == "__main__":
    main()
