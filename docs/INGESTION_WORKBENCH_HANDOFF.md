# PrepFlow Ingestion Workbench Handoff

**Updated:** August 2, 2026  
**Status:** Pre-intake gate complete; isolated extraction slice verified

## New-session instruction

Read this entire file and `docs/INGESTION_ARCHITECTURE.md` before proposing a
command or changing a file. Then discuss the current state and intended next step
with the project owner before resuming work.

## 1. Objective

The current milestone has two connected goals:

1. clean the existing Fundamentals Pack without modifying the approved canonical
   Pack; and
2. turn verified repairs into a safe, source-agnostic ingestion workflow that the
   project owner can eventually use to add a new source independently.

This is not merely a one-time content-editing pass. Each reviewed defect should
teach the importer one of the following:

- a narrowly guarded mechanical repair;
- a reusable detector;
- a parser improvement;
- a validation rule;
- a one-question exception; or
- a promotion blocker that requires source review.

Do not infer a generalized rule from one correction. A rule needs a precise
trigger, positive tests, negative tests, stale-shape protection, and evidence that
it does not alter valid content.

## 2. Repository and branch topology

Use these names consistently:

```text
dev/private factory: bins-projects/prepflow-dev
public product:       bins-projects/PrepFlow
local repository:     ~/projects/prepflow
active branch:        feat/ingestion-workbench
code checkpoint:      f91b054f8aef9bcb66b4a7e4340935c8690cf4c3
private master:       e522a586003a6534e7b7dd502bbd3447fde42d96
public master:        e522a586003a6534e7b7dd502bbd3447fde42d96
```

The documentation commit containing this handoff is expected to be the branch
tip and to descend directly from the code checkpoint above.

After the August 1 branch cleanup, the expected remote-tracking branches are:

```text
origin/feat/ingestion-workbench
origin/master
public/master
```

The obsolete public development, preview, hotfix, build, review, and release
branches were removed after their unique tips were preserved. Public is intended
to have one long-lived branch: `master`.

Do not push `feat/ingestion-workbench` to the public repository. New ingestion,
repair, compiler, QA, and internal documentation work belongs only in the private
factory.

## 3. Public product state

The public site remains deployed from `bins-projects/PrepFlow:master`:

```text
https://bins-projects.github.io/PrepFlow/web/
```

The August 1–2 ingestion-workbench work did not change public `master`, so the
existing online application and links remain intact.

Important remaining cleanup: older compiler/parser code that already existed in
public `master` has not yet been removed. Branch cleanup is complete; curated
public-content cleanup is not. A future allowlisted release process must publish
only the approved Packs, browser runtime, runtime data, approved assets,
public-facing documentation, and the minimum code needed for the product.

## 4. Safety and recovery state

The work is protected at several levels.

### Git history

The active private branch contains all ingestion-workbench implementation through
commit `f91b054` (`Add approved atomic choice-structure repairs`).

### Complete Git bundle

A verified full-history bundle exists outside the repository in the sibling backup
area:

```text
../prepflow-backups/prepflow-all-refs-2026-08-01.bundle
```

The bundle was verified and recorded complete history. It includes the former
branch tips and local emergency refs created before branch deletion.

### Candidate-workbench snapshots

The ignored Fundamentals workbench has these external snapshots:

```text
../prepflow-backups/workbench-2026-08-01-1117
../prepflow-backups/workbench-2026-08-01-14-repairs
../prepflow-backups/workbench-2026-08-01-15-repairs
../prepflow-backups/workbench-2026-08-02-16-repairs
../prepflow-backups/workbench-2026-08-02-17-repairs
../prepflow-backups/workbench-2026-08-02-24-repairs
```

Each snapshot contains:

```text
fundamentals/candidate.prepflow.json
fundamentals/candidate-manifest.json
fundamentals/repair-records.json
SHA256SUMS
```

