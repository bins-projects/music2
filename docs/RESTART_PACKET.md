# PrepFlow Restart Packet

## Mandatory first action

Read the milestone-specific handoff before proposing a command or changing a file:

```text
docs/INGESTION_WORKBENCH_HANDOFF.md
```

For ingestion, repair, Pack cleanup, source intake, compiler, QA, or public/private
repository-boundary work, also read:

```text
docs/INGESTION_ARCHITECTURE.md
docs/RELEASE_PRESERVATION_POLICY.md
```

The ingestion-workbench handoff contains the active branch, exact checkpoint,
repair and blocker counts, recovery locations, completed work, remaining question
list, next task, and safe restart commands.

## Current active milestone

```text
milestone:     Fundamentals cleanup and source-agnostic ingestion workbench
repository:    bins-projects/prepflow-dev
branch:        feat/ingestion-workbench
code checkpoint: fd23200
tests:         190 passed before the pre-intake gate
repair state:  24 approved candidate-only repairs
blockers:      277
canonical:     unchanged
```

The 17-to-24 repair comparison gate is recorded in
`docs/PRE_INTAKE_SAFETY_GATE_2026-08-02.md`. Discuss the source-neutral intake
design before implementing it. Question 108 has an unresolved source-verification
hold and canonical promotion remains blocked.

## Repository boundary

Use these names consistently:

```text
dev/private factory: bins-projects/prepflow-dev
public product:       bins-projects/PrepFlow
```

Private ingestion work must not be pushed to public. Public `master` remains the
deployed product and was not modified by the active workbench milestone.

## Authority order

1. The project owner's explicit direction.
2. The current local repository and ignored workbench state.
3. `docs/INGESTION_WORKBENCH_HANDOFF.md`.
4. `docs/INGESTION_ARCHITECTURE.md`.
5. `docs/RELEASE_PRESERVATION_POLICY.md`.
6. The private branch on GitHub.
7. Dated historical documents.

Never overwrite newer local ignored candidate work merely because GitHub contains
only the committed pipeline code.

## Working discipline

- Give one executable step at a time.
- Inspect status before changing files.
- Dry-run batch repairs before `--apply`.
- Apply repairs to candidates only.
- Run the full tests after implementation changes.
- Snapshot the ignored workbench after coherent approved repair groups.
- Commit and push generalized tools, tests, and continuity documentation to the
  private workbench branch.
- Keep source documents, raw extraction, candidate Packs, repair ledgers, internal
  reports, and private factory code out of the public product.
- Update the milestone handoff before ending a substantial session.

## New-chat opening message

The project owner can start a new chat with:

> Read `docs/RESTART_PACKET.md` and the handoff it names from
> `bins-projects/prepflow-dev` branch `feat/ingestion-workbench`. Then tell me where
> we are and discuss the next step with me before proposing a command.
