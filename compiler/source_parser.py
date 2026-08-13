import re


CHAPTER_RE = re.compile(r"^Chapter\s+\d+\s*:", re.IGNORECASE)
SECTION_HEADERS = {
    "MULTIPLE CHOICE",
    "MULTIPLE RESPONSE",
    "COMPLETION",
    "ORDERING",
}
QUESTION_RE = re.compile(r"^(\d+)\.\s+(.+)")
SYNTHETIC_QUESTION_RE = re.compile(
    r"^\[PREPFLOW_QUESTION\]\s*(\d+)\.\s+(.+)"
)
CHOICE_RE = re.compile(r"^([a-gA-G])\.\s+(.+)")
PAREN_CHOICE_RE = re.compile(r"^([a-gA-G])\)\s+(.+)")
ANSWER_RE = re.compile(r"^ANS\b\s*:?\s*(.*)", re.IGNORECASE)
DOWNLOADED_BY_ATTRIBUTION_RE = re.compile(
    r"^Downloaded by:\s+\S+(?:\s*\|\s*\S+)?\s*",
    re.IGNORECASE,
)
LONG_ANSWER_RE = re.compile(
    r"^(?:Correct\s+)?Answer:\s*([a-gA-G])"
    r"(?:[.)]\s*.*)?$",
    re.IGNORECASE,
)
RATIONALE_PREFIX_RE = re.compile(
    r"^(?:Rationale|Explanation|Feedback):\s*(.*)$",
    re.IGNORECASE,
)
INLINE_ANSWER_RE = re.compile(
    r"^(.*?)(?:\s+(?:-\s*)?ANS:\s*|\s+ANS>\s*)(.+?)\s*$",
    re.IGNORECASE,
)
CHOICE_MARKER_ONLY_RE = re.compile(r"^[a-gA-G]\.$")
OCR_C_CHOICE_RE = re.compile(
    r"^(?:[¢©]c?|e?c|ce|e)\.?\s+(.+)",
    re.IGNORECASE,
)
METADATA_RE = re.compile(
    r"^(DIF|OBJ|TOP|MSC|KEY|NCLEX|NOT|CONCEPTS):",
    re.IGNORECASE,
)
INLINE_METADATA_RE = re.compile(
    r"\s+(?:(?:Remembering|Understanding|Applying|Analyzing|Evaluating|"
    r"Creating)\s+)?(?:DIF|OBJ|TOP|MSC|KEY|NCLEX|NOT|CONCEPTS):.*$",
    re.IGNORECASE,
)
PAGE_BREAK_MARKER = "[PREPFLOW_PAGE_BREAK]"
SOURCE_SHARE_FOOTER_RE = re.compile(r"^Document shared on https?://", re.IGNORECASE)
PAGE_ARTIFACT_RE = re.compile(
    r"^(?:[A-Z](?:\s+[A-Z]){0,8}|.*\b(?:test bank|edition)\b.*|"
    r"[A-Z]{4,}\.[A-Z]{2,4})$",
    re.IGNORECASE,
)
INLINE_FIRST_CHOICE_RE = re.compile(
    r"^(\d+\.\s+.+?\?)\s*(?:[A-Z][A-Z .]{0,48}\s+)?"
    r"([a-gA-G])\s*[.)]\s+(.+)$"
)
CHOICE_SENTENCE_END_RE = re.compile(r"[.!?][)\\\"'”’‖]*$")

def strip_inline_metadata(text: str) -> str:
    return INLINE_METADATA_RE.sub("", text).rstrip()

def extract_answer_labels(answer_text: str) -> list[str]:
    """
    Extract answer labels only from standalone label tokens.

    A PDF watermark such as NURSINGTB.COM must not become the spurious
    labels G, B, and C. Compact multi-answer keys such as ACE remain
    supported when the entire token is made of labels.
    """

    labels: list[str] = []

    for token in re.findall(r"[A-Z]+", answer_text.upper()):
        if re.fullmatch(r"[A-G]+", token):
            labels.extend(token)

    return labels


def split_attributed_completion_answer(
    answer_text: str,
) -> tuple[str, str]:
    """Separate a one-word completion answer from an inline attribution.

    PDF text layers sometimes flatten an answer marker, a downloader
    attribution, the answer, and the opening rationale onto one line. This
    accepts only the narrow unambiguous shape: a single-token answer followed
    by a capitalized rationale sentence. Other completion answers remain
    untouched for review rather than being guessed.
    """

    without_attribution = DOWNLOADED_BY_ATTRIBUTION_RE.sub(
        "",
        answer_text,
    ).strip()
    match = re.match(
        r"^([A-Za-z][A-Za-z'’-]*)\s+([A-Z].+)$",
        without_attribution,
    )

    if match and without_attribution != answer_text.strip():
        return match.group(1), match.group(2).strip()

    return without_attribution, ""


