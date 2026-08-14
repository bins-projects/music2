# Repair and Add Questions Workbench

Repair & Add Questions is an integrated station inside the private PrepFlow Workbench. Codespaces starts one server through `.devcontainer/start-workbench.sh`, forwards only port 8765, and opens Ingestion & Clean at `/`. The `Repair & Add Questions` navigation button opens `/questions/` on the same origin, and `Back to Ingestion & Clean` returns to `/`. The unified launcher verifies private `master`, both expected remotes, clean tracked state, and synchronization before it creates or updates the separate `prepflow-public-release` worktree. If that path is unavailable, the unified Workbench still starts and Repair & Add remains in save-only mode.

The operator sees only `Publishable` or `Publishing unavailable — will save`. Readiness is recalculated on load, selection changes, and immediately before the final action. No environment opt-in, readiness button, or confirmation dialog is required.

The standalone `ingestion_v2.question_workbench_server` entry point is an isolated localhost development harness only. It is not started by Codespaces and does not compete for port 8765.

## Repair workflow

1. Choose an installed Pack and search by question text, numeric suffix, or full PFQ ID.
2. Open the complete record, edit supported fields, and review highlighted changes.
3. Use the learner preview to test grading and rationale feedback.
4. Select `Replace question & publish`. If publishing is unavailable, the same action saves the repair in the private operation ledger without changing the Pack.
5. Reopen a pending repair from Saved Operations. Its one action publishes it when readiness returns.

The original PFQ ID, record position, and every unsupported or unchanged field are preserved.

## Addition workflow

1. Choose any installed Pack, one of its actual chapters, and a supported canonical type.
2. Author the stem, type-specific answers or response items, rationale, and optional notes.
3. Test the exact interaction in learner preview.
4. Select `Add question & publish`. In save-only mode, the Workbench atomically reserves the permanent Pack-specific PFQ ID and stores the complete addition.
5. Pending additions can be edited or reassigned to another chapter without changing the reserved ID.

## Canonical types

- `mc` and `multiple_choice`: exact runtime aliases for single-answer Multiple Choice. `mc` is the canonical stored type for newly authored questions. Existing `multiple_choice` records keep that stored type during repair unless a separately approved migration intentionally changes it.
- `multiple_response`: Select all that apply; complete-set grading with two or more correct choices.
- `completion`: Fill in the blank; one or more accepted answers with case and surrounding-whitespace normalization only.
- `ordered_response`: Put in order; every response item exactly once and exact-sequence grading.

All five values occur in installed Packs and are supported. Fundamentals uses `mc`; the medical-surgical, pediatrics, and pharmacy generations use `multiple_choice`. The Workbench exposes one operator-facing Multiple Choice choice while retaining the stored alias on repairs. Existing legacy records remain loadable without forced cleanup. New or edited records use strict authoring validation. The current legacy inventory includes records with missing rationales and a small number of mislabeled or duplicated answer keys; those records require an intentional repair before they can satisfy the stricter authoring contract.

## Persistence and recovery

The ignored private ledger at `output/question-workbench/operations.json` is atomically replaced under a file lock. It stores pending/published repairs and additions, reserved namespaces and IDs, blockers, publication stages, and commit SHAs. IDs are allocated against installed Packs and every saved operation, so abandoned or published reservations are never reused.

Publishing creates private evidence in `docs/QUESTION_OPERATION_LOG.md`, validates the complete Pack, regenerates the catalog and Pack precache, verifies private/public Pack byte equality, and commits and pushes each repository. If interruption occurs after either local commit, Saved Operations exposes `Resume publication`; recovery pushes the recorded commit and never inserts the question twice. Unrelated tracked changes remain blocking and are never reset, stashed, cleaned, or overwritten.
