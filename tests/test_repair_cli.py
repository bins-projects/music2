import pytest

from compiler.repair import Finding, RepairError, create_repair_record
from compiler.repair_cli import (
    add_or_amend_record,
    build_parser,
    render_question,
    unrecorded_findings,
)
from tests.test_repair import sample_finding, sample_pack


def test_question_display_wraps_long_content() -> None:
    question = {
        "id": "PFQ-test-pack-000000001",
        "chapter": 1,
        "chapter_title": "Communication",
        "type": "mc",
        "stem": "A long question stem " * 12,
        "choices": [
            {"label": "A", "text": "A long answer choice " * 8},
            {"label": "B", "text": "A short choice"},
        ],
        "correct_answers": ["A"],
        "rationale": "A long rationale " * 14,
    }
    finding = Finding(
        finding_id="TEST-DAMAGE-001",
        question_id=question["id"],
        field="stem",
        damage_type="possible split word",
    )

    rendered = render_question(question, finding, width=72)

    assert max(len(line) for line in rendered.splitlines()) <= 72
    assert "Correct: A" in rendered


def test_cli_accepts_pipeline_disposition() -> None:
    args = build_parser().parse_args(
        ["--disposition", "repair_rule_candidate"]
    )

    assert args.disposition == "repair_rule_candidate"


def test_cli_can_open_next_interleaving_tier() -> None:
    args = build_parser().parse_args(
        ["--next-interleaving", "severe_interleaving"]
    )

    assert args.next_interleaving == "severe_interleaving"


def test_cli_can_open_next_artifact_evidence_tier() -> None:
    args = build_parser().parse_args(
        ["--next-artifact", "full_signature_evidence"]
    )

    assert args.next_artifact == "full_signature_evidence"


def test_cli_accepts_explicit_repair_amendment() -> None:
    args = build_parser().parse_args(
        ["--finding-id", "TEST-DAMAGE-001", "--amend-existing"]
    )

    assert args.amend_existing is True


def test_amendment_replaces_record_and_queue_skips_it() -> None:
    original = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is appropriate?",
    )
    amended = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is most appropriate?",
    )

    records, action = add_or_amend_record(
        [original], amended, amend=True
    )

    assert action == "amended"
    assert records == [amended]
    assert unrecorded_findings([sample_finding()], records) == []


def test_amendment_requires_an_existing_record() -> None:
    record = create_repair_record(
        sample_pack(),
        sample_finding(),
        "Which action is appropriate?",
    )

    with pytest.raises(RepairError, match="cannot be amended"):
        add_or_amend_record([], record, amend=True)