def recover_missing_a_choice(question: dict) -> dict:
    """
    Recover an A choice lost during PDF extraction.
    """

    if (
        question.get("question_type") == "multiple_choice"
        and question.get("correct_answers") == ["A"]
        and question.get("choices")
        and question["choices"][0]["label"] == "B"
        and "?" in question.get("stem", "")
    ):
        stem = question["stem"].strip()

        question_part, possible_answer = stem.rsplit("?", 1)

        if possible_answer.strip():
            question["stem"] = question_part.strip() + "?"
            question["choices"].insert(
                0,
                {
                    "label": "A",
                    "text": possible_answer.strip(),
                },
            )

    return question


def normalize_multiline_ordered_answers(
    lines: list[str],
) -> list[str]:
    """
    Combine ordered-response keys that appear on numbered lines.

    Example:
        ANS:
        1. D
        2. C
        3. F

    becomes:
        ANS: D C F
    """
    normalized: list[str] = []
    index = 0

    while index < len(lines):
        if not re.fullmatch(
            r"ANS:\s*",
            lines[index],
            re.IGNORECASE,
        ):
            normalized.append(lines[index])
            index += 1
            continue

        answer_labels: list[str] = []
        lookahead = index + 1

        while lookahead < len(lines):
            match = re.fullmatch(
                r"\d+\.\s*([A-H])",
                lines[lookahead],
                re.IGNORECASE,
            )

            if not match:
                break

            answer_labels.append(match.group(1).upper())
            lookahead += 1

        if len(answer_labels) >= 2:
            normalized.append(
                "ANS: " + " ".join(answer_labels)
            )
            index = lookahead
            continue

        normalized.append(lines[index])
        index += 1

    return normalized


def reorder_page_wrapped_choice_cycle(lines: list[str]) -> list[str]:
    """Restore an A–D choice cycle split around its answer key by page order.

    Some two-column PDFs emit the final choice and answer key before the first
    choices when a physical page boundary falls through the choice block.  We
    repair only a complete, unique conventional label cycle whose answer is
    one of those labels. All intervening material must be page transport
    noise; educational text is never moved or discarded.
    """
    reordered: list[str] = []
    index = 0

    def transport(value: str) -> bool:
        return not value or value == PAGE_BREAK_MARKER or bool(
            SOURCE_SHARE_FOOTER_RE.match(value)
        )

    while index < len(lines):
        first = CHOICE_RE.match(lines[index])
        if not first:
            reordered.append(lines[index])
            index += 1
            continue

        before = [lines[index]]
        cursor = index + 1
        while cursor < len(lines):
            if transport(lines[cursor]):
                cursor += 1
                continue
            choice = CHOICE_RE.match(lines[cursor])
            if choice:
                before.append(lines[cursor])
                cursor += 1
                continue
            break

        if cursor >= len(lines) or not ANSWER_RE.match(lines[cursor]):
            reordered.append(lines[index])
            index += 1
            continue
        answer_index = cursor
        answer_labels = extract_answer_labels(ANSWER_RE.match(lines[cursor]).group(1))
        cursor += 1
        after = []
        while cursor < len(lines) and transport(lines[cursor]):
            cursor += 1
        while cursor < len(lines):
            choice = CHOICE_RE.match(lines[cursor])
            if not choice:
                break
            after.append(lines[cursor])
            cursor += 1
            while cursor < len(lines) and transport(lines[cursor]):
                cursor += 1

        combined = before + after
        labels = [CHOICE_RE.match(value).group(1).upper() for value in combined]
        expected = [chr(ord("A") + offset) for offset in range(len(labels))]
        if (
            len(combined) >= 3
            and len(set(labels)) == len(labels)
            and sorted(labels) == expected
            and answer_labels
            and set(answer_labels).issubset(labels)
            and after
        ):
            by_label = {CHOICE_RE.match(value).group(1).upper(): value for value in combined}
            reordered.extend(by_label[label] for label in expected)
            reordered.append(lines[answer_index])
            index = cursor
            continue

        reordered.append(lines[index])
        index += 1

    return reordered


