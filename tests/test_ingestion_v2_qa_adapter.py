from copy import deepcopy

from ingestion_v2.domain import QuestionRecord
from ingestion_v2.qa_adapter import detect_candidate_damage


def question(**changes) -> QuestionRecord:
    values = {
        "question_id": "PFQ-test-000000001",
        "chapter": 1,
        "chapter_title": "Chapter",
        "question_type": "multiple_choice",
        "stem": "Which action is appropriate?",
        "choices": (("A", "First action"), ("B", "Second action"), ("C", "Third action"), ("D", "Fourth action")),
        "correct_answers": ("D",),
        "rationale": "The fourth action is appropriate.",
    }
    values.update(changes)
    return QuestionRecord(**values)


def test_clean_question_produces_no_qa_findings() -> None:
    result = detect_candidate_damage((question(),))

    assert result.findings == ()
    assert result.automatic_repairs == 0
    assert result.proposals_created == 0


def test_interleaving_in_choice_maps_to_source_neutral_choices_field() -> None:
    damaged = question(choices=(("A", "Damaged abCdEf xyZaBc g h j fragments"), ("B", "Clean")))

    result = detect_candidate_damage((damaged,))

    finding = next(item for item in result.findings if "interleaving" in item.damage_type)
    assert finding.field == "choices"
    assert finding.question_id == damaged.question_id


def test_embedded_choice_candidate_remains_finding_only() -> None:
    damaged = question(
        choices=(("A", "First action b. Second action"), ("C", "Third action"), ("D", "Fourth action"))
    )

    result = detect_candidate_damage((damaged,))

    embedded = next(item for item in result.findings if item.damage_type == "embedded_choice_recovery_candidate")
    assert "explicit approval" in embedded.explanation
    assert result.proposals_created == 0
    assert result.automatic_repairs == 0


def test_lowercase_vitamin_prose_stays_ambiguous_without_proposal() -> None:
    damaged = question(
        choices=(("A", "The patient takes vitamin b. Complex each morning"), ("C", "Third"), ("D", "Fourth"))
    )

    result = detect_candidate_damage((damaged,))

    assert any(item.damage_type == "ambiguous_embedded_choice" for item in result.findings)
    assert not any(item.damage_type == "embedded_choice_recovery_candidate" for item in result.findings)
    assert result.proposals_created == 0


def test_detector_adapter_does_not_mutate_question_records() -> None:
    questions = (question(),)
    before = deepcopy(questions)

    first = detect_candidate_damage(questions)
    second = detect_candidate_damage(questions)

    assert first == second
    assert questions == before
