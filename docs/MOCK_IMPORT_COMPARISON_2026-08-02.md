# PrepFlow Mock Import Comparison — August 2, 2026

## Status

The first isolated mock import reached candidate comparison. It used the original
PDF through a disposable staging copy, generalized cleaning, parsing without
broad missing-A recovery, normalization, record matching, and deterministic
typography/text normalization. It applied zero manual repairs and cannot promote.

The isolated candidate contains 1,040 questions with the existing stable IDs.
Seven additional malformed parser records remain explicit boundary findings and
were not silently deleted or assigned canonical IDs.

## Field comparison

Across 7,280 top-level question fields:

| Outcome | Fields |
|---|---:|
| all three states equal | 5,990 |
| isolated equals 24-repair candidate but differs from canonical | 770 |
| isolated equals canonical but differs from 24-repair candidate | 19 |
| isolated differs from both protected targets | 501 |

The 770 candidate matches are dominated by deterministic typography normalization
and must not be interpreted as 770 reproduced manual repairs. The 501 third-result
fields comprise 119 choice collections, 33 answer mappings, 316 rationales, and
33 stems. They are unexplained drift until accounted for.

## Repair lessons

Exactly reproduced without applying a repair:

- `FUND-DAMAGE-004` — question 68 stem;
- `PFQA-DUPLICATE-CHOICES-PFQ-FUNDAMENTALS-000000091`; and
- `PFQA-APPROVED-STRUCTURE-PFQ-FUNDAMENTALS-000000108`.

Question 108 remains under its source-verification hold; parser reproduction does
not resolve or authorize its A-to-C answer change.

Not reproduced: questions 4, 17, 37, 191, 293, 369, 676, 832, and 969.

Different from both targets: questions 1, 6, 27, 60, 111, 113, 137, 357, 611,
944, 1005, and 1022.

Totals: 3 reproduced, 9 not reproduced, and 12 different results.

## Blocker comparison

| Outcome | Count |
|---|---:|
| known 24-repair blockers | 277 |
| isolated blockers | 331 |
| retained blocker keys | 272 |
| added blocker keys | 59 |
| missing known blocker keys | 5 |
| reclassified shared keys | 0 |

The 59 added blockers include 32 correct-answer-without-choice findings, 5 plain
missing-label findings, 10 combined missing-label variants, 3 fragment-density
reviews, 4 mixed-case interleaving findings, and 6 severe interleaving findings.

The five absent known keys comprise two fragment reviews, two mixed-case
interleaving findings, and the merged-question blocker. They are not improvements:
each must be explained as a parser-boundary, field-shift, or genuine detector
outcome before disposition.

## Safety result and next gate

The original PDF, canonical Pack, 24-repair snapshot, and repair records remained
unchanged. The complete suite reports 222 passing tests. Promotion remains false
because boundary findings, validation findings, new blockers, unexplained drift,
the question-108 hold, and explicit approval are unresolved.

Next, categorize the 59 added and five missing blocker keys and trace the 501
third-result fields to generalized cleaning, parser boundaries, normalization, or
known repair lessons. Improve only source-neutral stages with focused positive and
negative tests; do not automatically apply the 24 repairs.

## Drift attribution

An explicit in-memory diagnostic run of the legacy cleaner attributes the 501
third-result fields as follows:

- 426 become exact 24-repair-candidate matches: 112 choices, 19 answer mappings,
  267 rationales, and 28 stems;
- 45 are changed by legacy cleaning but remain different from both targets: one
  choice collection and 44 rationales; and
- 30 persist unchanged through both cleaning routes: 6 choices, 14 answer
  mappings, 5 rationales, and 5 stems.

Of the 59 added blocker keys, 19 arise from the generalized-versus-legacy cleaning
difference and 40 remain present after legacy cleaning. All five missing known
keys are absent in both new parses, indicating parser-boundary or field-placement
differences rather than generalized cleaning.

This does not authorize putting legacy source-specific rules on the default path.
It identifies cleaning as the first high-impact stage: source-neutral guarded
equivalents should be developed for the repeated extraction noise, with the 45
partially changed fields and 30 persistent fields remaining in review.
