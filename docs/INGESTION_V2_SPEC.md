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

## Parsed candidate materialization

After identity reaches `identity_matched`, the user may explicitly prepare the
parsed review. The parser bridge attaches the authorized stable-ID mapping to
the preserved parsed records and converts parser findings into ordinary v2
blocking findings. It creates no proposals and performs no automatic repairs.
The selected protected Pack is independently converted into immutable v2
benchmark records; its `mc` type representation is normalized to the parser's
source-neutral `multiple_choice` representation without altering either input.

Materialization requires exact equality between the authorized parsed ID set and
the benchmark Pack ID set. Only then does the lifecycle enter `review_ready`.
Candidate construction remains in memory and uses the existing authorization
engine. Comparison is deliberately run against the separately held protected
benchmark—not against the parsed baseline—so every changed field is visible.
Neither preparation, candidate construction, nor comparison exposes a Pack
writer or promotion operation.

## Generalized QA detector bridge

Materialization runs the proven source-neutral typography, interleaving,
choice-structure, merged-question, and embedded-choice detection logic over the
isolated parsed records. A temporary in-memory detection Pack adapts immutable
v2 records to the existing detector boundary. It is never exported. Choice-item
paths such as `choices[0].text` are translated back to the source-neutral v2
`choices` field.

Every detector result becomes a blocking v2 finding with a new v2 audit ID. The
bridge applies zero repairs and emits zero v2 proposals. In particular, a
high-confidence embedded-choice shape becomes
`embedded_choice_recovery_candidate`, whose explanation requires a later
reviewable proposal and explicit approval. Ambiguous shapes—including lowercase
prose such as “vitamin b. Complex”—remain findings without proposals. Parser and
QA findings are combined in the same review queue before candidate construction;
the preserved parsed question remains unchanged.

## Deterministic proposal boundary

The first v2 proposal adapter handles only the guarded exact embedded-middle-
choice shape. It reuses the existing structural planner as evidence, then emits
a new v2 `Proposal` tied to the corresponding v2 QA finding. The proposal moves
one existing text segment into its detected missing label, preserves wording,
and requires the answer key to remain byte-for-byte equivalent. The legacy plan
itself is not applied or persisted.

Drafting does not resolve the finding and reports zero automatic applications.
Rejected, deferred, and undecided proposals leave the parsed record unchanged.
An explicit approval allows the existing v2 candidate engine to apply the
proposal in memory only after confirming `expected_before` still matches the
preserved choices. A stale value stops application. Ambiguous embedded-choice
evidence, including protected vitamin prose, produces no proposal. No source
verification requirement is asserted for this exact text-only move, but the
ordinary explicit review decision remains mandatory.

Complete-record duplicate detection groups records only when they share a
chapter and their normalized type, stem, choices, correct answers, and rationale
are all identical. The first stable ID is preserved as the retained reference;
each later identical record receives a `complete_duplicate_record` blocker. An
identical record in another chapter is not automatically classified as a
duplicate because placement may carry distinct instructional meaning. Detection
never deletes either record. Whole-record exclusion uses the existing explicit,
audited disposition and remains visible in comparison as a documented excluded
stable ID.

## User-authored proposal boundary

Findings without a deterministic correction can be opened in a private proposal
editor. The editor begins with the preserved value, represents scalar and
collection fields as JSON, requires a non-empty justification, and lets the user
mark the draft as requiring later source verification. Domain validation checks
the proposed value against an immutable copy of the question before the proposal
is accepted.

Saving records a new v2 proposal and audit event only. It neither approves the
proposal nor rebuilds the candidate. Approval is a separate review decision;
when source verification was requested, approval still leaves the proposal
blocked until a separate verification event is recorded. Editing creates a new
proposal, replaces the prior draft for that finding, and clears decisions or
verifications tied to the superseded proposal. Empty explanations, unchanged
values, invalid field shapes, and actions unavailable in the current review
state are rejected.

## Temporary source-page verification

PDF extraction preserves physical page positions, including pages without an
extractable text layer, so displayed page numbers are not shifted. Extracted
pages remain only in the active in-memory session and the already controlled raw
artifact. A source page is returned to the local interface only on an explicit
request for a finding currently awaiting source verification.

PrepFlow locates the reviewed question by its preserved normalized stem and
opens a page only when exactly one physical page matches. Zero or multiple
matches stop with an ambiguity error instead of displaying a guessed page. The
temporary response contains the page text and page number but is never written
to the source-neutral run manifest. For PDF runs, source verification is refused
until that finding's page has been opened. Viewing and verification are separate
audit events. Completion or controlled cleanup clears the in-memory pages and
removes the owned whole-document artifacts; the user's original remains outside
the run and untouched.

## Source-neutral private checkpoints

Active existing-Pack runs maintain `audit/checkpoint.json` inside their verified
private run directory. The checkpoint records only temporary-to-stable identity
decisions, proposal decision references, verification booleans, whole-record
dispositions, and comparison counts. It contains no question values, proposal
values, source-page text, raw or cleaned text, filenames, or original paths.

Checkpoint writes are atomic and constrained to the exact run boundary. The
schema validates stable PrepFlow IDs, temporary record IDs, v2 references,
allowed actions, non-negative counts, and exact run identity. It rejects known
content-bearing keys recursively and refuses symbolic-link audit paths. Source
cleanup retains this source-neutral checkpoint while removing disposable source
and whole-document artifacts.

The active-run resume layer reconstructs deterministic parser, identity, QA,
proposal, candidate, and comparison state from the controlled cleaned artifact,
then replays only the recorded authorizations. It refuses a completed or failed
run whose source-bearing artifacts have already been cleaned, a different target
Pack, an identity action that no longer matches, a decision whose proposal cannot
be reproduced, or comparison totals that differ from the checkpoint. Resume does
not write canonical data and does not turn a proposal into authorization.

The local workbench discovers only validated, source-bearing active runs under
its owned private run root. It exposes a source-neutral summary and a
`Continue previous review` action; the browser never supplies a filesystem path.
The server resolves the run ID inside that fixed root and reloads the selected
protected Pack before recovery. The interface explicitly distinguishes the
private checkpoint write from the unavailable canonical write.

The private workbench home offers new PDF intake, validated active-run resume,
and content-free completed-run summaries. Starting a new book records the chosen
protected comparison Pack before the interface advances to identity review.
Completed summaries are shown only after owned source-bearing artifacts are
confirmed removed. The public `web/` study runtime has an automated dependency
boundary test and must not reference this engine or its local APIs.

Every review case exposes its source chapter title and temporary source-record
ID alongside the stable PrepFlow ID. Complete-duplicate review shows both
preserved records with their chapter context and requires the reviewer to choose
the exact stable ID to exclude; either record may be selected, and no exclusion
is inferred from numeric ID order. Edited proposal content remains absent from
checkpoints. A SHA-256 fingerprint over the deterministic proposal identity and
values permits exact regenerated proposals to recover prior decisions while
still refusing any proposal whose content cannot be reproduced.

Answer-field review never presents a bare label without context. The preserved
side shows the complete broken parsed label sequence and the available choice
text for each distinct label, explicitly marking labels for which no choice was
parsed. The proposal side shows the corrected label together with its choice
text. Text-field repairs continue to display the complete damaged and proposed
versions side by side.

Candidate comparison differences are not evidence of readiness by themselves.
Every changed field is displayed with the broken candidate value, the protected
Pack reference value, source chapter context, and the full correct-answer choice
text from both records. Any remaining field difference adds an explicit
`unreviewed_comparison_field_changes` readiness blocker until a later review
decision layer accounts for it; comparison completion alone cannot clear it.

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
