# Ingestion v2 Transition Evidence — August 2, 2026

## Decision

The current cross-source experiment has produced enough evidence to stop
expanding the transitional intake path after this guarded cleaning change. The
existing pipeline should remain a benchmark while the next work defines and
builds ingestion v2 and its review workbench.

## Guarded repeated-page-noise result

The source-neutral cleaner now profiles page-aware extraction and removes only
repeated edge lines and suffix overlays that do not match protected educational
structure. Repeated answer, question, chapter, section, and metadata shapes are
not automatically removed.

| Measure | Fundamentals | Medical-Surgical |
|---|---:|---:|
| source records parsed | 1,047 | 1,443 |
| stable IDs aligned | 1,040 | 1,443 |
| parsed-only boundary records | 7 | 0 |
| target-only records | 0 | 0 |
| remaining benchmark field differences | 127 | 175 |
| benchmark blocker keys added | 59 | 2 |

No repair, answer recovery, candidate promotion, or canonical write is part of
this cleaning operation.

## Remaining-difference classification

Fundamentals has 127 remaining field differences: 59 rationales, 33 answer
mappings, 23 choice collections, and 12 stems. Of these, 48 are list-length or
choice/answer-structure differences, 56 are cases where one text contains the
other, seven are choice-text containment differences, 13 are substantive text
differences, two are punctuation/spacing/case differences, and one is an answer
membership difference. These are parser, structural-recovery, or repair-review
work—not authorization for broader cleaning.

Medical-Surgical has 175 remaining field differences: 106 choice collections,
54 chapter titles, 12 stems, two answer mappings, and one rationale. One hundred
choice differences are list-versus-keyed-map representation differences. The 54
chapter-title differences and 13 stem/rationale differences contain extra text
on the isolated side. Six choice collections contain extra text, and two answer
mappings contain 17 parsed labels instead of one expected answer. The latter two
produce the only added blocker keys, on stable questions 1172 and 1393. These
results separate schema normalization and parser behavior from cleaning.

## Safety observations

- Fundamentals retains its seven malformed parsed-only records for review.
- Medical-Surgical retains the three known exact duplicate pairs as visible
  duplicate findings; cleaning does not delete them.
- Existing Pack blockers remain visible.
- The isolated candidates remain explicitly non-promotable.
- Legacy source-specific cleaning and broad missing-A recovery remain outside
  the default route.

## Requirements carried into ingestion v2

1. Page-aware noise handling must remain guarded, source-neutral, and tested
   against protected educational structures.
2. Collection representation normalization must be distinct from content
   cleaning.
3. Answer-label parsing must create findings and proposals, never silently infer
   missing choices or answers.
4. Boundary records and duplicates must remain visible until reviewed.
5. The review workbench must present source context, findings, proposed repairs,
   approval state, and promotion holds as separate concepts.
6. Every candidate must be compared with the relevant canonical Pack and known
   blocker baseline before explicit promotion is available.
