from ingestion_v2.domain import Proposal
from ingestion_v2.parser import ExistingParserAdapter
from ingestion_v2.parser_bridge import materialize_matched_batch


SYNTHETIC_DOCUMENT = """Chapter 1: Synthetic Safety
MULTIPLE CHOICE
1. Which synthetic option is expected? First option
b. Second option
c. Third option
ANS: A
The second option is expected in this deliberately conflicted example.
DIF: Synthetic

2. Which synthetic observation should remain unresolved?
a. First observation
b. Second observation
ANS:
The source contains no usable answer key for this synthetic record.
DIF: Synthetic
"""


def synthetic_review_records(text: str = SYNTHETIC_DOCUMENT) -> tuple[
    tuple, tuple, tuple[Proposal, ...]
]:
    """Run a synthetic document through parser, identity bridge, and proposal setup."""
    batch = ExistingParserAdapter().parse(text)
    questions, findings = materialize_matched_batch(
        batch,
        {
            "PFV2-REC-000001": "PFQ-synthetic-000000108",
            "PFV2-REC-000002": "PFQ-synthetic-000000369",
        },
    )
    finding_by_damage = {finding.damage_type: finding for finding in findings}
    answer_finding = finding_by_damage["correct_answer_without_choice"]
    proposals = (
        Proposal(
            proposal_id="PFV2-PROP-0001",
            finding_id=answer_finding.finding_id,
            question_id=answer_finding.question_id,
            field="correct_answers",
            expected_before=("A",),
            proposed_after=("B",),
            explanation="The rationale supports B, but only temporary source verification can authorize changing the parsed answer.",
            requires_source_verification=True,
        ),
    )
    return questions, findings, proposals
