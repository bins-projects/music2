# Cross-Source Cleaning Inventory — August 2, 2026

## Purpose

This inventory compares the unchanged Fundamentals and Medical-Surgical raw
extractions without retaining or quoting source text. Counts are diagnostic only;
the legacy cleaner remains outside the default intake route.

## Fundamentals

The generalized artifact contains 20,353 lines and 1,137,914 characters. The
diagnostic legacy artifact contains 16,844 lines and 1,042,401 characters.

- 428 standalone document-share notices;
- 432 inline document-share overlays;
- 355 repeated test-bank title suffixes;
- 364 repeated domain-brand suffixes; and
- 42 repeated publisher/test-bank header lines.

## Medical-Surgical

The generalized artifact contains 23,847 lines and 1,060,563 characters. The
diagnostic legacy artifact contains 18,342 lines and 948,058 characters.

- 480 download notices;
- 480 distribution warnings;
- 480 standalone marketplace lines;
- 958 inline marketplace overlays;
- 145 trailing standalone metadata artifacts;
- 31 trailing source-title fragments;
- 7 standalone metadata artifacts; and
- 41 repeated publisher/header lines.

## Cross-source conclusion

The literal patterns differ, but their structural roles are the same: highly
repeated page-level source notices, legal/download messages, commerce/branding
lines, publisher/test-bank headers, and repeated suffix overlays attached to
otherwise valid educational lines.

The default cleaner must not gain brand, publisher, title, edition, or filename
rules. The next generalized design should learn temporary run-local noise
candidates from repetition and page position, distinguish whole-line noise from
repeated suffix overlays, and require conservative frequency/shape guards. It
must emit findings when confidence is insufficient rather than remove text.

Acceptance requires positive and negative synthetic tests plus unchanged valid
content and improved drift/blocker results on both isolated runs. A rule is not
acceptable merely because it recreates one legacy output.

## Page-aware detection result

Fresh extraction preserved temporary page boundaries: 433 Fundamentals pages and
480 Medical-Surgical pages. The detection-only profiler found:

| Source | Repeated lines | Protected educational shapes | Removal-eligible candidates | Repeated suffixes |
|---|---:|---:|---:|---:|
| Fundamentals | 6 | 3 | 3 | 0 |
| Medical-Surgical | 5 | 2 | 3 | 1 |

The protected candidates match source-neutral question/answer/chapter/section or
metadata shapes and are explicitly ineligible for automatic removal. The profiler
does not select repeated educational text in page interiors. It stores only
candidate IDs, counts, page coverage, edge coverage, lengths, and structural
flags—no candidate text or fingerprint.

No text was removed. The next gate is a dry-run comparison of the six eligible
whole-line candidates and one suffix candidate against both protected Pack
benchmarks before any generalized removal operation is authorized.
