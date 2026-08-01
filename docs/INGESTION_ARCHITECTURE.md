# PrepFlow Ingestion Architecture

## Status

This document is the authoritative contract for PrepFlow ingestion work.

It governs source handling, temporary artifacts, candidate Packs, question repair,
validation, approval, and the boundary between the private development repository
and the public product repository.

## 1. Core Identity

PrepFlow is a source-agnostic content refinery.

A person deliberately chooses material to import. That choice makes the educational
content eligible to become canonical PrepFlow material after it has been parsed,
organized, validated, repaired when necessary, and approved.

PrepFlow is not:

- a document archive;
- a source library;
- a citation manager;
- a provenance database;
- a publisher catalog; or
- a permanent store for imported files or extracted documents.

The finished, approved Pack is the durable product of ingestion.

## 2. Source-Agnostic Rule

The ingestion system must not preserve information that identifies where imported
material originated.

Persisted Pack data may include only source-neutral study information such as:

- PrepFlow Pack identifier;
- PrepFlow question identifier;
- chapter or other organizational grouping;
- question type;
- question stem;
- choices when applicable;
- correct answer or answers;
- rationale when available;
- source-neutral study tags or organizational fields; and
- source-neutral QA or repair status tied to a PrepFlow identifier.

The system must not persist:

- original filenames or paths;
- document titles;
- authors;
- publishers;
- editions;
- file hashes used as source fingerprints;
- page numbers or source locations;
- source-document metadata;
- import records that identify a source;
- original PDF, DOC, DOCX, EPUB, or similar files;
- full raw extraction text;
- full cleaned-document text; or
- identifying source fragments in logs, reports, or test fixtures.

The fact that a person selected the material is sufficient. PrepFlow does not need
to retain evidence of that selection or the identity of the material.

## 3. Temporary Import Lifecycle

All source and whole-document artifacts are temporary working material.

The intended lifecycle is:

1. A temporary copy is placed in a private, ignored incoming area.
2. PrepFlow extracts text into a private, ignored run workspace.
3. PrepFlow cleans the extracted text.
4. After successful extraction and cleaning checks, the temporary imported source
   copy is deleted.
5. Parsing converts the cleaned text into candidate question records.
6. Type-aware validation and QA identify uncertain or damaged records.
7. Human-approved repairs are applied to candidate records only.
8. A candidate Pack is built and compared with the expected import results.
9. After approval, the candidate becomes the canonical Pack.
10. Raw extraction, cleaned full-document text, detection artifacts containing
    source text, and other whole-document working files are deleted.

Original files stored separately by the user are outside PrepFlow's ownership and
must never be modified or deleted. PrepFlow deletes only the temporary copy
deliberately placed into its incoming area.

If a run fails before a safe cleanup point, PrepFlow must report the failure
clearly. It must never reach outside its own ignored workspace to recover, modify,
or delete a file.

Reprocessing requires the user to supply the original material again from separate
storage. PrepFlow does not retain a hidden archival copy for convenience.

## 4. Canonical Processing Flow

The authoritative processing flow is:

Temporary source
→ temporary extraction
→ temporary cleaning
→ parsing
→ normalization
→ type-aware validation
→ QA findings
→ repair workbench
→ candidate Pack
→ comparison and approval
→ canonical Pack
→ temporary-artifact cleanup

Each stage has one responsibility:

- Adapters read supported input formats.
- Extraction obtains text without deciding educational meaning.
- Cleaning removes proven non-educational noise and mechanical extraction damage.
- Parsing recognizes questions, chapters, choices, answers, rationales, and types.
- Normalization converts supported parser output into one Pack-ready shape.
- Validation checks structural and content invariants without inventing content.
- QA classifies uncertainty and sends reviewable records to the workbench.
- Repair applies explicit field-level or atomic structural decisions to candidate
  records.
- Approval promotes a validated candidate Pack to canonical status.
- Cleanup removes temporary source and whole-document artifacts.

## 5. Candidate-First Safety

Import and repair operations must not directly modify an approved Pack.

Every run produces a candidate. The canonical Pack remains unchanged until the
candidate passes validation, comparison, and explicit approval.

At minimum, promotion must confirm:

- the candidate can be loaded;
- required Pack and question fields are present;
- question types are structurally valid;
- correct-answer mappings are valid;
- identifiers are valid and stable;
- chapter organization is coherent;
- no unexplained question loss or duplication occurred;
- unresolved high-risk findings are blocked; and
- temporary source artifacts are eligible for cleanup.

## 6. Human-in-the-Loop Repair

The repair workbench presents one flagged question at a time in wrapped,
side-scroll-free text.

A review shows only source-neutral question data:

- PrepFlow question ID;
- chapter or organizational group;
- question type;
- stem;
- choices;
- correct answer or answers;
- rationale;
- flagged field;
- finding type; and
- proposed correction when one is safe to propose.

A field-level repair record may retain:

- PrepFlow question ID;
- field or field path;
- previous question-field value;
- corrected question-field value;
- source-neutral damage category;
- approval state; and
- whether the decision remains a one-question repair or has been promoted into a
  generalized rule.

It must not retain source identity or document provenance.