def remove_repeated_choice_answer_pair(lines: list[str]) -> list[str]:
    """Drop an exact duplicate choice/answer pair repeated inside a rationale.

    A few page-layout extractions repeat the last choice and answer key again
    after the first lines of rationale text.  The original pair is retained;
    this only removes a later pair when it exactly repeats both a choice and
    the answer already seen in the *same numbered question*.  It is not a
    content inference and cannot change a differing choice or answer.
    """
    cleaned: list[str] = []
    seen_choices: dict[str, str] = {}
    primary_answers: tuple[str, ...] | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        if QUESTION_RE.match(line):
            seen_choices = {}
            primary_answers = None

        choice = CHOICE_RE.match(line)
        if choice and primary_answers is not None:
            cursor = index + 1
            while cursor < len(lines) and lines[cursor] in {"", PAGE_BREAK_MARKER}:
                cursor += 1
            answer = ANSWER_RE.match(lines[cursor]) if cursor < len(lines) else None
            label = choice.group(1).upper()
            choice_text = choice.group(2).strip()
            if (
                answer
                and seen_choices.get(label) == choice_text
                and tuple(extract_answer_labels(answer.group(1))) == primary_answers
            ):
                index = cursor + 1
                continue

        if choice:
            seen_choices[choice.group(1).upper()] = choice.group(2).strip()

        answer = ANSWER_RE.match(line)
        if answer and primary_answers is None:
            primary_answers = tuple(extract_answer_labels(answer.group(1)))

        cleaned.append(line)
        index += 1

    return cleaned


def reorder_scattered_complete_choice_cycle(lines: list[str]) -> list[str]:
    """Recover a complete A–G cycle split around a page-layout interruption.

    This handles the remaining layout shape where some choices occur after the
    answer key, with repeated source prose between them.  It acts only when a
    single numbered question contains one complete, unique conventional cycle
    and one answer key, and at least one choice is physically after that key.
    The original prose stays in place; only the known choice/answer control
    lines are moved together before it.
    """
    output: list[str] = []
    index = 0
    while index < len(lines):
        if not QUESTION_RE.match(lines[index]):
            output.append(lines[index])
            index += 1
            continue

        end = index + 1
        while end < len(lines) and not QUESTION_RE.match(lines[end]):
            end += 1
        segment = lines[index:end]
        choice_entries = [
            (position, match)
            for position, value in enumerate(segment)
            if (match := CHOICE_RE.match(value))
        ]
        answer_entries = [
            (position, match)
            for position, value in enumerate(segment)
            if (match := ANSWER_RE.match(value))
        ]
        labels = [match.group(1).upper() for _, match in choice_entries]
        expected = [chr(ord("A") + offset) for offset in range(len(labels))]
        if (
            len(choice_entries) >= 3
            and len(choice_entries) == len(set(labels))
            and sorted(labels) == expected
            and len(answer_entries) == 1
            and any(position > answer_entries[0][0] for position, _ in choice_entries)
            and set(extract_answer_labels(answer_entries[0][1].group(1))).issubset(labels)
        ):
            choice_positions = {position for position, _ in choice_entries}
            answer_position = answer_entries[0][0]
            by_label = {
                match.group(1).upper(): segment[position]
                for position, match in choice_entries
            }
            insertion = min(choice_positions)
            for position, value in enumerate(segment):
                if position == insertion:
                    output.extend(by_label[label] for label in expected)
                    output.append(segment[answer_position])
                if position in choice_positions or position == answer_position:
                    continue
                output.append(value)
        else:
            output.extend(segment)
        index = end
    return output


def normalize_inline_answers(lines: list[str]) -> list[str]:
    """
    Split alternate inline answer markers into canonical ANS lines.

    Examples:
        D. Strength of urinary stream. - ANS: D
        D. Calculate by hand. Ans> D

    become:
        D. Strength of urinary stream.
        ANS: D
    """
    normalized: list[str] = []

    for line in lines:
        match = INLINE_ANSWER_RE.match(line)

        if not match:
            normalized.append(line)
            continue

        content = match.group(1).strip()
        answer = match.group(2).strip()

        if content:
            normalized.append(content)

        normalized.append(f"ANS: {answer}")

    return normalized


def normalize_labeled_question_format(
    lines: list[str],
) -> list[str]:
    """
    Normalize labeled source question formats.

    Supported labels include:
        Choices:
        A) Choice text
        Answer: A) Choice text
        Correct Answer: A. Choice text
        Rationale: Explanation
        Explanation: Explanation
        Feedback: Explanation

    Once a labeled format is detected, subsequent numbered questions are
    marked as explicit question boundaries so they cannot be absorbed into
    the preceding rationale.
    """
    normalized: list[str] = []
    labeled_format_active = False

    for line in lines:
        if CHAPTER_RE.match(line):
            labeled_format_active = False
            normalized.append(line)
            continue

        if (
            labeled_format_active
            and QUESTION_RE.match(line)
        ):
            normalized.append(f"[PREPFLOW_QUESTION] {line}")
            continue

        if line.strip().lower() == "choices:":
            labeled_format_active = True
            continue

        choice_match = PAREN_CHOICE_RE.match(line)

        if choice_match:
            labeled_format_active = True
            normalized.append(
                f"{choice_match.group(1)}. "
                f"{choice_match.group(2).strip()}"
            )
            continue

        answer_match = LONG_ANSWER_RE.match(line)

        if answer_match:
            labeled_format_active = True
            normalized.append(
                f"ANS: {answer_match.group(1).upper()}"
            )
            continue

        rationale_match = RATIONALE_PREFIX_RE.match(line)

        if rationale_match:
            labeled_format_active = True
            rationale = rationale_match.group(1).strip()

            if rationale:
                normalized.append(rationale)

            continue

        normalized.append(line)

    return normalized


