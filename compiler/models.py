from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Answer:
    """
    Represents the correct answer for a Question.
    """

    type: str
    value: object

@dataclass
class Organization:
    """Stores source-neutral placement within a PrepFlow Pack."""

    chapter: object = ""
    chapter_title: str = ""
    question_number: object = ""


@dataclass
class Content:
    """
    Contains the learner-facing parts of a Question.
    """

    stem: str
    choices: list[dict[str, str]]
    rationale: str = ""

@dataclass
class Classification:
    """
    Describes how a Question can be grouped for study and analytics.
    """

    concepts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    body_system: Optional[str] = None
    difficulty: Optional[str] = None
    bloom_level: Optional[str] = None


@dataclass
class Metadata:
    """
    Stores developer-facing information about a Question.
    """

    created: str = ""
    compiler_version: str = ""
    validated: bool = False
    notes: list[str] = field(default_factory=list)

@dataclass
class Question:
    """
    The canonical PrepFlow question object.

    Every supported source format is eventually compiled into this structure.
    """

    id: str
    version: int
    organization: Organization
    content: Content
    answer: Answer
    classification: Classification = field(default_factory=Classification)
    metadata: Metadata = field(default_factory=Metadata)

@dataclass
class Pack:
    """
    A collection of Questions and the metadata that describes them.
    """

    id: str
    title: str
    version: str
    schema_version: str
    created: str
    questions: list[Question] = field(default_factory=list)
