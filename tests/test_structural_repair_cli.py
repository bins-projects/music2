from pathlib import Path

from compiler.structural_repair_cli import build_parser, structural_findings


def test_structural_cli_requires_explicit_finding_and_choice() -> None:
    args = build_parser().parse_args(
        [
            "--finding-id",
            "PFQA-INTERLEAVE-Q1-STEM",
            "--insert-label",
            "A",
        ]
    )

    assert args.pack == Path("packs/fundamentals.prepflow.json")
    assert args.insert_label == "A"
    assert args.insert_index == 0


def test_structural_cli_can_open_a_structure_only_finding() -> None:
    pack = {
        "questions": [
            {
                "id": "Q1",
                "type": "mc",
                "stem": "Which item? A. First choice",
                "choices": [
                    {"label": "B", "text": "Second choice"},
                    {"label": "C", "text": "Third choice"},
                ],
                "correct_answers": ["B"],
            }
        ]
    }

    findings = structural_findings(pack)

    assert any(
        item.finding_id == "PFQA-STRUCTURE-Q1-STEM"
        for item in findings
    )