def normalize_inline_question_choices(lines: list[str]) -> list[str]:
    """
    Split a first answer choice that PDF extraction placed on the stem line.

    This is limited to a numbered question ending in a question mark followed
    by a conventional choice marker. Uppercase domain-like overlay text
    between the stem and choice is discarded as page-extraction noise.
    """

    normalized: list[str] = []

    for line in lines:
        match = INLINE_FIRST_CHOICE_RE.match(line)

        if match:
            normalized.extend(
                (
                    match.group(1).strip(),
                    f"{match.group(2).upper()}. {match.group(3).strip()}",
                )
            )
            continue

        normalized.append(line)

    return normalized


def normalize_split_choices(lines: list[str]) -> list[str]:
    """
    Repair PDF extraction where choice markers are split, incomplete,
    or followed by wrapped choice text.
    """
    normalized: list[str] = []
    index = 0
    last_choice_label: str | None = None

    def append_line(line: str) -> None:
        nonlocal last_choice_label

        normalized.append(line)
        choice_match = CHOICE_RE.match(line)

        if choice_match:
            last_choice_label = choice_match.group(1).upper()
        elif (
            QUESTION_RE.match(line)
            or SYNTHETIC_QUESTION_RE.match(line)
            or ANSWER_RE.match(line)
            or CHAPTER_RE.match(line)
            or line.upper() in SECTION_HEADERS
        ):
            last_choice_label = None

    while index < len(lines):
        # Some PDF readers insert a space between a choice label and its
        # punctuation (``a . First choice``). This is still an explicit
        # conventional marker, so normalize it without interpreting prose.
        spaced_choice = re.match(r"^([a-gA-G])\s+[.)]\s+(.+)$", lines[index])
        if spaced_choice:
            append_line(
                f"{spaced_choice.group(1).upper()}. {spaced_choice.group(2).strip()}"
            )
            index += 1
            continue

        # Some copied PDF layers put the next choice label on a separate
        # line before a downloader attribution, e.g. "A. First" followed by
        # "B Downloaded by: ... . Second". Recover only the immediate
        # alphabetical successor.
        if index + 1 < len(lines):
            current_choice = CHOICE_RE.match(lines[index])
            attributed_continuation = re.match(
                r"^([a-gA-G])\s+Downloaded by:\s+.*?\.\s+(.+)$",
                lines[index + 1],
                re.IGNORECASE,
            )
            if (
                current_choice
                and attributed_continuation
                and ord(attributed_continuation.group(1).upper())
                == ord(current_choice.group(1).upper()) + 1
            ):
                append_line(lines[index])
                append_line(
                    f"{attributed_continuation.group(1).upper()}. "
                    f"{attributed_continuation.group(2).strip()}"
                )
                index += 2
                continue

        # Some copied PDF layers place a downloader attribution between a
        # choice label and its text, e.g. "A. First B Downloaded by: ... .
        # Second". Recover only an immediately following conventional label;
        # this cannot reinterpret ordinary educational prose as a choice.
        attributed_choice = re.match(
            r"^([a-gA-G])\.\s+(.+?)\s+([a-gA-G])\s+"
            r"Downloaded by:\s+.*?\.\s+(.+)$",
            lines[index],
            re.IGNORECASE,
        )
        if (
            attributed_choice
            and ord(attributed_choice.group(3).upper())
            == ord(attributed_choice.group(1).upper()) + 1
        ):
            append_line(
                f"{attributed_choice.group(1).upper()}. "
                f"{attributed_choice.group(2).strip()}"
            )
            append_line(
                f"{attributed_choice.group(3).upper()}. "
                f"{attributed_choice.group(4).strip()}"
            )
            index += 1
            continue

        # Layout extraction can keep the next choice marker on the same line
        # but insert a space before its punctuation: ``A. First B . Second``.
        # Recover only the immediate alphabetical successor.  This moves
        # existing source text into its own choice and deliberately leaves
        # answer labels unchanged.
        inline_spaced_choice = re.match(
            r"^([a-gA-G])\.\s+(.+?)\s+([a-gA-G])\s+[.)]\s+(.+)$",
            lines[index],
        )
        if (
            inline_spaced_choice
            and ord(inline_spaced_choice.group(3).upper())
            == ord(inline_spaced_choice.group(1).upper()) + 1
        ):
            append_line(
                f"{inline_spaced_choice.group(1).upper()}. "
                f"{inline_spaced_choice.group(2).strip()}"
            )
            append_line(
                f"{inline_spaced_choice.group(3).upper()}. "
                f"{inline_spaced_choice.group(4).strip()}"
            )
            index += 1
            continue

        # A PDF page boundary may fall between a bare choice label and its
        # leading period (``B`` / page break / ``. Second choice``).  Preserve
        # the physical page marker for provenance but join this one exact,
        # conventional choice shape before parsing.
        period_index = index + 1
        while period_index < len(lines) and lines[period_index] in {"", PAGE_BREAK_MARKER}:
            period_index += 1
        if (
            re.fullmatch(r"[a-gA-G]", lines[index])
            and period_index < len(lines)
            and re.match(r"^\.\s+\S", lines[period_index])
        ):
            append_line(
                f"{lines[index]}. {lines[period_index][1:].strip()}"
            )
            index = period_index + 1
            continue

        if (
            index + 2 < len(lines)
            and re.fullmatch(r"[a-gA-G]", lines[index])
            and lines[index + 1] == "."
        ):
            append_line(
                f"{lines[index]}. {lines[index + 2]}"
            )
            index += 3
            continue

        if CHOICE_MARKER_ONLY_RE.fullmatch(lines[index]):
            continuation_index = index + 1

            while (
                continuation_index < len(lines)
                and lines[continuation_index] in {"", PAGE_BREAK_MARKER}
            ):
                continuation_index += 1

            if continuation_index < len(lines):
                continuation = lines[continuation_index]
                starts_structural_boundary = bool(
                    CHOICE_RE.match(continuation)
                    or CHOICE_MARKER_ONLY_RE.fullmatch(continuation)
                    or QUESTION_RE.match(continuation)
                    or SYNTHETIC_QUESTION_RE.match(continuation)
                    or ANSWER_RE.match(continuation)
                    or CHAPTER_RE.match(continuation)
                    or continuation.upper() in SECTION_HEADERS
                )

                if not starts_structural_boundary:
                    append_line(
                        f"{lines[index]} {continuation}"
                    )
                    index = continuation_index + 1
                    continue

        # OCR can also drop punctuation and spacing from a numeric first
        # choice. Recover only a lowercase a plus a numeric payload when the
        # next significant line is the conventional B choice.
        missing_numeric_a = re.match(
            r"^a\s*(\d+(?:[.,]\d+)?)$",
            lines[index],
        )
        next_index = index + 1
        while (
            next_index < len(lines)
            and lines[next_index] in {"", PAGE_BREAK_MARKER}
        ):
            next_index += 1
        next_choice = (
            CHOICE_RE.match(lines[next_index])
            if next_index < len(lines)
            else None
        )

        if (
            missing_numeric_a
            and last_choice_label is None
            and next_choice
            and next_choice.group(1).upper() == "B"
        ):
            append_line(f"A. {missing_numeric_a.group(1)}")
            index += 1
            continue

        # OCR can confuse a lowercase c choice marker with a cent or
        # copyright sign. Recover it only inside the unambiguous B-C-D
        # sequence; standalone currency and copyright text remain untouched.
        ocr_c_choice = OCR_C_CHOICE_RE.match(lines[index])
        following_index = index + 1
        while (
            following_index < len(lines)
            and lines[following_index] in {"", PAGE_BREAK_MARKER}
        ):
            following_index += 1
        following_choice = (
            CHOICE_RE.match(lines[following_index])
            if following_index < len(lines)
            else None
        )

        if (
            ocr_c_choice
            and last_choice_label == "B"
            and following_choice
            and following_choice.group(1).upper() == "D"
        ):
            append_line(f"C. {ocr_c_choice.group(1).strip()}")
            index += 1
            continue

        missing_period_match = re.match(
            r"^([a-gA-G])\s+(.+)$",
            lines[index],
        )

        if missing_period_match and last_choice_label:
            current_label = missing_period_match.group(1).upper()

            if ord(current_label) == ord(last_choice_label) + 1:
                append_line(
                    f"{current_label}. "
                    f"{missing_period_match.group(2).strip()}"
                )
                index += 1
                continue

        append_line(lines[index])
        index += 1

    return normalized

