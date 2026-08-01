from compiler.repair import Finding
from compiler.repair_cli import build_parser, render_question


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