The 24-repair snapshot is the current recovery point. Its three recorded files
passed SHA-256 verification when the snapshot was created.

### Preserved former branch tips

Before deletion, two questionable historical tips were preserved as local
emergency refs:

```text
emergency/public-content-qa-fundamentals-cleanup
emergency/dev-home-quiz-panel-clean
```

They are also included in the verified Git bundle. They are preservation refs, not
active development branches.

## 5. Canonical and candidate boundary

The canonical Pack is:

```text
packs/fundamentals.prepflow.json
```

The active ignored workbench is:

```text
output/repair-workbench/fundamentals/
```

The canonical Pack was explicitly reported unchanged after every batch and
candidate build. Do not edit or overwrite it while repairing Fundamentals.

Repair records and candidate outputs are intentionally ignored by Git. Their
durable recovery mechanism is the external snapshot, while generalized pipeline
code and source-neutral tests are committed to the private branch.

Promotion to canonical status is a separate future decision requiring explicit
approval, complete validation, comparison, and no unexplained drift.

## 6. Current verified workbench state

The latest verified state is:

```text
approved candidate-only repairs: 24
promotion blockers:               277
automated tests before gate:      190 passed
canonical Pack:                   unchanged
```

The 24 repair lessons are:

```text
approved_choice_structure_correction: 3
approved_question_correction:          6
exact_duplicate_choice_block_removed: 1
manual_text_rewrite:                   1
stem_choice_split:                     6
trailing_metadata_removed:             1
uppercase_overlay_fragment_removed:    4
whitespace_only:                       2
```

The candidate build also applies one approved source-neutral text rule:

```text
join_which_fragment: 1 field
```

Typography normalization at the checkpoint reported:

```text
fields normalized:          1379
opening marks replaced:      588
closing marks replaced:      587
apostrophes replaced:       1192
```

## 7. Implemented workbench capabilities

The private branch now includes:

- source-agnostic ingestion architecture documentation;
- compiler models with source provenance removed;
- candidate-only repair records and application;
- amendable repair records with wrap-safe terminal display;
- live typography QA;
- Pack-wide interleaving and extraction-artifact detection;
- artifact profiling learned from approved temporary repairs;
- promotion-blocker generation;
- candidate manifests and repair-lesson classification;
- atomic stem/choice structural repair records;
- Pack-wide choice-structure QA;
- guarded batching of high-confidence leading choices absorbed into stems;
- guarded removal of an exact duplicated choice block;
- explicitly approved atomic choice removal and answer-map correction;
- stale-shape rejection and full-question validation; and
- source-neutral positive and negative test fixtures.

Useful commands include:

```bash
python -m compiler.repair_cli --help
python -m compiler.structural_repair_cli --help
python -m compiler.repair_audit_cli
python -m compiler.artifact_profile_cli
python -m compiler.structural_batch_cli
python -m compiler.duplicate_choice_batch_cli
python -m compiler.choice_structure_repair_cli --help
python -m compiler.candidate_cli
python -m pytest -q
```

Batch commands are dry-run by default. `--apply` writes only the candidate and
repair set unless a separate, explicitly approved promotion process is invoked.

## 8. Completed structural exceptions

The structural-exception review has safely resolved:

```text
PFQ-fundamentals-000000091
PFQ-fundamentals-000000108
PFQ-fundamentals-000000111
PFQ-fundamentals-000000293
PFQ-fundamentals-000000832
PFQ-fundamentals-000000969
PFQ-fundamentals-000001005
```

Question 91 contained two consecutive, byte-for-byte identical A–D choice blocks.
The generalized repair retains the first block only when:

- the two blocks are exactly equal;
- retained labels are canonical and ordered;
- every correct answer maps to a retained label;
- the complete pre-change shape still matches; and
- the repaired question passes validation.

This reduced promotion blockers from 304 to 303 and created repair 15.

