from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ingestion_v2.domain import DomainError


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
    """Expose proven generalized cleaning behind an auditable v2 boundary."""

    cleaner_name = "guarded_page_aware_source_neutral_v1"

    def clean(self, text: str) -> CleaningResult:
        if not isinstance(text, str) or not text.strip():
            raise DomainError("Cleaner input must be non-empty extracted text")

        # Existing generalized mechanics stay isolated behind this adapter while
        # v2 progressively replaces them with native components.
        from compiler.cleaner import clean_text_generalized
        from compiler.noise_profile import remove_profiled_noise

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        removal = remove_profiled_noise(normalized)
        cleaned = clean_text_generalized(removal.text)
        return CleaningResult(
            text=cleaned,
            cleaner_name=self.cleaner_name,
            input_characters=len(text),
            output_characters=len(cleaned),
            removed_repeated_lines=removal.removed_whole_lines,
            stripped_repeated_suffixes=removal.stripped_suffixes,
            protected_repeated_structures=removal.protected_candidates,
            meaning_repairs=0,
            source_specific_rules=0,
        )
