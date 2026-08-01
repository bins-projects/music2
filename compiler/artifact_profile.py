import math
from collections import Counter
from dataclasses import dataclass

from compiler.pack_qa import (
    audit_interleaving,
    finding_id_for_interleaving,
    iter_question_text,
)
from compiler.repair import (
    Finding,
    RepairError,
    RepairRecord,
    analyze_repair_delta,
    apply_repairs,
    deletion_subsequence,
)


ARTIFACT_EVIDENCE_LEVELS = (
    "full_signature_evidence",
    "near_complete_evidence",
    "partial_evidence",
    "insufficient_evidence",
)


@dataclass(frozen=True)
class ArtifactProfileResult:
    training_repairs: int
    signature_length: int
    unresolved_fields: int
    evidence_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ArtifactEvidenceFinding:
    finding: Finding
    classification: str
    score: int


def shortest_common_supersequence(left: str, right: str) -> str:
    rows = len(left) + 1
    columns = len(right) + 1
    lengths = [[0] * columns for _ in range(rows)]
    for row in range(rows):
        lengths[row][0] = row
    for column in range(columns):
        lengths[0][column] = column

    for row in range(1, rows):
        for column in range(1, columns):
            if left[row - 1] == right[column - 1]:
                lengths[row][column] = lengths[row - 1][column - 1] + 1
            else:
                lengths[row][column] = min(
                    lengths[row - 1][column],
                    lengths[row][column - 1],
                ) + 1

    output = []
    row = len(left)
    column = len(right)
    while row or column:
        if row == 0:
            output.append(right[column - 1])
            column -= 1
        elif column == 0:
            output.append(left[row - 1])
            row -= 1
        elif left[row - 1] == right[column - 1]:
            output.append(left[row - 1])
            row -= 1
            column -= 1
        elif lengths[row - 1][column] < lengths[row][column - 1]:
            output.append(left[row - 1])
            row -= 1
        else:
            output.append(right[column - 1])
            column -= 1

    return "".join(reversed(output))


def learn_overlay_signature(records: list[RepairRecord]) -> tuple[str, int]:
    fragments = []
    for record in records:
        analysis = analyze_repair_delta(record.before, record.after)
        if analysis.classification != "uppercase_overlay_fragment_removed":
            continue
        fragment = deletion_subsequence(record.before, record.after)
        if fragment:
            fragments.append(fragment)

    if not fragments:
        raise RepairError(
            "No approved overlay-removal repairs are available for profiling"
        )

    fragments.sort(key=len, reverse=True)
    signature = fragments[0]
    for fragment in fragments[1:]:
        signature = shortest_common_supersequence(signature, fragment)
    return signature, len(fragments)


def longest_common_subsequence_length(left: str, right: str) -> int:
    previous = [0] * (len(right) + 1)
    for left_character in left:
        current = [0]
        for column, right_character in enumerate(right, 1):
            if left_character == right_character:
                current.append(previous[column - 1] + 1)
            else:
                current.append(max(previous[column], current[-1]))
        previous = current
    return previous[-1]


def evidence_score(text: str, signature: str, *, window: int = 140) -> int:
    best = 0
    step = max(1, window // 7)
    for start in range(0, max(1, len(text)), step):
        sample = text[start:start + window]
        visible = "".join(
            character
            for character in sample
            if character.isupper() or character == "."
        )
        best = max(
            best,
            longest_common_subsequence_length(signature, visible),
        )
    return best


def classify_evidence(score: int, signature_length: int) -> str:
    if score == signature_length:
        return "full_signature_evidence"
    if score >= math.ceil(signature_length * 0.8):
        return "near_complete_evidence"
    if score >= math.ceil(signature_length * 0.6):
        return "partial_evidence"
    return "insufficient_evidence"


def profile_pack_artifacts(
    pack: dict,
    records: list[RepairRecord],
) -> ArtifactProfileResult:
    signature, training_repairs = learn_overlay_signature(records)
    scored = score_pack_artifacts(pack, records, signature=signature)
    counts = Counter(item.classification for item in scored)

    return ArtifactProfileResult(
        training_repairs=training_repairs,
        signature_length=len(signature),
        unresolved_fields=len(scored),
        evidence_counts=tuple(
            (name, counts[name]) for name in ARTIFACT_EVIDENCE_LEVELS
        ),
    )


def score_pack_artifacts(
    pack: dict,
    records: list[RepairRecord],
    *,
    signature: str | None = None,
) -> list[ArtifactEvidenceFinding]:
    if signature is None:
        signature, _ = learn_overlay_signature(records)
    candidate = apply_repairs(pack, records)
    text_by_field = {
        (question["id"], field): text
        for question in candidate["questions"]
        for field, text in iter_question_text(question)
    }
    results = []
    findings = audit_interleaving(candidate)
    for finding in findings:
        text = text_by_field[(finding.question_id, finding.field)]
        score = evidence_score(text, signature)
        classification = classify_evidence(score, len(signature))
        results.append(
            ArtifactEvidenceFinding(
                finding=Finding(
                    finding_id=finding_id_for_interleaving(finding),
                    question_id=finding.question_id,
                    field=finding.field,
                    damage_type=(
                        classification.replace("_", " ")
                        + "; "
                        + finding.severity.replace("_", " ")
                    ),
                ),
                classification=classification,
                score=score,
            )
        )
    return results


def artifact_evidence_findings(
    pack: dict,
    records: list[RepairRecord],
    classification: str,
) -> list[Finding]:
    if classification not in ARTIFACT_EVIDENCE_LEVELS:
        raise RepairError(
            f"Unsupported artifact evidence level: {classification}"
        )
    return [
        item.finding
        for item in score_pack_artifacts(pack, records)
        if item.classification == classification
    ]