def number_unnumbered_questions(lines: list[str]) -> list[str]:
    """
    Add synthetic numbers to alternate-format questions that omit them.

    Each ANS line closes a source-question block. For blocks without an
    existing numbered question, locate the start of the stem and prefix it
    with a synthetic number.
    """
    normalized = list(lines)
    chapter_start = None
    previous_answer = None
    synthetic_number = 1

    def is_source_header(line: str) -> bool:
        lowered = line.lower()

        return (
            "understanding pharmacology:" in lowered
            or lowered.startswith("linda workman:")
            or lowered.startswith("workman &")
            or lowered.startswith("unit ")
            or lowered == "extra per year?"
        )

    for index, line in enumerate(lines):
        if CHAPTER_RE.match(line):
            chapter_start = index
            previous_answer = None
            synthetic_number = 1
            continue

        # A sharing URL printed at the foot of an extracted page is transport
        # metadata, never a choice continuation or educational content.
        if SOURCE_SHARE_FOOTER_RE.match(line):
            continue

        if line == PAGE_BREAK_MARKER:
            # Preserve the answer-block scan across pages: a question can
            # start before the break and finish with choices or its key after
            # it. The marker itself is excluded from every candidate block.
            continue

        if chapter_start is None or not ANSWER_RE.match(line):
            continue

        block_start = (
            previous_answer + 1
            if previous_answer is not None
            else chapter_start + 1
        )
        block = lines[block_start:index]

        previous_answer = index

        if not block:
            continue

        if any(
            QUESTION_RE.match(candidate)
            or SYNTHETIC_QUESTION_RE.match(candidate)
            for candidate in block
        ):
            continue

        # Do not synthesize a question from a bare page break, a trailing
        # rationale, or a second answer key. A genuine unnumbered block has
        # either its first choice, a question cue, or a completion blank.
        has_choice_a = any(
            re.match(r"^A\.\s+", candidate, re.IGNORECASE)
            for candidate in block
        )
        has_question_cue = any(
            re.match(
                r"^(?:what|which|when|where|who|why|how)\b",
                candidate.strip(),
                re.IGNORECASE,
            )
            for candidate in block
        )
        has_completion_blank = any("_____" in candidate for candidate in block)
        if not (has_choice_a or has_question_cue or has_completion_blank):
            continue

        choice_a_offset = next(
            (
                offset
                for offset, candidate in enumerate(block)
                if re.match(r"^A\.\s+", candidate, re.IGNORECASE)
            ),
            None,
        )

        if choice_a_offset is not None:
            stem_end = block_start + choice_a_offset - 1
        else:
            stem_end = index - 1

        while (
            stem_end >= block_start
            and (
                not lines[stem_end]
                or lines[stem_end] == PAGE_BREAK_MARKER
                or is_source_header(lines[stem_end])
                or lines[stem_end].upper() in SECTION_HEADERS
            )
        ):
            stem_end -= 1

        if stem_end < block_start:
            continue

        stem_start = block_start

        # The block may begin with the prior question's rationale. The last
        # complete declarative sentence before the new stem is its boundary.
        for candidate_index in range(block_start, stem_end):
            candidate = lines[candidate_index].strip()

            if candidate.endswith((".", "!")):
                stem_start = candidate_index + 1

        while (
            stem_start <= stem_end
            and (
                not lines[stem_start]
                or lines[stem_start] == PAGE_BREAK_MARKER
                or is_source_header(lines[stem_start])
                or lines[stem_start].upper() in SECTION_HEADERS
            )
        ):
            stem_start += 1

        question_cues = [
            candidate_index
            for candidate_index in range(block_start, stem_end + 1)
            if re.match(
                r"^(?:what|which|when|where|who|why|how)\b",
                lines[candidate_index].strip(),
                re.IGNORECASE,
            )
        ]

        if question_cues:
            stem_start = question_cues[-1]

            if stem_start > block_start:
                setup_line = lines[stem_start - 1].strip()

                if re.match(
                    r"^(?:a|an|the)\s+"
                    r"(?:patient|client|man|woman|child|infant|"
                    r"couple|nurse)\b",
                    setup_line,
                    re.IGNORECASE,
                ):
                    stem_start -= 1

        if stem_start > stem_end:
            continue

        normalized[stem_start] = (
            f"[PREPFLOW_QUESTION] {synthetic_number}. "
            f"{normalized[stem_start]}"
        )
        synthetic_number += 1

    return normalized

