window.PREPFLOW_REVIEW_DEMO = {
  format: "prepflow_v2_review_queue",
  version: "1.0",
  cases: [
    {
      finding_id: "PFV2-FIND-0001",
      question_id: "PFQ-synthetic-000000108",
      chapter: 4,
      question_type: "mc",
      field: "correct_answers",
      damage_type: "answer_rationale_conflict",
      severity: "blocking",
      explanation: "The recorded answer and rationale disagree. PrepFlow cannot safely choose between them.",
      preserved_value: ["A"],
      proposal: {
        proposal_id: "PFV2-PROP-0001",
        proposed_value: ["C"],
        explanation: "The rationale supports C, but the temporary source must confirm the printed answer.",
        requires_source_verification: true
      },
      status: "awaiting_decision",
      allowed_actions: ["approve", "reject", "defer", "edit_as_new_proposal"],
      source_verification_recorded: false
    },
    {
      finding_id: "PFV2-FIND-0002",
      question_id: "PFQ-synthetic-000000369",
      chapter: 14,
      question_type: "mc",
      field: "choices",
      damage_type: "possible_choice_absorbed_in_stem",
      severity: "blocking",
      explanation: "The choice sequence starts at B, and the stem contains a possible A marker.",
      preserved_value: [["B", "Second synthetic option"], ["C", "Third synthetic option"]],
      proposal: {
        proposal_id: "PFV2-PROP-0002",
        proposed_value: [["A", "Recovered synthetic option"], ["B", "Second synthetic option"], ["C", "Third synthetic option"]],
        explanation: "Restore the explicitly marked choice as one atomic stem-and-choice repair.",
        requires_source_verification: false
      },
      status: "awaiting_decision",
      allowed_actions: ["approve", "reject", "defer", "edit_as_new_proposal"],
      source_verification_recorded: false
    },
    {
      finding_id: "PFV2-FIND-0003",
      question_id: "PFQ-synthetic-000000937",
      chapter: 37,
      question_type: "multiple_response",
      field: "stem",
      damage_type: "possible_merged_question",
      severity: "blocking",
      explanation: "Two question-shaped fragments may have merged. No safe correction has been established.",
      preserved_value: "Synthetic damaged stem with a second question-shaped fragment.",
      proposal: null,
      status: "needs_proposal",
      allowed_actions: ["leave_blocked", "exclude_record", "create_proposal"],
      source_verification_recorded: false
    }
  ],
  capabilities: {
    read_review_queue: true,
    record_review_decision: true,
    record_source_verification: true,
    build_isolated_candidate: false,
    compare_isolated_candidate: false,
    promote_canonical: false
  },
  candidate: {
    state: "not_built",
    persistent: false,
    promotion_ready: false
  },
  comparison: { state: "not_run" }
};