Question 108 contained a leaked fifth choice, `D Evaluation`, following a
complete A-D choice set. Its recorded answer was A even though the unchanged stem,
choices, and rationale identify C, `Subjective data from a primary source`. The
project owner explicitly approved one atomic correction that removed only the
leaked fifth choice and changed the answer mapping from A to C. The operation
records the complete previous choice and answer shape, rejects stale application,
and created repair 16. The candidate rebuild passed with 302 promotion blockers;
the canonical Pack remained unchanged.

Question 111 contained one leading `D Evaluation` choice before an otherwise
complete A-D choice block whose retained D choice was byte-for-byte identical.
The project owner approved removing only the leading duplicate while preserving
answer A. The existing atomic choice-structure operation was sufficient, so no
new detector, code commit, or phrase-based rule was created. This created repair
17, reduced promotion blockers from 302 to 301, and left the canonical Pack
unchanged.

## 9. Structural comparison disposition

The 17-to-24 repair interval changed these seven questions only:

```text
PFQ-fundamentals-000000113
PFQ-fundamentals-000000357
PFQ-fundamentals-000000369
PFQ-fundamentals-000000611
PFQ-fundamentals-000000676
PFQ-fundamentals-000000944
PFQ-fundamentals-000001022
```

Question 937 did not change. Its existing blocker was enriched by the guarded
merged-question detector and remains unresolved. See the pre-intake gate report
for the complete blocker delta and inventory.

## 10. Exact next task

The source-neutral intake slice now creates an isolated run, copies a PDF to
a generic `incoming/source.pdf`, extracts through the existing PDF adapter, writes
raw text only inside the ignored run workspace, deletes the disposable PDF after
successful extraction, and records source-neutral run status. Generalized cleaning
normalizes whitespace and removes only a guarded leading chapter index; it does
not invoke legacy source-specific cleaning. Its synthetic containment and
cleaning, parsing, validation, and matching tests pass.

The first real run extracted 1,162,282 characters and generalized cleaning
produced 1,137,914 characters, 42 chapter headings, and 1,046 numbered-question
shapes. Isolated parsing produced 1,047 intermediate records: 828 multiple-choice
and 219 multiple-response, with two missing answers and 16 choice-sequence
findings. Broad missing-A recovery was disabled. Its incoming directory is empty.
Temporary raw, cleaned, and parsed artifacts remain in the ignored run workspace
for the next stage. The external original and canonical Pack hashes were
unchanged. No stable IDs, repairs, candidate build, comparison, or promotion
occurred.

Normalization retained all 1,047 records. Validation reported two fatal
no-choice records, 43 recoverable diagnostics, and four advisories. Recoverable
codes comprise 35 correct answers referencing missing choices, two missing
answers, and six missing rationales. Because the legacy validator groups records
by chapter/question label without question type, those 43 diagnostics currently
block 57 records across 39 labels. This is not an acceptable candidate result and
no Pack was built.

Read-only ordered stem alignment matched all 1,040 canonical IDs and all 1,040
24-repair candidate IDs. It found exactly seven parsed-only records and zero
target-only records. The same seven positions occur against both targets. Their
source-neutral chapter/question keys are 5/1, 7/1, 7/9, 15/1, 15/15, 28/1, and
38/1. Structural summaries show incomplete or merged parser products rather than
seven complete duplicate questions: missing rationales, missing answers,
absent/partial choices, or abnormally large combined fields. No source text or
fingerprint is stored in the match report.

Each parsed record now has a run-local `PFIR` identity, and the seven unmatched
records have explicit `PFIQA-BOUNDARY` findings. A strictly isolated comparison
candidate was built from the 1,040 aligned records using their existing stable
PrepFlow IDs. Its manifest retains all boundary and validation findings, records
zero applied repairs, and marks promotion readiness false with comparison and
explicit-approval blockers. Canonical and 24-repair candidate hashes were
unchanged, and the complete 220-test suite passes.

