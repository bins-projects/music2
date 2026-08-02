from dataclasses import asdict
from collections import Counter


class IntakeAttributionError(ValueError):
    """Raised when drift attribution inputs do not align."""


FIELDS = (
    "chapter",
    "chapter_title",
    "type",
    "stem",
    "choices",
    "correct_answers",
    "rationale",
)


def _questions(pack: dict) -> dict[str, dict]:
    values = pack.get("questions")
    if not isinstance(values, list):
        raise IntakeAttributionError("Pack questions must be a list")
    result = {item.get("id"): item for item in values if isinstance(item, dict)}
    if len(result) != len(values) or None in result:
        raise IntakeAttributionError("Pack IDs must be present and unique")
    return result


def _blockers(values) -> dict[tuple[str, str], dict]:
    result = {}
    for item in values:
        value = item if isinstance(item, dict) else asdict(item)
        key = (value["question_id"], value["field"])
        result[key] = value
    return result


def attribute_drift(
    isolated_pack: dict,
    legacy_diagnostic_pack: dict,
    canonical_pack: dict,
    candidate_24_pack: dict,
    isolated_blockers,
    legacy_blockers,
    known_blockers,
) -> dict:
    isolated = _questions(isolated_pack)
    legacy = _questions(legacy_diagnostic_pack)
    canonical = _questions(canonical_pack)
    candidate = _questions(candidate_24_pack)
    if not (set(isolated) == set(legacy) == set(canonical) == set(candidate)):
        raise IntakeAttributionError("Attribution Pack ID sets do not match")

    categories = Counter()
    records = []
    for question_id in sorted(isolated):
        for field in FIELDS:
            current = isolated[question_id].get(field)
            old_cleaner = legacy[question_id].get(field)
            approved = candidate[question_id].get(field)
            original = canonical[question_id].get(field)
            if current in (approved, original):
                continue
            if old_cleaner == approved:
                category = "legacy_cleaning_reaches_candidate_24"
            elif old_cleaner == original:
                category = "legacy_cleaning_reaches_canonical"
            elif old_cleaner == current:
                category = "persists_after_legacy_cleaning"
            else:
                category = "legacy_cleaning_changes_but_unresolved"
            categories[(category, field)] += 1
            records.append(
                {"question_id": question_id, "field": field, "category": category}
            )

    current = _blockers(isolated_blockers)
    legacy_findings = _blockers(legacy_blockers)
    known = _blockers(known_blockers)
    added = set(current) - set(known)
    missing = set(known) - set(current)
    blocker_attribution = {
        "added_also_in_legacy": sum(key in legacy_findings for key in added),
        "added_from_generalized_cleaning_difference": sum(
            key not in legacy_findings for key in added
        ),
        "missing_present_in_legacy": sum(key in legacy_findings for key in missing),
        "missing_absent_in_both_new_parses": sum(
            key not in legacy_findings for key in missing
        ),
        "legacy_diagnostic_blocker_count": len(legacy_findings),
    }
    return {
        "format": "prepflow_intake_drift_attribution",
        "version": "1.0",
        "field_category_counts": {
            category: dict(
                sorted(
                    (field, count)
                    for (item_category, field), count in categories.items()
                    if item_category == category
                )
            )
            for category in sorted({category for category, _ in categories})
        },
        "field_records": records,
        "blocker_attribution": blocker_attribution,
        "legacy_cleaner_used_for_diagnostics_only": True,
        "promotion_ready": False,
    }