A structural repair record may instead retain a source-neutral operation, the
expected pre-change question shape, and the corrected values needed to apply that
operation. Structural changes must be atomic. For example, when a visible choice
has been absorbed into a stem, one repair must correct the stem and restore the
choice together, then revalidate the complete question and its correct-answer
mapping. A stale pre-change shape blocks the repair rather than risking a partial
or misplaced edit.

## 7. Repair Confidence

Repairs are separated by risk.

### Deterministic mechanical repair

Safe candidates include unambiguous spacing artifacts, exact duplicate values,
known encoding substitutions, and other changes that cannot alter educational
meaning. These may become automatic only when protected by focused tests.

### Review-required repair

Likely reconstructions, watermark interleaving, damaged words, or uncertain
punctuation require human approval. The system may propose a correction but must
not silently treat probability as fact.

### Source-required repair

Missing choices whose wording is absent, absent correct answers, truncation,
dosages, measurements, negations, priority wording, select-all-that-apply
structure, and changes that may alter clinical meaning require the user to consult
or resupply the separately stored material. A choice whose complete wording is
visibly absorbed into an adjacent field may be restored through a human-approved
atomic structural repair.

## 8. Turning Repairs into Importer Knowledge

A correction to one question does not automatically become a global rewrite rule.

Each resolved finding is classified as one of:

- a one-question repair;
- a reusable detector;
- a generalized mechanical repair;
- a parser improvement;
- a source-neutral validation rule; or
- a promotion-blocking condition.

A generalized rule must have:

- a narrowly defined trigger;
- positive examples;
- negative examples;
- a test proving the intended repair;
- a test proving valid content is not changed; and
- comparison results showing no unexplained Pack drift.

Tests and fixtures should use minimal source-neutral examples. They must not become
a repository of identifying document excerpts.

## 9. Baseline Comparison

Importer improvements are evaluated against a known baseline.

When the original material is supplied again, PrepFlow may run the baseline and
candidate pipelines in the same temporary workspace and compare:

- question counts;
- chapter assignments;
- identifiers;
- question types;
- stems;
- choices;
- correct-answer mappings;
- rationales;
- QA findings;
- repaired records; and
- unexplained additions, losses, or changes.

The comparison report must be source-neutral. It may identify Pack and question
records, but it must not retain the input filename, document identity, or original
whole-document text.

After the comparison and approval decision, its temporary source-derived working
artifacts are deleted.

## 10. Identifier Stability

PrepFlow identifiers belong to PrepFlow content, not to source documents.

Existing approved question IDs must be preserved across repairs and rebuilds.
Reordering questions must not silently change identity. New IDs must be assigned
without embedding filenames, titles, page numbers, publishers, or other provenance.

## 11. Private and Public Repository Boundary

The private development repository is the factory. It may contain:

- importer and compiler code;
- source-neutral adapters and profiles;
- validation and QA code;
- the repair workbench;
- source-neutral tests and fixtures;
- candidate-building tools;
- release-building tools;
- internal architecture documentation; and
- approved canonical Packs used to build a release.

Neither repository may contain imported source documents or persistent
whole-document extraction artifacts.

The public repository is the finished product. A curated release process should
publish only:

- approved canonical Packs;
- the browser runtime;
- runtime data needed by the application;
- approved visual and interface assets;
- public-facing documentation; and
- the minimum programming required for the product to operate.

The public repository must not receive the private importer, repair workbench,
internal QA ledgers, temporary candidate files, or internal ingestion reports.

Once the private factory begins diverging from the public product, public releases
must be assembled through an explicit allowlisted release process rather than by
mirroring the entire private master branch.

## 12. Drug-Card Ingestion

Drug-card ingestion follows the same contract.

The private factory may parse, validate, repair, and approve candidate drug cards.
The public product receives only the approved source-neutral card library and the
runtime needed to display it.

No original drug source document, filename, citation record, or source-identifying
metadata becomes a runtime dependency.

## 13. Required Cleanup Guarantees

Implementation of the ingestion workbench must include tests proving that:

- incoming and run workspaces are ignored by Git;
- a successful run deletes its temporary imported source copy;
- promotion or explicit completion deletes whole-document raw and cleaned artifacts;
- canonical Packs are not modified before approval;
- failed runs never delete files outside PrepFlow's own workspace;
- persisted Packs and repair records contain no forbidden provenance fields; and
- public release staging rejects private ingestion files and temporary artifacts.

## 14. First Implementation Slice

The first vertical slice will:

1. load the existing Fundamentals QA ledger;
2. select one flagged question by PrepFlow ID;
3. display it in wrapped text;
4. accept a field-level correction;
5. write a source-neutral repair record;
6. apply that repair to a candidate Pack only;
7. validate the candidate question;
8. show the before-and-after question fields; and
9. prove the approved Fundamentals Pack remains unchanged.

This slice does not import a new document yet. It establishes the repair,
validation, and candidate-safety foundation that the independent importer will use.

The workbench subsequently extends this foundation with atomic structural repairs,
including splitting a visible choice out of a damaged stem. These repairs remain
candidate-only and use exact pre-change checks to prevent partial application.
