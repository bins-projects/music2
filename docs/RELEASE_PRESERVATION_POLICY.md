# PrepFlow Release Preservation and Repository Boundary Policy

## Purpose

PrepFlow must preserve the last known-good public product while private ingestion,
repair, content, and interface work is developed and validated.

## Repository roles

```text
bins-projects/prepflow-dev = private development factory
bins-projects/PrepFlow     = public product
```

The repositories are not development mirrors.

The private factory may contain importer/compiler code, repair tooling, internal
QA, candidate-building tools, source-neutral tests, internal documentation, and
approved canonical Packs.

The public product should contain only approved canonical Packs, the browser
runtime, required runtime data, approved interface assets, public-facing
documentation, and the minimum code required for the application to operate.

Never push a private ingestion-workbench branch to the public repository.

## Protected states

### 1. Active private development

Work occurs on a focused branch in `prepflow-dev`. The branch may evolve through
small verified commits. Ignored candidate or repair artifacts must be protected by
external snapshots because they are intentionally absent from Git history.

### 2. Verified private checkpoint

After a coherent milestone:

1. run applicable automated tests;
2. verify any relevant browser workflow;
3. inspect the focused diff;
4. run privacy and artifact checks;
5. commit the intended code and documentation;
6. push the private branch;
7. verify the remote branch tip; and
8. snapshot any ignored candidate state needed for recovery.

### 3. Curated public release

A public release must be assembled from an explicit allowlist. Do not mirror or
merge the entire private factory branch into public `master`.

Release staging must reject:

- importer and compiler implementation not required at runtime;
- repair workbench code;
- internal QA ledgers and findings;
- candidate Packs and repair records;
- temporary input, extraction, and cleaned-document artifacts;
- internal ingestion reports;
- source-identifying metadata; and
- unrelated development files.

Before publishing:

1. identify the last known-good public commit;
2. stage only allowlisted public files;
3. compare the staged product with both the approved private checkpoint and the
   current public product;
4. run runtime tests and browser verification;
5. inspect privacy and artifact results;
6. review the exact public diff;
7. update public `master` through a reviewable, non-force workflow; and
8. verify the deployed public site before considering the release complete.

## Public branch policy

Public should have one long-lived branch:

```text
master
```

Do not recreate public development, preview, build, hotfix, review, or historical
release branches merely because they exist in a backup bundle. Create a temporary
public release branch only when the curated release workflow needs one, and remove
it after the release is verified and its commit remains recoverable.

Release tags are optional. Recoverability depends on verified commits and external
bundles, not on preserving a large tag collection.

## Privacy and artifact gate

Before private commits and again before public staging:

1. scan intended changes for personal names, personal email addresses, usernames,
   device names, absolute home paths, credentials, and source provenance;
2. use role-based language and repository-relative or generic paths;
3. exclude imported sources, full raw extraction, full cleaned-document text,
   screenshots, transfer archives, temporary proofs, and unrelated artifacts;
4. verify persisted Packs and repair records contain no forbidden provenance; and
5. inspect the exact staged or proposed diff.

Required flow:

```text
edit → test → privacy scan → inspect diff → commit → push
```

## Rollback and emergency recovery

The previous public version must remain recoverable until the new deployment is
verified.

Recovery may use:

- the prior public commit;
- a temporary rollback branch created from that commit;
- a verified Git bundle;
- preserved emergency refs; or
- focused restoration of files from known-good history.

Do not rebuild a known-good release from scratch.

## Prohibited actions

Do not:

- force-push public `master`;
- publish directly from ignored candidate output;
- merge an entire private factory branch into public;
- expose source documents, provenance, repair ledgers, or internal QA publicly;
- delete the only verified recovery copy of a unique commit;
- overwrite the canonical Pack during candidate repair; or
- assume a successful private push changed the public product.

## Current boundary checkpoint

At the August 2, 2026 ingestion-workbench checkpoint:

```text
private master:          e522a586003a6534e7b7dd502bbd3447fde42d96
public master:           e522a586003a6534e7b7dd502bbd3447fde42d96
active private branch:   feat/ingestion-workbench
code checkpoint:         7b21b961c8f56d61f76871c0cb839663b18e029c
public deployment:       unchanged by the workbench milestone
```

The documentation commit containing this policy and the workbench handoff is
expected to be the active private branch tip and to descend from the code
checkpoint above.

The public branch cleanup is complete. Removal of legacy compiler/parser material
already present on public `master`, plus implementation of allowlisted release
staging, remains future work.

## Change control

Update this policy when repository roles, branch policy, public staging,
recoverability, privacy rules, or the release workflow materially change.
