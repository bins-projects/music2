import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedTextRepair:
    rule_id: str
    pattern: re.Pattern
    replacement: str


@dataclass(frozen=True)
class SplitCandidate:
    separated: str
    mechanical_join: str


@dataclass(frozen=True)
class TextRepairAnalysis:
    blocked: bool
    blocker_codes: tuple[str, ...]
    approved_rule_ids: tuple[str, ...]
    split_candidates: tuple[SplitCandidate, ...]


@dataclass(frozen=True)
class TextRepairResult:
    text: str
    applied_rule_ids: tuple[str, ...]
    analysis: TextRepairAnalysis


@dataclass(frozen=True)
class TypographyNormalization:
    text: str
    opening_marks_replaced: int
    closing_marks_replaced: int
    opening_quotes: int
    closing_quotes: int

    @property
    def balanced(self) -> bool:
        return self.opening_quotes == self.closing_quotes


APPROVED_TEXT_REPAIRS = (
    ApprovedTextRepair(
        rule_id="join_medications_suffix",
        pattern=re.compile(r"\bmedication s\b"),
        replacement="medications",
    ),
    ApprovedTextRepair(
        rule_id="join_ask_fragment",
        pattern=re.compile(r"\band as k for\b"),
        replacement="and ask for",
    ),
    ApprovedTextRepair(
        rule_id="join_which_fragment",
        pattern=re.compile(r"\bw hich\b"),
        replacement="which",
    ),
)

SPLIT_SUFFIX_RE = re.compile(
    r"\b([A-Za-z]{4,})\s+"
    r"(s|ed|ing|ly|tion|ment|ness|ity|al|ous|ive)\b"
)
WORD_RE = re.compile(r"\b[A-Za-z]+\b")
APOSTROPHE_MARKS = {"'", "‘", "’"}


def normalize_extraction_typography(text: str) -> TypographyNormalization:
    opening_marks = text.count("―")
    closing_marks = text.count("‖")
    normalized = text.replace("―", "“").replace("‖", "”")

    return TypographyNormalization(
        text=normalized,
        opening_marks_replaced=opening_marks,
        closing_marks_replaced=closing_marks,
        opening_quotes=normalized.count("“"),
        closing_quotes=normalized.count("”"),
    )


def case_transitions(word: str) -> int:
    transitions = 0
    for left, right in zip(word, word[1:]):
        if left.islower() != right.islower():
            transitions += 1
    return transitions


def interleaving_blockers(text: str) -> tuple[str, ...]:
    word_matches = tuple(WORD_RE.finditer(text))
    words = [match.group(0) for match in word_matches]
    singleton_fragments = [
        match.group(0)
        for match in word_matches
        if len(match.group(0)) == 1
        and match.group(0).lower() not in {"a", "i"}
        and not (
            match.group(0).lower() == "s"
            and match.start() > 0
            and text[match.start() - 1] in APOSTROPHE_MARKS
        )
    ]
    mixed_case_fragments = [
        word
        for word in words
        if not word.islower()
        and not word.isupper()
        and not word.istitle()
        and case_transitions(word) >= 2
    ]

    blockers = []
    if len(singleton_fragments) >= 3:
        blockers.append("fragment_density")
    if len(mixed_case_fragments) >= 2:
        blockers.append("mixed_case_interleaving")
    if singleton_fragments and mixed_case_fragments:
        blockers.append("combined_interleaving")

    return tuple(blockers)


def detect_split_candidates(text: str) -> tuple[SplitCandidate, ...]:
    candidates = []
    seen = set()

    for match in SPLIT_SUFFIX_RE.finditer(text):
        separated = match.group(0)
        mechanical_join = "".join(match.groups())
        key = (separated, mechanical_join)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            SplitCandidate(
                separated=separated,
                mechanical_join=mechanical_join,
            )
        )

    return tuple(candidates)


def analyze_text_repairs(text: str) -> TextRepairAnalysis:
    blockers = interleaving_blockers(text)
    approved_rule_ids = tuple(
        rule.rule_id
        for rule in APPROVED_TEXT_REPAIRS
        if rule.pattern.search(text)
    )

    return TextRepairAnalysis(
        blocked=bool(blockers),
        blocker_codes=blockers,
        approved_rule_ids=approved_rule_ids,
        split_candidates=detect_split_candidates(text),
    )


def apply_approved_text_repairs(text: str) -> TextRepairResult:
    analysis = analyze_text_repairs(text)
    if analysis.blocked:
        return TextRepairResult(
            text=text,
            applied_rule_ids=(),
            analysis=analysis,
        )

    repaired = text
    applied = []
    for rule in APPROVED_TEXT_REPAIRS:
        repaired, count = rule.pattern.subn(rule.replacement, repaired)
        if count:
            applied.append(rule.rule_id)

    return TextRepairResult(
        text=repaired,
        applied_rule_ids=tuple(applied),
        analysis=analysis,
    )
