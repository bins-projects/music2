import math
import re
from collections import Counter, defaultdict


URL_RE = re.compile(r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net)\b)", re.IGNORECASE)
EDUCATIONAL_STRUCTURE_RE = re.compile(
    r"^(?:chapter\s+\d+|\d+[.)]\s+\S|[a-g][.)]\s*\S|ans\s*:|"
    r"multiple\s+(?:choice|response)|completion|ordering|"
    r"(?:dif|obj|top|msc|key|nclex|not|concepts)\s*:)",
    re.IGNORECASE,
)
PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")


def _normalize(line: str) -> str:
    return " ".join(line.split()).casefold()


def profile_repeated_page_noise(
    text: str,
    *,
    edge_depth: int = 6,
    minimum_pages: int | None = None,
) -> dict:
    """Detect repeated page noise without retaining candidate text."""
    pages = text.split("\f")
    page_lines = []
    line_pages = defaultdict(set)
    edge_pages = defaultdict(set)
    occurrences = Counter()
    originals = {}
    for page_index, page in enumerate(pages):
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        page_lines.append(lines)
        edge_indexes = set(range(min(edge_depth, len(lines))))
        edge_indexes.update(range(max(0, len(lines) - edge_depth), len(lines)))
        for line_index, line in enumerate(lines):
            normalized = _normalize(line)
            if not normalized:
                continue
            originals.setdefault(normalized, line)
            occurrences[normalized] += 1
            line_pages[normalized].add(page_index)
            if line_index in edge_indexes:
                edge_pages[normalized].add(page_index)

    page_count = len(pages)
    threshold = minimum_pages or max(3, math.ceil(page_count * 0.1))
    candidates = []
    candidate_lines = []
    for normalized in sorted(line_pages):
        pages_seen = len(line_pages[normalized])
        edge_seen = len(edge_pages[normalized])
        has_url = bool(URL_RE.search(originals[normalized]))
        educational_shape = bool(EDUCATIONAL_STRUCTURE_RE.search(originals[normalized]))
        page_number_shape = bool(PAGE_NUMBER_RE.fullmatch(originals[normalized].strip()))
        qualifies = (
            edge_seen >= threshold
            or (has_url and pages_seen >= threshold)
        )
        if not qualifies:
            continue
        candidate_lines.append(normalized)
        candidates.append(
            {
                "candidate_id": f"PFNOISE-LINE-{len(candidates) + 1:04d}",
                "occurrences": occurrences[normalized],
                "pages": pages_seen,
                "edge_pages": edge_seen,
                "character_count": len(originals[normalized]),
                "has_url_shape": has_url,
                "educational_structure_shape": educational_shape,
                "page_number_shape": page_number_shape,
                "automatic_removal_eligible": not educational_shape,
                "classification": (
                    "protected_repeated_educational_structure"
                    if educational_shape
                    else "repeated_page_edge_line"
                    if edge_seen >= threshold
                    else "repeated_line"
                ),
            }
        )

    suffixes = []
    for candidate_index, normalized in enumerate(candidate_lines, start=1):
        suffix_occurrences = 0
        suffix_pages = set()
        for page_index, lines in enumerate(page_lines):
            for line in lines:
                value = _normalize(line)
                if value != normalized and value.endswith(" " + normalized):
                    suffix_occurrences += 1
                    suffix_pages.add(page_index)
        if len(suffix_pages) < threshold:
            continue
        suffixes.append(
            {
                "candidate_id": f"PFNOISE-SUFFIX-{len(suffixes) + 1:04d}",
                "learned_from_line_candidate": f"PFNOISE-LINE-{candidate_index:04d}",
                "occurrences": suffix_occurrences,
                "pages": len(suffix_pages),
                "classification": "repeated_suffix_overlay",
            }
        )

    return {
        "format": "prepflow_repeated_noise_profile",
        "version": "1.0",
        "page_count": page_count,
        "minimum_pages": threshold,
        "line_candidates": candidates,
        "suffix_candidates": suffixes,
        "detection_only": True,
        "text_removed": False,
    }
