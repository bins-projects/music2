from compiler.candidate import build_candidate
from compiler.pack_qa import audit_merged_questions


def question_pack(*, choices, answers, rationale, question_type="mc") -> dict:
    return {
        "format": "prepflow_pack",
        "version": "1.0",
        "pack_id": "test-pack",
        "title": "Test Pack",
        "questions": [
            {
                "id": "PFQ-test-pack-000000001",
                "chapter": 1,
                "chapter_title": "Test Chapter",
                "type": question_type,
                "stem": "What is the priority action?",
                "choices": [
                    {"label": label, "text": text}
                    for label, text in choices
                ],
                "correct_answers": list(answers),
                "rationale": rationale,
            }
        ],
    }


def merged_pack() -> dict:
    return question_pack(
        choices=[
            ("A", "First action"),
            ("B", "Second action"),
            ("C", "Third action"),
            ("D", "Fourth action"),
            ("A", "Neighboring first action"),
            ("B", "Neighboring second action"),
            ("C", "Neighboring third action"),
            ("D", "Neighboring fourth action"),
            ("E", "Neighboring fifth action"),
        ],
        answers=("C", "E"),
        rationale=(
            "The first explanation belongs here. What actions should the nurse "
            "take? (Select all that apply.) The second explanation follows."
        ),
    )


def test_combined_evidence_blocks_a_possible_merged_question() -> None:
    findings = audit_merged_questions(merged_pack())

    assert len(findings) == 1
    assert findings[0].issue_codes[-1] == "possible_merged_questions"


def test_merged_question_finding_is_in_candidate_promotion_blockers() -> None:
    result = build_candidate(merged_pack(), [])

    blocker = next(
        item
        for item in result.promotion_blockers
        if item.question_id == "PFQ-test-pack-000000001"
    )
    assert "possible merged questions" in blocker.damage_type


def test_each_signal_alone_is_insufficient() -> None:
    valid_choices = [
        ("A", "First action"),
        ("B", "Second action"),
        ("C", "Third action"),
        ("D", "Fourth action"),
    ]
    cases = [
        question_pack(
            choices=valid_choices,
            answers=("A", "C"),
            rationale="What finding supports the answer?",
            question_type="multiple_response",
        ),
        question_pack(
            choices=valid_choices,
            answers=("A",),
            rationale="What finding supports the answer?",
        ),
        question_pack(
            choices=valid_choices + [("A", "Repeated label")],
            answers=("A",),
            rationale="One explanation only.",
        ),
    ]

    assert all(audit_merged_questions(pack) == [] for pack in cases)
