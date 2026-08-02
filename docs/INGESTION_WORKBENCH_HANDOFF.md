# PrepFlow Ingestion Workbench Handoff

**Updated:** August 2, 2026  
**Status:** Authoritative continuity record for the active Fundamentals cleanup

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
code checkpoint:      7b21b961c8f56d61f76871c0cb839663b18e029c
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
commit `7b21b96` (`Repair exact duplicate choice blocks safely`).

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
```

Each snapshot contains:

```text
fundamentals/candidate.prepflow.json
fundamentals/candidate-manifest.json
fundamentals/repair-records.json
SHA256SUMS
```

The 15-repair snapshot is the current recovery point.

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
approved candidate-only repairs: 15
promotion blockers:               303
automated tests:                  159 passed
canonical Pack:                   unchanged
```

The 15 repair lessons are:

```text
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
fields normalized:          1378
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
python -m compiler.candidate_cli
python -m pytest -q
```

Batch commands are dry-run by default. `--apply` writes only the candidate and
repair set unless a separate, explicitly approved promotion process is invoked.

## 8. Completed structural exceptions

The structural-exception review has safely resolved:

```text
PFQ-fundamentals-000000091
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

## 9. Remaining structural exceptions

Ten questions remain in this structural review group:

```text
PFQ-fundamentals-000000108
PFQ-fundamentals-000000111
PFQ-fundamentals-000000113
PFQ-fundamentals-000000357
PFQ-fundamentals-000000369
PFQ-fundamentals-000000611
PFQ-fundamentals-000000676
PFQ-fundamentals-000000937
PFQ-fundamentals-000000944
PFQ-fundamentals-000001022
```

Known preliminary classifications:

- 108 and 111: apparent leaked extra `D Evaluation` content across question
  boundaries;
- 113: rationale appears absorbed into choice B, with choices C/D displaced or
  out of order;
- 357 and 611: missing choice B;
- 369: missing choice C;
- 676 and 944: missing choice A appears absorbed into the stem, but damage is too
  ambiguous for the existing high-confidence batch;
- 937: appears to combine two different choice sets and has suspicious answer
  mapping; and
- 1022: missing choice C.

These descriptions are preliminary QA observations, not approved corrections.

## 10. Exact next task

Begin with questions 108 and 111.

The safety framework already applies, but no generalized `D Evaluation` repair
rule exists. Do not delete that text merely because the phrase repeats.

For each question:

1. open the flagged question through the repair/audit tooling;
2. inspect its complete source-neutral question fields;
3. inspect the immediately neighboring PrepFlow questions to understand the
   boundary shape;
4. determine independently whether the extra choice is leaked content;
5. compare the two findings only after both have been understood;
6. decide whether they share one deterministic mechanical signature;
7. if they do, implement one guarded candidate-only operation with exact-shape,
   answer-map, positive, negative, and stale-shape tests; or
8. if they do not, keep them as individual repairs or promotion blockers.

The manual checks are rule-development work. They are not permission to silently
rewrite both questions.

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
parent: 7b21b96 Repair exact duplicate choice blocks safely
```

Expected test result at the checkpoint:

```text
159 passed
```

Then verify that the ignored repair set still contains 15 records by rebuilding
the candidate:

```bash
python -m compiler.candidate_cli
```

If the ignored workbench is missing or does not report 15 approved repairs, stop.
Restore or compare against the external 15-repair snapshot; do not recreate the
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
