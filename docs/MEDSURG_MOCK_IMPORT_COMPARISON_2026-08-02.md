# Medical-Surgical Mock Import Comparison — August 2, 2026

## Baseline result

The untouched PDF was processed through the same unchanged isolated pipeline used
for Fundamentals. The disposable staging copy was deleted after extraction. No
repair, promotion, canonical write, or pipeline tuning occurred.

| Measure | Result |
|---|---:|
| existing Pack questions | 1,443 |
| isolated parsed records | 1,443 |
| aligned stable IDs | 1,443 |
| parsed-only records | 0 |
| target-only records | 0 |
| exact stem alignments | 1,357 |
| changed stem alignments | 86 |
| boundary findings | 0 |

The parser identified 1,187 multiple-choice, 134 multiple-response, 107
completion, and 15 ordered-response records. Generalized cleaning detected 63
chapters and 1,446 numbered shapes before parsing.

## Validation and field comparison

Validation reported 40 correct answers referencing missing choices, one missing
answer/no-choice record, and four advisories. The legacy label-grouping behavior
would mark 45 records as skipped, but the isolated candidate retains all 1,443
aligned records and remains non-promotable.

Across 10,101 top-level question fields, 9,421 match the existing Pack and 680
differ:

- 268 rationales;
- 222 choice collections;
- 86 stems;
- 54 chapter titles;
- 49 answer mappings; and
- 1 question type.

The existing Pack has seven QA blockers. The isolated candidate retains all seven
and adds 41: 40 correct-answer-without-choice findings and one missing-choice
collection.

## Diagnostic attribution

When the legacy cleaner is run in memory for diagnosis only, all 680 differing
fields become exact existing-Pack matches and all 41 added blocker keys disappear.
The legacy-cleaned diagnostic state has exactly the same seven blocker keys as the
existing Pack.

This is strong evidence that Medical-Surgical’s current drift is caused by
cleaning-stage extraction noise rather than lost source content or record
alignment. It does not authorize the source-title-specific legacy rules on the
new default path. Instead, it provides a second independent benchmark for guarded,
source-neutral header, footer, branding, and overlay-noise handling.

## Safety

The source PDF and `packs/medical_surgical.prepflow.json` hashes were unchanged.
The isolated candidate contains 1,443 stable IDs, zero repairs, no boundary
findings, and `promotion_ready: false`. The complete suite reports 223 passing
tests.
