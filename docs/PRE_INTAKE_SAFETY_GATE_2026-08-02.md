# PrepFlow Pre-Intake Safety Gate — August 2, 2026

## Result

The read-only comparison of the externally preserved 17-repair and 24-repair
Fundamentals snapshots passed. Both `SHA256SUMS` files verified all three expected
artifacts. Pack metadata, 1,040 question IDs, and question count are identical.
There are no added or removed questions.

Exactly these questions changed:

| Question | Changed fields |
|---|---|
| PFQ-fundamentals-000000113 | choices |
| PFQ-fundamentals-000000357 | choices, stem |
| PFQ-fundamentals-000000369 | choices, rationale |
| PFQ-fundamentals-000000611 | choices |
| PFQ-fundamentals-000000676 | choices, stem |
| PFQ-fundamentals-000000944 | choices, stem |
| PFQ-fundamentals-000001022 | choices |

The repair count changed from 17 to 24. Promotion blockers changed from 301 to
277: 24 removed, zero added, and one reclassified.

## Removed blockers

| Question | Field | Previous classification |
|---|---|---|
| 113 | stem | choice structure: noncanonical_choice_order |
| 357 | choices[1].text | probable interleaving (mixed_case_interleaving) |
| 357 | stem | choice structure: missing_sequence_label |
| 369 | stem | choice structure: missing_sequence_label |
| 611 | stem | choice structure: missing_sequence_label |
| 676 | stem | probable interleaving (mixed_case_interleaving); choice structure: missing_sequence_label, possible_choice_absorbed_in_stem |
| 937 | rationale | fragment review (fragment_density) |
| 944 | choices[0].text | fragment review (fragment_density) |
| 944 | choices[1].text | probable interleaving (combined_interleaving) |
| 944 | choices[2].text | probable interleaving (combined_interleaving) |
| 944 | rationale | probable interleaving (mixed_case_interleaving, combined_interleaving) |
| 944 | stem | fragment review (fragment_density); choice structure: missing_sequence_label, possible_choice_absorbed_in_stem |
| 948 | choices[0].text | probable interleaving (combined_interleaving) |
| 948 | choices[1].text | probable interleaving (combined_interleaving) |
| 948 | choices[2].text | probable interleaving (combined_interleaving) |
| 948 | choices[3].text | probable interleaving (combined_interleaving) |
| 950 | rationale | probable interleaving (combined_interleaving) |
| 950 | stem | probable interleaving (combined_interleaving) |
| 961 | rationale | probable interleaving (combined_interleaving) |
| 961 | stem | probable interleaving (combined_interleaving) |
| 963 | rationale | probable interleaving (combined_interleaving) |
| 963 | stem | probable interleaving (mixed_case_interleaving, combined_interleaving) |
| 1022 | choices[2].text | probable interleaving (mixed_case_interleaving) |
| 1022 | stem | choice structure: missing_sequence_label |

The eleven removals outside the seven repaired questions are question 937’s
rationale; all four choices on 948; and the stem and rationale on 950, 961, and
963. Candidate content for those questions is byte-identical between snapshots.
Those blockers disappeared because the guarded clinical-unit exemption prevents
valid unit forms from being tokenized as overlay fragments. They are detector
classification changes, not candidate drift or repairs.

## Reclassified blocker

Question 937’s stem retained the same finding identity and field. Its previous
classification was:

`choice structure: duplicate_choice_label, noncanonical_choice_order`

It is now:

`choice structure: duplicate_choice_label, noncanonical_choice_order; restarted choice sequence; mc multiple answer mismatch; question prompt in rationale; possible merged questions`

This is the expected enrichment from the guarded merged-question detector. No
blocker was added at a new question/field key.

## Current 277-blocker inventory

| Category | Count |
|---|---:|
| severe interleaving (fragment_density, mixed_case_interleaving, combined_interleaving) | 96 |
| probable interleaving (mixed_case_interleaving, combined_interleaving) | 60 |
| fragment review (fragment_density) | 56 |
| probable interleaving (mixed_case_interleaving) | 53 |
| probable interleaving (combined_interleaving) | 8 |
| probable interleaving (fragment_density, combined_interleaving) | 2 |
| severe interleaving plus unbalanced directional quotation marks | 1 |
| duplicate/noncanonical choice structure plus possible merged question | 1 |

Fields: 151 rationales, 53 stems, and 73 choice-text fields (277 total).

## Promotion readiness and boundaries

`config/promotion-holds.prepflow.json` records one unresolved source-verification
hold for PFQ-fundamentals-000000108. Its candidate-only answer change from A to C
must be checked against the separately retained source before canonical promotion.

The comparison tool is read-only and provides no apply or promotion operation.
Embedded-choice findings remain proposals requiring explicit approval. The
canonical Pack, repair records, and both external snapshots were not modified.
No intake implementation, source upload, promotion, public push, or repair action
was performed during this gate.
