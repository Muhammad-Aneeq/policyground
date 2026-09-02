"""Typed representations of an authored policy and its sections.

Every field a policy header may carry is declared here with ``extra="forbid"``. A misspelled
front-matter key is then a loud validation error at ingest time rather than a silently ignored
attribute — which matters most for ``label``, where a typo would default a restricted document
into a permissive state if the model were lenient.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from policyground.labels import Label

POLICY_ID_RE = re.compile(r"^PG-\d{4}$")


class PolicyFrontMatter(BaseModel):
    """The YAML block at the top of every ``corpus/policies/*.md`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: Annotated[str, Field(pattern=r"^PG-\d{4}$")]
    title: str = Field(min_length=4)
    label: Label
    version: str
    owner: str = Field(min_length=3)
    effective_date: dt.date
    supersedes: str | None = None
    category: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("version", "supersedes")
    @classmethod
    def _version_is_quoted_string(cls, value: str | None) -> str | None:
        """Reject an unquoted YAML version like ``3.10``, which parses as the float 3.1.

        This is not pedantry: ``version: 3.10`` and ``version: 3.1`` are indistinguishable after
        YAML parsing, so a policy could appear to regress a version on re-ingest. Requiring the
        quoted form in the source file makes the ambiguity impossible.
        """
        if value is None:
            return None
        if not re.fullmatch(r"\d+\.\d+", value):
            raise ValueError(f"version must be a quoted 'major.minor' string, got {value!r}")
        return value


class Section:
    """One heading and the body beneath it, with exact offsets into the raw file.

    The offsets are the reason this is not a plain string. Highlighting a cited passage in the
    Source Viewer (spec 08 §9 screen 2) by re-matching text is fragile — the same sentence can
    appear twice, and markdown rendering changes whitespace. Offsets into the exact bytes the API
    serves are not (PLAN.md **D-017**).

    ``path`` is the heading trail ("3. Approval matrix" nested under a top-level title), which is
    what a citation should read like to an accountant: a section reference, not a chunk number.
    """

    __slots__ = ("end", "heading", "level", "path", "start", "text")

    def __init__(
        self,
        *,
        level: int,
        heading: str,
        path: tuple[str, ...],
        text: str,
        start: int,
        end: int,
    ) -> None:
        self.level = level
        self.heading = heading
        self.path = path
        self.text = text
        self.start = start
        self.end = end

    @property
    def path_str(self) -> str:
        return " > ".join(self.path)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Section {self.path_str!r} [{self.start}:{self.end}]>"


class PolicyDoc:
    """A parsed policy: validated header, raw source, and its section tree."""

    __slots__ = ("body_start", "front_matter", "raw", "sections", "source_path")

    def __init__(
        self,
        *,
        front_matter: PolicyFrontMatter,
        raw: str,
        body_start: int,
        sections: list[Section],
        source_path: str,
    ) -> None:
        self.front_matter = front_matter
        self.raw = raw
        self.body_start = body_start
        self.sections = sections
        self.source_path = source_path

    @property
    def policy_id(self) -> str:
        return self.front_matter.policy_id

    @property
    def title(self) -> str:
        return self.front_matter.title

    @property
    def label(self) -> Label:
        return self.front_matter.label

    @property
    def body(self) -> str:
        """Everything after the front-matter block — what gets chunked and searched."""
        return self.raw[self.body_start :]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PolicyDoc {self.policy_id} {self.label} sections={len(self.sections)}>"
