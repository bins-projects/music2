# PrepFlow Ingestion v2

## Purpose

Ingestion v2 is the private factory engine that turns temporary source material
into reviewable PrepFlow candidates. The public study interface and canonical
Pack format remain stable. The existing compiler remains available as a benchmark
until v2 proves equivalent or better behavior across independent sources.

## Non-negotiable rules

1. The user's original document remains outside PrepFlow. Intake receives only a
   disposable copy in an ignored workspace.
2. Extraction and cleaning cannot decide educational meaning.
3. Damaged content remains visible. Uncertainty creates a finding rather than a
   confident-looking reconstruction.
4. Detection, proposal, authorization, candidate application, and promotion are
   distinct operations.
5. A proposal cannot modify a candidate without an explicit approval decision.
6. A proposal requiring source verification cannot be applied until that
   verification is separately recorded.
7. Approved changes use an expected-before guard. Stale candidates fail safely.
8. Unresolved blocking findings, holds, or incomplete comparisons prevent
   promotion readiness.
9. Candidate construction never modifies a canonical Pack.
10. Promotion is an explicit future operation and is not exposed by intake,
    detection, proposal, review, or comparison components.
11. Stable PrepFlow question IDs survive reprocessing and are the only durable
    identity used by findings and repairs.
12. Source filenames, paths, titles, publishers, editions, page locations, raw
    documents, and whole-document text never enter durable records or Git.
13. Legacy source-specific cleaning and broad missing-choice recovery are not in
    the v2 default path.
14. AI may eventually suggest proposals and explanations. It receives no power
    to approve, apply, verify, or promote its own output.

## Engine boundaries

```text
disposable intake
  -> extraction
  -> guarded cleaning
  -> parsing and normalization
  -> validation and detection
  -> findings
  -> optional proposals
  -> review decisions and source verification
  -> guarded candidate construction
  -> QA and benchmark comparison
  -> promotion-readiness report
  -> separate explicit promotion
```

The initial executable core implements the center of this flow: source-neutral
question records, findings, proposals, review decisions, verification, guarded
candidate construction, and read-only promotion-readiness reporting. It uses no
private source data and imports no legacy compiler behavior.

The review-case layer projects those immutable records into a deterministic queue
for an interface. It computes statuses and allowed actions but does not edit a
candidate itself. Queue ordering is stable by question ID, field, and finding ID.
The interface therefore displays engine state rather than inventing its own
authorization rules.

## Review interface contract

The future workbench will show one review case at a time with:

- stable question ID and source-neutral question fields;
- the preserved candidate value;
- finding type, severity, and explanation;
- a proposed value and explanation when justified;
- source context held only in the temporary private run;
- source-verification status;
- approve, reject, edit-as-new-proposal, defer, and leave-blocked actions; and
- the effect of the decision on candidate QA and promotion readiness.

The interface is a client of the engine. It cannot bypass domain validation or
write directly to canonical Packs.

The first connected workbench runs on `127.0.0.1` only and uses synthetic,
in-memory records. Browser actions are submitted to the Python review engine,
validated against the current queue state, and returned as a new read-only view.
Its event history disappears when the local process stops. It has no Pack-write,
filesystem-persistence, candidate-build, or promotion endpoint.

The connected synthetic workbench is now fed through the parser boundary rather
than hand-assembled review cases. Synthetic document text produces run-local
records, structured parser findings, exact stable-ID mappings, and then the
review queue. Whole-document input text is not returned in the interface payload.
The demonstration currently produces three visible blockers from two parsed
records and performs zero automatic repairs.

The workbench can explicitly build an isolated candidate in memory. Candidate
construction re-runs the Python authorization guards: approval without required
source verification applies nothing, stale proposals fail, and only approved and
verified proposals may change the candidate. The preserved parser records remain
immutable. The workbench returns applied proposal IDs, unresolved finding IDs,
and promotion-readiness reasons; comparison remains incomplete and promotion is
still unavailable.

Candidate comparison requires exact stable-ID equality with the selected
benchmark. It reports every changed field in stable question/field order. A
review decision, verification, or candidate rebuild invalidates the prior report.
Only a comparison for the current candidate can satisfy the comparison gate;
unresolved blocking findings continue to prevent readiness independently.

## Findings without a safe correction

A reviewer may explicitly retain a blocker or exclude an unusable record. A
retained blocker records the human disposition but remains unresolved and blocks
readiness. Exclusion is a question-level atomic operation: the candidate omits
the whole record, records its stable ID and audit event, and never presents the
result as an exact ID match. Comparison succeeds only when every missing ID is
accounted for by a documented exclusion; unrelated findings remain unresolved.
Neither disposition invents replacement content.

## First vertical slice

The first slice is complete when synthetic tests prove that:

- findings alone never change a question;
- proposals alone never change a question;
- rejected and deferred proposals never change a question;
- approved proposals apply only when their expected value is current;
- source-verification holds prevent otherwise approved changes;
- unresolved blockers and incomplete comparison prevent readiness; and
- advisory-only, fully compared candidates can be reported ready without being
  promoted.
