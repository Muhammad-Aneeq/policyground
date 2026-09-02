"""Section-aware chunking (spec 08 §4 F2: "chunk (section-aware) … with metadata").

Two properties drive every decision here:

1. **A chunk should be a citable unit.** An accountant asked "where does it say that?" expects
   "PG-0003 §2", not "chunk 47". So the primary boundary is the authored section, and the section
   path travels with the chunk into the citation.

2. **Offsets must survive.** Every chunk records ``start``/``end`` into the policy's raw markdown,
   and the invariant ``raw[start:end] == chunk.text`` is asserted in the tests. That is what lets
   the Source Viewer highlight the exact passage rather than re-finding it by string match
   (PLAN.md **D-017**).

Long sections are split, but only on paragraph boundaries, and each piece carries a heading
breadcrumb so a mid-section chunk still reads as belonging to its section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from policyground.corpus.models import PolicyDoc, Section
from policyground.retrieval.base import Chunk

#: Soft cap. Sections under this become exactly one chunk, which is the common case: the authored
#: sections in this corpus average well under it, so most chunks are whole sections.
MAX_CHUNK_CHARS = 1400
#: A trailing fragment shorter than this is merged back into the previous piece rather than
#: standing alone. A 60-character chunk retrieves badly and cites worse.
MIN_CHUNK_CHARS = 220

_PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True, slots=True)
class ChunkingStats:
    """Reported by ingestion so a corpus edit's effect on the index is visible, not guessed."""

    policies: int
    sections: int
    chunks: int
    split_sections: int
    max_chars: int

    def render(self) -> str:
        return (
            f"{self.chunks} chunks from {self.sections} sections across {self.policies} policies "
            f"({self.split_sections} split; longest chunk {self.max_chars} chars)"
        )


def _split_points(text: str) -> list[int]:
    """Offsets (relative to ``text``) where a split may occur: after a blank line."""
    return [match.end() for match in _PARAGRAPH_BREAK_RE.finditer(text)]


def _split_section_text(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Split into ``(start, end)`` spans on paragraph boundaries, greedily filling to ``max_chars``.

    Returns spans relative to ``text``. The spans tile the input exactly — no gaps, no overlap —
    so summing their lengths reproduces the original, and no authored sentence is dropped or
    indexed twice.

    A paragraph longer than ``max_chars`` on its own is *not* hard-split mid-sentence: it is
    emitted whole. An oversized chunk retrieves slightly worse; a chunk cut mid-sentence cites
    something that reads as a mistake, and the citation is the product.
    """
    if len(text) <= max_chars:
        return [(0, len(text))]

    boundaries = _split_points(text)
    if not boundaries:
        return [(0, len(text))]

    spans: list[tuple[int, int]] = []
    start = 0
    last_usable = start

    for boundary in boundaries:
        if boundary - start <= max_chars:
            last_usable = boundary
            continue
        # This boundary overshoots. Close the chunk at the last boundary that fit.
        if last_usable > start:
            spans.append((start, last_usable))
            start = last_usable
            last_usable = boundary if boundary - start <= max_chars else start
        else:
            # A single paragraph exceeds the cap; emit it whole rather than cutting a sentence.
            spans.append((start, boundary))
            start = boundary
            last_usable = start

    if start < len(text):
        spans.append((start, len(text)))

    # Merge a runt tail into its predecessor.
    if len(spans) >= 2 and (spans[-1][1] - spans[-1][0]) < MIN_CHUNK_CHARS:
        prev_start, _ = spans[-2]
        _, last_end = spans[-1]
        spans = [*spans[:-2], (prev_start, last_end)]

    return spans


def chunk_section(
    doc: PolicyDoc,
    section: Section,
    *,
    ordinal_start: int,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[Chunk]:
    """Turn one section into one or more chunks, preserving absolute offsets."""
    spans = _split_section_text(section.text, max_chars)
    chunks: list[Chunk] = []

    for piece_index, (rel_start, rel_end) in enumerate(spans):
        abs_start = section.start + rel_start
        abs_end = section.start + rel_end
        ordinal = ordinal_start + piece_index

        # The chunk id is derived from content location, never from a global counter, so it is
        # stable across rebuilds and across corpus edits elsewhere in the manual.
        suffix = f"#{piece_index}" if len(spans) > 1 else ""
        chunk_id = f"{doc.policy_id}::{ordinal:03d}{suffix}"

        section_path = section.path_str
        if len(spans) > 1:
            section_path = f"{section_path} (part {piece_index + 1} of {len(spans)})"

        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                policy_id=doc.policy_id,
                policy_title=doc.title,
                section_path=section_path,
                label=doc.label,
                version=doc.front_matter.version,
                text=doc.raw[abs_start:abs_end],
                start=abs_start,
                end=abs_end,
                ordinal=ordinal,
            )
        )

    return chunks


def chunk_policy(doc: PolicyDoc, *, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """All chunks for one policy, in document order.

    Sections whose text is only a heading and whitespace are skipped: a heading with no body
    contributes nothing retrievable and would dilute the index with an unciteable chunk.
    """
    chunks: list[Chunk] = []
    ordinal = 0

    for section in doc.sections:
        body_after_heading = section.text
        if section.level > 0:
            # Drop the heading line itself when testing for emptiness, but keep it in the chunk
            # text: the heading is often the most retrievable phrase in the section.
            newline = body_after_heading.find("\n")
            body_after_heading = body_after_heading[newline + 1 :] if newline != -1 else ""
        if not body_after_heading.strip():
            continue

        produced = chunk_section(doc, section, ordinal_start=ordinal, max_chars=max_chars)
        chunks.extend(produced)
        ordinal += len(produced)

    return chunks


def chunk_corpus(
    docs: list[PolicyDoc], *, max_chars: int = MAX_CHUNK_CHARS
) -> tuple[list[Chunk], ChunkingStats]:
    """Chunk every policy, returning chunks in stable order plus reportable statistics."""
    all_chunks: list[Chunk] = []
    sections = 0
    split_sections = 0

    for doc in docs:
        for section in doc.sections:
            sections += 1
            if len(section.text) > max_chars and len(_split_points(section.text)) > 0:
                split_sections += 1
        all_chunks.extend(chunk_policy(doc, max_chars=max_chars))

    stats = ChunkingStats(
        policies=len(docs),
        sections=sections,
        chunks=len(all_chunks),
        split_sections=split_sections,
        max_chars=max((len(c.text) for c in all_chunks), default=0),
    )
    return all_chunks, stats