The first field/blocker comparison is recorded in
`docs/MOCK_IMPORT_COMPARISON_2026-08-02.md`. Of 24 repair lessons, 3 were
reproduced, 9 were not reproduced, and 12 produced a different result. The
isolated candidate has 331 blockers versus the known 277: 272 retained keys, 59
added keys, five missing known keys, and no shared-key reclassifications. Across
7,280 top-level fields, 5,990 are equal in all states, 770 match the normalized
24-repair candidate, 19 remain canonical-shaped, and 501 differ from both. The
complete 222-test suite passes; protected hashes remain unchanged.

The diagnostic-only attribution report shows that legacy cleaning makes 426 of
the 501 third-result fields exactly match the 24-repair candidate, changes another
45 without reaching either target, and leaves 30 unchanged. Nineteen of the 59
added blocker keys arise from the cleaning-path difference; 40 persist after
legacy cleaning. All five missing known keys are absent in both new parses. The
legacy cleaner was not placed on the default route, and the complete 223-test
suite passes.

Next, inventory the legacy transformations responsible for the 426 exact matches
and design source-neutral guarded equivalents for repeated extraction noise.
Protect each generalized rule with positive, negative, and Pack-drift tests. Keep
the 45 partially changed and 30 persistent fields in review, and do not
automatically apply any repair. The mock candidate must never promote or overwrite
canonical data automatically.

Question 108 has an unresolved, tracked source-verification hold on its
candidate-only A-to-C answer change. Canonical promotion remains blocked until
that change is checked against the separately retained source and the hold is
explicitly resolved.

## 11. First commands in a resumed session

Do not begin by applying a repair. First establish the local state:

```bash
cd ~/projects/prepflow || exit 1
git status --short --branch
git log -1 --oneline
python -m pytest -q
```

Expected branch and recent history before new work:

```text
feat/ingestion-workbench
HEAD: documentation commit publishing this handoff
code ancestor: f91b054 Add approved atomic choice-structure repairs
```

Expected test result at the checkpoint:

```text
190 passed before the pre-intake gate
```

Verify the ignored repair set still contains 24 records without recreating it.
Use the read-only comparison against the external snapshots before any candidate
rebuild:

```bash
python -m compiler.workbench_compare_cli \
  ../prepflow-backups/workbench-2026-08-02-17-repairs \
  ../prepflow-backups/workbench-2026-08-02-24-repairs
```

If the ignored workbench is missing or does not report 24 approved repairs, stop.
Restore or compare against the external 24-repair snapshot; do not recreate the
repairs from memory.

## 12. Collaboration rules

- Give the project owner one executable terminal step at a time.
- Explain what a command will change before an applying command.
- Use dry runs before batch application.
- Keep the canonical Pack unchanged.
- Do not conflate detection with authorization to repair.
- Discuss ambiguous educational or clinically meaningful content before changing
  it.
- Preserve correct-answer mappings and stable PrepFlow IDs.
- Do not persist source identity, filenames, citations, page locations, raw
  extraction text, or whole imported documents.
- Do not push ingestion work to the public repository.
- Commit generalized tools, tests, and durable documentation to the private
  workbench branch.
- Snapshot ignored candidate state after each coherent approved repair group.
- Update this handoff whenever the repair count, blocker count, active branch,
  next task, repository boundary, or recovery state materially changes.

## 13. Definition of the larger milestone

The Fundamentals cleanup is not complete when the ten structural exceptions are
gone. The larger milestone also requires:

- review or disposition of all remaining promotion blockers;
- a usable intake command or guided workflow for adding a new source;
- temporary incoming/run workspace handling and deletion guarantees;
- baseline-versus-candidate comparison;
- explicit candidate promotion;
- allowlisted public release staging that excludes private factory files; and
- removal of legacy importer/compiler material from the public product without
  breaking the deployed application.

Do not imply that these later stages are already implemented.
