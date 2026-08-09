from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from ingestion_v2.domain import DomainError

MARKETPLACE_BANNER_RE = re.compile(
    r"(?:[A-Za-z0-9.-]+[.](?:com|org|net) *- *)?"
    r"The Marketplace to Buy and Sell your Study Material",
    re.IGNORECASE,
)
DOWNLOADER_ATTRIBUTION_RE = re.compile(r"^Downloaded by:", re.IGNORECASE)
DISTRIBUTION_WARNING_RE = re.compile(
    r"^Distribution of this document is illegal$",
    re.IGNORECASE,
)
MARKETPLACE_PROMOTION_RE = re.compile(
    r"^(?:Want to earn|extra per year[?])",
    re.IGNORECASE,
)
ANSWER_KEY_RE = re.compile(
    r"^(?:ans(?:wer)?|correct(?:\s+answer)?)\s*:",
    re.IGNORECASE,
)
STANDALONE_CHOICE_LABEL_RE = re.compile(
    r"^[A-H](?:[.)])?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CleaningResult:
    text: str
    cleaner_name: str
    input_characters: int
    output_characters: int
    removed_repeated_lines: int
    stripped_repeated_suffixes: int
    protected_repeated_structures: int
    meaning_repairs: int = 0
    source_specific_rules: int = 0


class Cleaner(Protocol):
    def clean(self, text: str) -> CleaningResult: ...


class GuardedPageAwareCleaner:
    """Remove only repeated non-educational page-edge noise.

    This is intentionally a native v2 implementation. It does not infer missing
    words, choices, answers, or rationale content; it only removes a repeated
    line that is structurally safe and appears at a physical page edge.
    """

    cleaner_name = "native_guarded_page_aware_source_neutral_v2"

    def clean(self, text: str) -> CleaningResult:
        if not isinstance(text, str) or not text.strip():
            raise DomainError("Cleaner input must be non-empty extracted text")

        pages = _pages(_normalized_newlines(text))
        pages, attribution_removed, attribution_stripped = (
            _strip_repeated_marketplace_attribution(pages)
        )
        repeated = _repeated_lines(pages)
        protected = sum(
            1
            for value in repeated
            if _is_educational_shape(value)
        )
        removable = {
            value
            for value, count in repeated.items()
            if count >= 3 and not _is_educational_shape(value)
            and _is_repeated_page_edge(value, pages)
        }

        cleaned_pages = []
        removed_lines = attribution_removed
        stripped_suffixes = attribution_stripped
        for page in pages:
            cleaned, page_removed, page_stripped = _clean_page(page, removable)
            cleaned_pages.append(cleaned)
            removed_lines += page_removed
            stripped_suffixes += page_stripped

        cleaned = "\n\f\n".join("\n".join(page) for page in cleaned_pages)
        return CleaningResult(
            text=cleaned,
            cleaner_name=self.cleaner_name,
            input_characters=len(text),
            output_characters=len(cleaned),
            removed_repeated_lines=removed_lines,
            stripped_repeated_suffixes=stripped_suffixes,
            protected_repeated_structures=protected,
        )


def _strip_repeated_marketplace_attribution(
    pages: tuple[tuple[str, ...], ...],
) -> tuple[tuple[tuple[str, ...], ...], int, int]:
    """Remove only bounded, repeated marketplace-attribution blocks.

    A downloader line is the required anchor. We examine its immediate local
    neighbors instead of carrying attribution state through the rest of a page,
    so educational content such as answer keys can never be removed merely
    because it follows a marketplace banner.
    """

    downloader_pages = sum(
        1
        for page in pages
        if any(DOWNLOADER_ATTRIBUTION_RE.match(line.strip()) for line in page)
    )
    if downloader_pages < 3:
        return pages, 0, 0

    cleaned_pages: list[tuple[str, ...]] = []
    removed = 0
    stripped = 0

    for page in pages:
        lines = list(page)
        omitted: set[int] = set()

        for index, line in enumerate(lines):
            if not DOWNLOADER_ATTRIBUTION_RE.match(line.strip()):
                continue

            omitted.add(index)

            # A preceding line may contain a choice label followed by the
            # banner. Remove only the banner, retaining that label.
            if index and MARKETPLACE_BANNER_RE.search(lines[index - 1]):
                preserved = MARKETPLACE_BANNER_RE.sub("", lines[index - 1]).strip()
                if preserved:
                    lines[index - 1] = preserved
                    stripped += 1
                else:
                    omitted.add(index - 1)

            # The remaining boilerplate is adjacent to the downloader line.
            # Blank lines may separate it from a repeated banner, but no other
            # content is eligible for removal.
            cursor = index + 1
            while cursor < len(lines):
                normalized = lines[cursor].strip()
                if not normalized:
                    cursor += 1
                    continue
                if (
                    DISTRIBUTION_WARNING_RE.match(normalized)
                    or MARKETPLACE_PROMOTION_RE.match(normalized)
                ):
                    omitted.add(cursor)
                    cursor += 1
                    continue
                if MARKETPLACE_BANNER_RE.fullmatch(normalized):
                    omitted.add(cursor)
                    cursor += 1
                    continue
                break

        cleaned_pages.append(
            tuple(line for index, line in enumerate(lines) if index not in omitted)
        )
        removed += len(omitted)

    return tuple(cleaned_pages), removed, stripped

def _normalized_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _pages(text: str) -> tuple[tuple[str, ...], ...]:
    pages = []
    for page in text.split("\f"):
        lines = tuple(line.rstrip() for line in page.split("\n"))
        while lines and not lines[0].strip():
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines = lines[:-1]
        if lines:
            pages.append(lines)
    return tuple(pages)


def _normalized_line(value: str) -> str:
    return " ".join(value.split())


def _repeated_lines(pages: tuple[tuple[str, ...], ...]) -> dict[str, int]:
    page_occurrences: dict[str, set[int]] = {}
    for page_index, page in enumerate(pages):
        for line in page:
            normalized = _normalized_line(line)
            if normalized:
                page_occurrences.setdefault(normalized, set()).add(page_index)
    return {value: len(indices) for value, indices in page_occurrences.items()}


def _is_repeated_page_edge(value: str, pages: tuple[tuple[str, ...], ...]) -> bool:
    occurrences = 0
    for page in pages:
        nonempty = tuple(_normalized_line(line) for line in page if line.strip())
        if nonempty and value in {nonempty[0], nonempty[-1]}:
            occurrences += 1
    return occurrences >= 3


def _clean_page(
    page: tuple[str, ...],
    removable: set[str],
) -> tuple[tuple[str, ...], int, int]:
    lines = list(page)
    removed = 0
    stripped = 0

    while lines and _normalized_line(lines[0]) in removable:
        lines.pop(0)
        removed += 1
    while lines and _normalized_line(lines[-1]) in removable:
        lines.pop()
        removed += 1

    cleaned = []
    for line in lines:
        stripped_line = line

        # Answer keys are educational syntax, not containers for page-edge
        # suffix noise. Guard them again at application time so a future
        # profiler regression cannot remove a valid answer payload.
        if ANSWER_KEY_RE.match(_normalized_line(stripped_line)):
            cleaned.append(stripped_line)
            continue

        for noise in sorted(removable, key=len, reverse=True):
            suffix = re.compile(r"(?:\s+|\s*[-|:]\s*)" + re.escape(noise) + r"\s*$")
            candidate = suffix.sub("", stripped_line)
            if candidate != stripped_line and candidate.strip():
                stripped_line = candidate.rstrip()
                stripped += 1
                break
        cleaned.append(stripped_line)
    return tuple(cleaned), removed, stripped


def _is_educational_shape(value: str) -> bool:
    lowered = value.casefold()
    return bool(
        re.match(r"^(?:chapter|section)\s+\d+\b", value, re.IGNORECASE)
        or STANDALONE_CHOICE_LABEL_RE.fullmatch(value.strip())
        or re.match(r"^\d+[.)]\s+", value)
        or re.match(r"^[a-z][.)]\s+", value, re.IGNORECASE)
        or re.match(r"^(?:ans(?:wer)?|correct(?:\s+answer)?)\s*:", value, re.IGNORECASE)
        or re.match(r"^(?:dif|obj|msc|top|not)\s*:", value, re.IGNORECASE)
        or "rationale" in lowered
    )
