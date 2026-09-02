"""Read authored policies from disk into :class:`PolicyDoc`, preserving exact character offsets.

Front-matter is parsed here rather than with ``python-frontmatter`` (PLAN.md **D-020**). The
library returns the body as a *new string*, which loses the mapping back into the file the API
serves — and that mapping is exactly what the Source Viewer's highlight depends on. Fifteen lines
of parsing buys an invariant the tests can assert: for every section, ``raw[start:end] ==
section.text``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import yaml

from policyground.corpus.models import PolicyDoc, PolicyFrontMatter, Section

_FENCE = "---"
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


class CorpusError(RuntimeError):
    """A policy file could not be read or does not meet the authoring contract."""


def split_front_matter(raw: str, *, source: str) -> tuple[dict[str, object], int]:
    """Return ``(front_matter_mapping, body_start_offset)``.

    ``body_start_offset`` is an index into ``raw``, so slicing ``raw`` with section offsets and
    slicing the body with the same offsets agree. Every other component in the system depends on
    that agreement holding.
    """
    if not raw.startswith(_FENCE):
        raise CorpusError(f"{source}: file must open with a '---' front-matter fence")

    # Find the closing fence: the first line that is exactly '---' after the opening one.
    match = re.search(r"^---[ \t]*$", raw[len(_FENCE) :], re.MULTILINE)
    if match is None:
        raise CorpusError(f"{source}: front-matter block is not closed with '---'")

    fm_text = raw[len(_FENCE) : len(_FENCE) + match.start()]
    body_start = len(_FENCE) + match.end()

    # Skip the newline(s) immediately after the closing fence so offsets start at real content.
    while body_start < len(raw) and raw[body_start] in "\r\n":
        body_start += 1

    try:
        parsed = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise CorpusError(f"{source}: front-matter is not valid YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise CorpusError(f"{source}: front-matter must be a mapping, got {type(parsed).__name__}")

    return parsed, body_start


def parse_sections(raw: str, body_start: int) -> list[Section]:
    """Split the body into sections at markdown headings, tracking the heading trail.

    A section runs from its heading to the next heading *of any level*. Nesting is captured in
    ``path`` rather than by making a parent section contain its children: a citation should point
    at the smallest unit that answers the question, and duplicated parent text would let the same
    sentence be retrieved twice at different granularities.

    Content appearing before the first heading (rare, but a preamble is legal markdown) is
    attached to a synthetic "Preamble" section so no authored text is silently unindexable.
    """
    body = raw[body_start:]
    matches = list(_HEADING_RE.finditer(body))
    sections: list[Section] = []

    if not matches:
        text = body.strip()
        if text:
            sections.append(
                Section(
                    level=1,
                    heading="Preamble",
                    path=("Preamble",),
                    text=body,
                    start=body_start,
                    end=body_start + len(body),
                )
            )
        return sections

    if body[: matches[0].start()].strip():
        preamble_end = body_start + matches[0].start()
        sections.append(
            Section(
                level=1,
                heading="Preamble",
                path=("Preamble",),
                text=raw[body_start:preamble_end],
                start=body_start,
                end=preamble_end,
            )
        )

    # trail[level] holds the most recent heading seen at that level, so `path` for a level-3
    # heading is (level-1 heading, level-2 heading, this one) with gaps skipped.
    trail: dict[int, str] = {}

    for index, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()

        trail[level] = heading
        for deeper in [lvl for lvl in trail if lvl > level]:
            del trail[deeper]

        start = body_start + match.start()
        end = body_start + (matches[index + 1].start() if index + 1 < len(matches) else len(body))
        path = tuple(trail[lvl] for lvl in sorted(trail))

        sections.append(
            Section(
                level=level,
                heading=heading,
                path=path,
                text=raw[start:end],
                start=start,
                end=end,
            )
        )

    return sections


def load_policy(path: Path) -> PolicyDoc:
    """Parse one policy file, validating its header against :class:`PolicyFrontMatter`."""
    raw = path.read_text(encoding="utf-8")
    mapping, body_start = split_front_matter(raw, source=path.name)

    try:
        front_matter = PolicyFrontMatter.model_validate(mapping)
    except Exception as exc:
        raise CorpusError(f"{path.name}: invalid front-matter: {exc}") from exc

    # The filename carries the policy id so that a file can be located from a citation without a
    # lookup, and so a copy-paste error that duplicates an id is visible in a directory listing.
    if not path.name.startswith(front_matter.policy_id):
        raise CorpusError(
            f"{path.name}: filename must start with its policy_id {front_matter.policy_id!r}"
        )

    sections = parse_sections(raw, body_start)
    return PolicyDoc(
        front_matter=front_matter,
        raw=raw,
        body_start=body_start,
        sections=sections,
        source_path=path.name,
    )


def iter_policy_paths(policies_dir: Path) -> Iterator[Path]:
    """Markdown files in the corpus, in stable policy-id order."""
    yield from sorted(policies_dir.glob("PG-*.md"))


def load_corpus(policies_dir: Path) -> list[PolicyDoc]:
    """Load every policy, failing loudly on a duplicate id.

    Returned in policy-id order so that ingestion, the manifest and every test see the same
    sequence on every run — determinism the index rebuild depends on.
    """
    paths = list(iter_policy_paths(policies_dir))
    if not paths:
        raise CorpusError(f"no policy files found in {policies_dir}")

    docs = [load_policy(path) for path in paths]

    seen: dict[str, str] = {}
    for doc in docs:
        if doc.policy_id in seen:
            raise CorpusError(
                f"duplicate policy_id {doc.policy_id}: {seen[doc.policy_id]} and {doc.source_path}"
            )
        seen[doc.policy_id] = doc.source_path

    return docs