def parse_source_questions(
    text: str,
    *,
    allow_missing_a_recovery: bool = True,
) -> list[dict]:
    def finalize(candidate: dict) -> dict:
        if allow_missing_a_recovery:
            return recover_missing_a_choice(candidate)
        return candidate

    # Preserve PDF page boundaries as a signal for later parsing. A boundary
    # is not itself a question boundary: choices and answer keys can continue
    # onto the following page.
    source_with_page_markers = text.replace(
        "\f", f"\n{PAGE_BREAK_MARKER}\n"
    )
    lines = [line.strip() for line in source_with_page_markers.splitlines()]
    lines = normalize_labeled_question_format(lines)
    lines = normalize_inline_question_choices(lines)
    lines = normalize_split_choices(lines)
    lines = normalize_inline_answers(lines)
    lines = normalize_multiline_ordered_answers(lines)
    lines = reorder_page_wrapped_choice_cycle(lines)
    lines = number_unnumbered_questions(lines)
    lines = remove_repeated_choice_answer_pair(lines)
    lines = reorder_scattered_complete_choice_cycle(lines)

    # Join chapter headings that were wrapped across PDF-extracted lines.
    joined_lines: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if CHAPTER_RE.match(line) and index + 1 < len(lines):
            continuation_index = index + 1

            while (
                continuation_index < len(lines)
                and lines[continuation_index] in {"", PAGE_BREAK_MARKER}
            ):
                continuation_index += 1

            continuation = (
                lines[continuation_index]
                if continuation_index < len(lines)
                else ""
            )
            continuation_is_content = bool(
                continuation
                and continuation.upper() not in SECTION_HEADERS
                and not QUESTION_RE.match(continuation)
                and not CHOICE_RE.match(continuation)
                and not ANSWER_RE.match(continuation)
                and not METADATA_RE.match(continuation)
            )
            heading_requires_continuation = bool(
                re.search(
                    r"(?:,|\band|\bor)\s*$",
                    line,
                    re.IGNORECASE,
                )
            )
            title_shaped_continuation = bool(
                re.fullmatch(
                    r"[A-Z][a-z'’‘-]*(?:\s+(?:and|of|or|the|with|in|for|to|"
                    r"[A-Z][a-z'’‘-]*)){0,7}",
                    continuation,
                )
            )
            publisher_context_follows = any(
                "edition" in candidate.casefold()
                or "test bank" in candidate.casefold()
                for candidate in lines[
                    continuation_index + 1:continuation_index + 5
                ]
            )

            if (
                continuation_is_content
                and (
                    heading_requires_continuation
                    or (
                        title_shaped_continuation
                        and publisher_context_follows
                    )
                )
            ):
                joined_lines.append(f"{line} {continuation}")
                index = continuation_index + 1
                continue

        joined_lines.append(line)
        index += 1

    lines = joined_lines

    chapter = None
    section = None
    question = None
    questions: list[dict] = []
    reading_rationale = False
    metadata_started = False
    awaiting_completion_answer = False
    page_break_after_complete_choice = False

    for line in lines:
        if not line:
            continue

        # A sharing URL printed at the foot of an extracted page is transport
        # metadata, never a choice continuation or educational content.
        if SOURCE_SHARE_FOOTER_RE.match(line):
            continue

        if line == PAGE_BREAK_MARKER:
            page_break_after_complete_choice = bool(
                question
                and question["choices"]
                and not reading_rationale
                and not metadata_started
                and CHOICE_SENTENCE_END_RE.search(question["choices"][-1]["text"])
            )
            continue

        # Repeated page titles, one-letter overlay fragments, and all-caps
        # domains can occur before a choice continuation. They are transport
        # artifacts, so retain the page-boundary decision until real content.
        if page_break_after_complete_choice and PAGE_ARTIFACT_RE.match(line):
            continue

        # A paragraph that begins on a new page after a complete final choice
        # is rationale, not a continuation of that choice. Keep the signal
        # narrow: explicit choice, answer, metadata, and question boundaries
        # still retain their ordinary meanings.
        if (
            page_break_after_complete_choice
            and question is not None
            and not CHOICE_RE.match(line)
            and not ANSWER_RE.match(line)
            and not QUESTION_RE.match(line)
            and not SYNTHETIC_QUESTION_RE.match(line)
            and not METADATA_RE.match(line)
        ):
            reading_rationale = True
        page_break_after_complete_choice = False

        if CHAPTER_RE.match(line):
            # A new chapter is a hard question boundary. Finalize the
            # previous question before processing any wrapped chapter-title
            # or publisher-header lines that follow.
            if question is not None:
                questions.append(finalize(question))
                question = None

            # A table of contents can look like numbered questions before the
            # first chapter. Discard only a multi-entry preamble when every
            # candidate lacks both choices and an answer; preserve any
            # structurally complete chapterless records for source review.
            if (
                chapter is None
                and len(questions) >= 3
                and all(
                    candidate["chapter"] is None
                    and not candidate["choices"]
                    and not candidate["correct_answers"]
                    for candidate in questions
                )
            ):
                questions.clear()

            chapter = line
            section = None
            reading_rationale = False
            metadata_started = False
            awaiting_completion_answer = False
            continue

        # Some PDF chapter headings continue onto the next line before
        # publisher/source metadata begins, for example:
        # "Introduction Linton: Medical-Surgical Nursing, 8th Edition".
        # Preserve only the legitimate title prefix.
        if (
            chapter is not None
            and question is None
            and "linton:" in line.lower()
        ):
            # A line beginning with Linton is publisher metadata only.
            # A prefix before Linton may be a legitimate wrapped title,
            # such as "Introduction".
            continuation = re.split(
                r"(?i)\s*Linton:",
                line,
                maxsplit=1,
            )[0].strip()

            if continuation:
                chapter = f"{chapter} {continuation}"

            continue

        if line.upper() in SECTION_HEADERS:
            section = line.upper()
            continue

        synthetic_question_match = SYNTHETIC_QUESTION_RE.match(line)
        question_match = synthetic_question_match or QUESTION_RE.match(line)

        # Wrapped stems can begin with clock times such as "0700.".
        # A leading-zero number inside an unfinished question is content,
        # not a new source-question boundary.
        if (
            question_match
            and question is not None
            and not question["choices"]
            and not question["correct_answers"]
            and question_match.group(1).startswith("0")
        ):
            question["stem"] += " " + strip_inline_metadata(line)
            question["stem"] = question["stem"].rstrip()
            continue

        if question_match and (
            synthetic_question_match
            or not reading_rationale
            or metadata_started
        ):
            if question is not None:
                questions.append(finalize(question))

            question = {
                "chapter": chapter,
                "section": section,
                "source_question_number": int(question_match.group(1)),
                "question_type": {
                    "MULTIPLE CHOICE": "multiple_choice",
                    "MULTIPLE RESPONSE": "multiple_response",
                    "COMPLETION": "completion",
                    "ORDERING": "ordered_response",
                }.get(section, "multiple_choice"),
                "stem": strip_inline_metadata(
                    question_match.group(2).strip()
                ),
                "choices": [],
                "correct_answers": [],
                "rationale": "",
            }
            reading_rationale = False
            metadata_started = False
            awaiting_completion_answer = False
            continue

        if question is None:
            continue

        choice_match = CHOICE_RE.match(line)
        if choice_match and not reading_rationale:
            question["choices"].append(
                {
                    "label": choice_match.group(1).upper(),
                    "text": choice_match.group(2).strip(),
                }
            )
            continue

        if METADATA_RE.match(line):
            reading_rationale = False
            metadata_started = True
            continue

        if awaiting_completion_answer:
            if question["question_type"] == "ordered_response":
                question["correct_answers"] = re.findall(
                    r"[A-G]",
                    line.upper(),
                )
            else:
                question["correct_answers"] = [line]

            awaiting_completion_answer = False
            reading_rationale = True
            continue

        answer_match = ANSWER_RE.match(line)
        if answer_match:
            answer_text = answer_match.group(1).strip()

            if (
                question["question_type"] == "multiple_choice"
                and not question["choices"]
                and (
                    "_____" in question["stem"]
                    or (
                        answer_text
                        and not re.fullmatch(
                            r"[A-G](?:\s*,?\s*[A-G])*",
                            answer_text,
                            re.IGNORECASE,
                        )
                    )
                )
            ):
                question["question_type"] = "completion"

            sequence_language = any(
                phrase in question["stem"].lower()
                for phrase in (
                    "appropriate sequence",
                    "correct order",
                    "prioritize the steps",
                    "prioritize these",
                    "place the events",
                    "place the options",
                )
            )

            if (
                question["question_type"] == "completion"
                and question["choices"]
                and sequence_language
            ):
                question["question_type"] = "ordered_response"

                if answer_text:
                    question["correct_answers"] = extract_answer_labels(answer_text)
                    reading_rationale = True
                else:
                    awaiting_completion_answer = True

                continue

            if question["question_type"] == "completion":
                if answer_text:
                    completion_answer, inline_rationale = (
                        split_attributed_completion_answer(answer_text)
                    )
                    question["correct_answers"] = [completion_answer]
                    question["rationale"] = inline_rationale
                    reading_rationale = True
                else:
                    awaiting_completion_answer = True
                continue

            question["correct_answers"] = extract_answer_labels(answer_text)
            reading_rationale = True
            continue

        if not question["choices"] and not reading_rationale:
            question["stem"] += " " + strip_inline_metadata(line)
            question["stem"] = question["stem"].rstrip()
            continue

        if metadata_started:
            # Ignore short standalone extraction artifacts such as
            # "U S N T O", but allow educational rationale text that
            # appears after source metadata.
            if not re.search(r"[a-z]", line) and len(line) < 30:
                continue

            if question["correct_answers"]:
                reading_rationale = True
            else:
                continue

        if question["choices"] and not reading_rationale:
            question["choices"][-1]["text"] += " " + line
            continue

        if reading_rationale:
            contained_inline_metadata = bool(INLINE_METADATA_RE.search(line))

            if question["rationale"]:
                question["rationale"] += " "
            question["rationale"] += strip_inline_metadata(line)
            question["rationale"] = question["rationale"].rstrip()

            if contained_inline_metadata:
                metadata_started = True

    if question is not None:
        questions.append(finalize(question))

    return questions
