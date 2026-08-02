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

## Private run lifecycle

Every intake operates inside one private `v2-run-*` directory. The lifecycle
manifest stores only source-neutral stage names, counts, and failure codes. It
never stores the user's original path, filename, source bytes, or extracted text.

The run accepts bytes only as a disposable copy. That copy remains available
through extraction and is deleted after cleaning succeeds. Raw and cleaned
whole-document text remain inside the owned artifacts directory while parsing,
review, candidate construction, and comparison proceed. Final completion removes
the disposable source, raw text, and cleaned text while retaining the
source-neutral run manifest.

A failed run records its exact stage and a constrained source-neutral failure
code. Controlled artifacts remain until explicit failed-run cleanup. Cleanup can
address only three known filenames under the exact verified run boundary; it
rejects symbolic links and non-file targets and never follows a link to an
external original.

The connected workbench now drives this lifecycle for its synthetic document.
Before the user starts a run, the server exposes no review cases and holds no
source-bearing run artifacts. Starting the run stages the disposable synthetic
copy, records extraction and the current pass-through synthetic cleaning stage,
parses it, and reaches `review_ready`; the staged copy is already deleted at that
point. Candidate construction and comparison advance the manifest. Any later
review change returns it to `review_ready` and invalidates those outputs. Explicit
completion is available only after comparison and removes raw and cleaned text.
It never enables promotion.

## Cleaning boundary

`GuardedPageAwareCleaner` wraps the cross-source repeated-noise behavior already
proven against Fundamentals and Medical-Surgical. It normalizes line endings,
removes only eligible repeated page-edge lines and suffix overlays, protects
repeated educational structures, and retains the guarded leading-index behavior.
Its result reports input/output size, removals, suffix stripping, and protected
candidate counts. It always reports zero meaning-level repairs and zero
source-specific rules. The connected synthetic run now parses this cleaned result
rather than the raw/pass-through value, and exposes only source-neutral cleaning
metrics in the workbench and run manifest.

## Extraction boundary

Extraction adapters receive only the verified `incoming/source.bin` disposable
copy inside a `v2-run-*` directory. They reject alternate directories, missing
copies, symbolic links, and unsupported source types. The synthetic UTF-8 adapter
and text-PDF adapter both return page-preserving text plus source-neutral counts.
PDF extraction reads the contained bytes without depending on or recording the
original filename, path, document metadata, or hash. A PDF with no extractable
text fails with a source-neutral diagnostic suitable for a future OCR decision.
The connected lifecycle now passes extraction output—with form-feed page
boundaries—into guarded cleaning and reports only adapter, page, and character
counts to the workbench.

## Private PDF intake control

The local workbench accepts a selected PDF as raw bytes with an
`application/pdf` request. It does not transmit or persist the user's filename
or filesystem path, and rejects empty inputs and files larger than 250 MiB. The
server creates its own disposable `incoming/source.bin`, extracts the PDF,
applies guarded source-neutral cleaning, and parses the cleaned text. A real,
minimal PDF fixture exercises this path in tests rather than substituting plain
text for the extraction step.

The front half deliberately stops at `identity_pending`. Parsed records have no
PrepFlow IDs until the user selects either a new-Pack identity strategy or an
existing-Pack re-import strategy. Consequently this control cannot build a
candidate, compare with canonical data, promote data, or overwrite a Pack.

On successful front-half processing, the incoming copy has already been
deleted while private raw and cleaned text remain available for the next stage.
The user may cancel and clean the run, which removes only the owned
source-bearing artifacts and permits a retry. Extraction or parsing failure is
reported with a source-neutral failure code and likewise requires explicit
controlled cleanup. A completed run's manifest remains as an audit record while
a later intake receives a new isolated run directory.

## Existing-Pack identity matching

At `identity_pending`, the local workbench may assess parsed records against one
of its explicitly allowlisted protected Packs. The v2 matcher reuses the proven
source-neutral typography normalization boundary, but is intentionally stricter
than the legacy ordered matcher: it automatically links only a unique normalized
exact stem in the same chapter. It never treats position, source question number,
or equal-length changed regions as sufficient identity evidence.

Changed or absent stems produce `changed_or_unmatched_identity`; duplicate exact
stems produce `ambiguous_exact_identity`. Reports contain temporary record IDs,
stable Pack IDs, classifications, and counts, but no source or question text.
Stable-ID authorization is available only when every parsed record and every
target Pack record is accounted for exactly once with no identity findings.
Otherwise the run stops at `identity_review`. A complete report stops at
`identity_matched`; candidate construction and canonical promotion remain
unavailable in this slice.

Identity review may rank up to three unclaimed targets from the same chapter by
normalized stem similarity. Rankings are proposals, never identity authority.
The private local interface displays the parsed stem, target stem, stable target
ID, and score so the user can approve a selected match, reject the suggestions,
or defer. Review content stays in the in-memory session payload and is never
written into the source-neutral run manifest.

An approval is accepted only for a suggestion actually displayed for that
temporary parsed record. The engine prevents duplicate use of a stable target
ID. Reject and defer retain the identity blocker. The lifecycle reaches
`identity_matched` only when exact automatic matches plus explicitly approved
matches create complete one-to-one accounting of both parsed and target records.
Even then, this stage only authorizes identity mapping; it does not authorize a
content repair, candidate write, Pack overwrite, or promotion.

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
