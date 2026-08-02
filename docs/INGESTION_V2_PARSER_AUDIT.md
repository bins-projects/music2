# Ingestion v2 Parser Audit

## Decision

V2 will preserve the existing parser as a benchmark and initially reuse its
proven structure recognition through a narrow adapter. The v2 domain does not
depend on legacy dictionaries, heuristic repairs, source-specific cleaning, or
stable-ID assignment inside parsing.

## Existing component classification

| Existing behavior | V2 disposition | Reason |
|---|---|---|
| chapter, section, question, choice, answer, and rationale recognition | wrap, then replace incrementally | proven across Fundamentals and Medical-Surgical |
| multiline choice and answer normalization | reuse behind adapter | mechanical structure handling with useful tests |
| type recognition for MC, multiple response, completion, and ordering | reuse behind adapter | established benchmark behavior |
| normalization into a consistent parsed record | replace at boundary | legacy normalizer mixes list/dictionary representations and contains a title-specific rule |
| broad missing-A recovery | exclude | detection is not authorization to reconstruct a choice |
| publisher/title-specific chapter cleanup | exclude from v2 boundary | violates the source-neutral default route |
| unnumbered-question heuristics | benchmark and finding source | potentially useful, but too inferential to become silent v2 truth |
| stable question identity | separate matching stage | source numbering is not durable PrepFlow identity |
| validation diagnostics | replace with structured findings | prose diagnostics are not sufficient review records |
| legacy models and canonical export | keep as benchmark | v2 candidate and promotion boundaries are independently guarded |

## Implemented boundary

`ExistingParserAdapter` accepts extracted text and returns immutable v2 parsed
records plus structured parser findings. It always disables broad missing-A
recovery and reports zero automatic repairs. It has no canonical Pack access.

`materialize_matched_batch` is a separate stage. It requires an exact mapping
from every run-local parsed record to a stable PrepFlow ID, preserves all parsed
values, and translates parser findings into the review engine. Missing or extra
identity mappings fail before any candidate can be built.

## Next replacement seams

1. Introduce a v2-native tokenizer that preserves page and line boundaries.
2. Replace legacy preprocessing functions individually using synthetic contracts.
3. Emit evidence spans in the temporary run only; durable findings remain
   source-neutral.
4. Add comparison tests proving each replacement does not lose benchmark records.
5. Retire the adapter only after both existing books and synthetic damage suites
   meet the same or stronger safety outcomes.
