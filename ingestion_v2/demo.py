from ingestion_v2.domain import Finding, FindingSeverity, Proposal, QuestionRecord


def synthetic_review_records() -> tuple[
    tuple[QuestionRecord, ...], tuple[Finding, ...], tuple[Proposal, ...]
]:
    """Return source-neutral synthetic records for local workbench development."""
    questions = (
        QuestionRecord(
            question_id="PFQ-synthetic-000000108",
            chapter=4,
            question_type="mc",
            stem="Which synthetic answer is supported?",
            choices=(("A", "First option"), ("B", "Second option"), ("C", "Third option")),
            correct_answers=("A",),
            rationale="The synthetic rationale supports the third option.",
        ),
        QuestionRecord(
            question_id="PFQ-synthetic-000000369",
            chapter=14,
            question_type="mc",
            stem="Synthetic question with a possible absorbed first option.",
            choices=(("B", "Second synthetic option"), ("C", "Third synthetic option")),
            correct_answers=("B",),
        ),
        QuestionRecord(
            question_id="PFQ-synthetic-000000937",
            chapter=37,
            question_type="multiple_response",
            stem="Synthetic damaged stem with a second question-shaped fragment.",
            choices=(("A", "First"), ("B", "Second")),
            correct_answers=("A",),
        ),
    )
    findings = (
        Finding(
            finding_id="PFV2-FIND-0001",
            question_id=questions[0].question_id,
            field="correct_answers",
            damage_type="answer_rationale_conflict",
            severity=FindingSeverity.BLOCKING,
            explanation="The recorded answer and rationale disagree. PrepFlow cannot safely choose between them.",
        ),
        Finding(
            finding_id="PFV2-FIND-0002",
            question_id=questions[1].question_id,
            field="choices",
            damage_type="possible_choice_absorbed_in_stem",
            severity=FindingSeverity.BLOCKING,
            explanation="The choice sequence starts at B, and the stem contains a possible A marker.",
        ),
        Finding(
            finding_id="PFV2-FIND-0003",
            question_id=questions[2].question_id,
            field="stem",
            damage_type="possible_merged_question",
            severity=FindingSeverity.BLOCKING,
            explanation="Two question-shaped fragments may have merged. No safe correction has been established.",
        ),
    )
    proposals = (
        Proposal(
            proposal_id="PFV2-PROP-0001",
            finding_id=findings[0].finding_id,
            question_id=questions[0].question_id,
            field="correct_answers",
            expected_before=("A",),
            proposed_after=("C",),
            explanation="The rationale supports C, but the temporary source must confirm the printed answer.",
            requires_source_verification=True,
        ),
        Proposal(
            proposal_id="PFV2-PROP-0002",
            finding_id=findings[1].finding_id,
            question_id=questions[1].question_id,
            field="choices",
            expected_before=questions[1].choices,
            proposed_after=(
                ("A", "Recovered synthetic option"),
                ("B", "Second synthetic option"),
                ("C", "Third synthetic option"),
            ),
            explanation="Restore the explicitly marked choice as one atomic structural proposal.",
        ),
    )
    return questions, findings, proposals
