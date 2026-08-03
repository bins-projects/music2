from ingestion_v2.domain import QuestionRecord, ReviewAction, ReviewDecision
from ingestion_v2.engine import build_candidate
from ingestion_v2.proposal_adapter import draft_benchmark_answer_proposals, draft_deterministic_proposals
from ingestion_v2.qa_adapter import detect_candidate_damage


def embedded_question(text: str = "First action b. Second action") -> QuestionRecord:
    return QuestionRecord(
        question_id="PFQ-test-000000001",
        chapter=1,
        chapter_title="Chapter",
        question_type="multiple_choice",
        stem="Which action is appropriate?",
        choices=(("A", text), ("C", "Third action"), ("D", "Fourth action")),
        correct_answers=("D",),
        rationale="The fourth action is appropriate.",
    )


def test_exact_embedded_choice_drafts_review_only_v2_proposal() -> None:
    questions = (embedded_question(),)
    qa = detect_candidate_damage(questions)

    proposals = draft_deterministic_proposals(questions, qa.findings)

    assert len(proposals) == 1
    assert proposals[0].field == "choices"
    assert proposals[0].expected_before == questions[0].choices
    assert proposals[0].proposed_after == (
        ("A", "First action"),
        ("B", "Second action"),
        ("C", "Third action"),
        ("D", "Fourth action"),
    )
    assert proposals[0].requires_source_verification is False
    assert questions[0].choices[0][1] == "First action b. Second action"


def test_proposal_does_not_change_candidate_until_explicit_approval() -> None:
    questions = (embedded_question(),)
    qa = detect_candidate_damage(questions)
    proposals = draft_deterministic_proposals(questions, qa.findings)

    untouched = build_candidate(questions, qa.findings, proposals)
    approved = build_candidate(
        questions,
        qa.findings,
        proposals,
        (
            ReviewDecision(
                decision_id="PFV2-DEC-EMBEDDED-000001",
                proposal_id=proposals[0].proposal_id,
                action=ReviewAction.APPROVE,
            ),
        ),
    )

    assert untouched.questions[0].choices == questions[0].choices
    assert proposals[0].finding_id in untouched.unresolved_finding_ids
    assert approved.questions[0].choices == proposals[0].proposed_after
    assert proposals[0].finding_id not in approved.unresolved_finding_ids
    assert questions[0].choices[0][1] == "First action b. Second action"


def test_ambiguous_vitamin_prose_drafts_no_proposal() -> None:
    questions = (embedded_question("The patient takes vitamin b. Complex each morning"),)
    qa = detect_candidate_damage(questions)

    assert draft_deterministic_proposals(questions, qa.findings) == ()


def test_benchmark_answer_draft_always_requires_source_verification() -> None:
    damaged = embedded_question()
    damaged = QuestionRecord(**{**damaged.__dict__, "choices": (("A", "First"), ("B", "Second")), "correct_answers": ("C", "A", "E")})
    benchmark = QuestionRecord(**{**damaged.__dict__, "correct_answers": ("A",)})
    from ingestion_v2.domain import Finding, FindingSeverity
    finding = Finding("PFV2-FIND-ANSWER-1", damaged.question_id, "correct_answers", "correct_answer_without_choice", FindingSeverity.BLOCKING, "Parsed answers reference missing choices.")

    proposals = draft_benchmark_answer_proposals((damaged,), (benchmark,), (finding,))

    assert proposals[0].proposed_after == ("A",)
    assert proposals[0].requires_source_verification is True
