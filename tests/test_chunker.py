"""Section-aware chunking preserves citability and exact offsets.

Spec 08 §4 F2: *"chunk (section-aware) … with metadata (policy_id, section, label)."*

The offset invariant (``raw[start:end] == chunk.text``) gets the most attention here because it is
silent when it breaks: a wrong offset still highlights *something*, and the Source Viewer looks
like it is working while pointing at the wrong passage.
"""

from __future__ import annotations

import itertools
import re

from policyground.corpus.chunker import (
    MAX_CHUNK_CHARS,
    _split_section_text,
    chunk_corpus,
    chunk_policy,
)
from policyground.corpus.models import PolicyDoc
from policyground.labels import Label
from policyground.retrieval.base import Chunk


def test_every_chunk_offset_round_trips(corpus: list[PolicyDoc]) -> None:
    """THE invariant. If this fails, every highlight in the UI is quietly wrong."""
    for doc in corpus:
        for chunk in chunk_policy(doc):
            assert doc.raw[chunk.start : chunk.end] == chunk.text, (
                f"{chunk.chunk_id} offsets do not reproduce its text"
            )


def test_chunks_carry_complete_metadata(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        assert chunk.policy_id
        assert chunk.policy_title
        assert chunk.section_path
        assert isinstance(chunk.label, Label)
        assert chunk.version
        assert chunk.text.strip()
        assert chunk.end > chunk.start


def test_chunk_ids_are_unique(chunks: list[Chunk]) -> None:
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(set(ids)) == len(ids)


def test_chunk_ids_are_stable_across_rebuilds(corpus: list[PolicyDoc]) -> None:
    """Derived from location, never a global counter.

    A counter-based id would change for every chunk whenever a policy is inserted, invalidating
    stored citations in the ``answers`` table and every cached judge verdict.
    """
    first = [c.chunk_id for c in chunk_corpus(corpus)[0]]
    second = [c.chunk_id for c in chunk_corpus(corpus)[0]]
    assert first == second
    assert all(cid.startswith("PG-") and "::" in cid for cid in first)


def test_no_chunk_spans_two_policies(chunks: list[Chunk]) -> None:
    """Each chunk belongs to exactly one policy — a citation cannot straddle two documents."""
    for chunk in chunks:
        assert chunk.chunk_id.startswith(chunk.policy_id)


def test_a_chunk_inherits_its_policy_label(corpus: list[PolicyDoc]) -> None:
    """The label travels with the chunk. Everything about governance depends on this."""
    for doc in corpus:
        for chunk in chunk_policy(doc):
            assert chunk.label is doc.label


def test_chunks_are_not_empty_or_heading_only(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        without_heading = chunk.text.split("\n", 1)[-1] if "\n" in chunk.text else ""
        assert without_heading.strip(), f"{chunk.chunk_id} is a heading with no body"


def test_chunks_of_one_policy_tile_it_without_overlap(corpus: list[PolicyDoc]) -> None:
    """Chunks may skip empty sections, but they must never overlap — no double-indexed text."""
    for doc in corpus:
        spans = sorted((c.start, c.end) for c in chunk_policy(doc))
        for (_, first_end), (second_start, _) in itertools.pairwise(spans):
            assert first_end <= second_start, f"{doc.policy_id} has overlapping chunks"


def test_section_path_is_carried_into_the_citation(chunks: list[Chunk]) -> None:
    """The citation reads like a policy reference, not a chunk number."""
    sample = next(c for c in chunks if c.policy_id == "PG-0007")
    assert sample.citation_label.startswith("PG-0007 - ")


def test_long_sections_split_on_paragraph_boundaries() -> None:
    """A split must land at a blank line, never mid-sentence."""
    paragraph = "This is a sentence that runs on for a while and carries meaning. " * 6
    text = "\n\n".join([paragraph] * 5)

    spans = _split_section_text(text, max_chars=600)
    assert len(spans) > 1, "fixture should be long enough to require splitting"

    # Every boundary except the final one must coincide with a paragraph break in the source.
    paragraph_breaks = {match.end() for match in re.finditer(r"\n[ \t]*\n", text)}
    for _, end in spans[:-1]:
        assert end in paragraph_breaks, f"split at {end} is not on a paragraph boundary"

    for start, end in spans:
        assert text[start:end].strip().endswith("."), "a piece ends mid-sentence"


def test_split_spans_tile_the_input_exactly() -> None:
    """No authored text is dropped or duplicated by splitting."""
    paragraph = "Policy prose paragraph with a reasonable amount of content in it. " * 5
    text = "\n\n".join([paragraph] * 6)

    spans = _split_section_text(text, max_chars=500)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    for (_, prev_end), (next_start, _) in itertools.pairwise(spans):
        assert prev_end == next_start
    assert "".join(text[s:e] for s, e in spans) == text


def test_a_short_section_is_exactly_one_chunk() -> None:
    spans = _split_section_text("Short section body.", max_chars=MAX_CHUNK_CHARS)
    assert spans == [(0, len("Short section body."))]


def test_an_oversized_single_paragraph_is_not_cut_mid_sentence() -> None:
    """Emitting one long chunk beats emitting a citation that reads as a mistake."""
    text = "word " * 1000  # no paragraph breaks at all
    spans = _split_section_text(text, max_chars=200)
    assert spans == [(0, len(text))]


def test_a_runt_tail_is_merged_into_its_predecessor() -> None:
    """A 40-character trailing chunk retrieves badly and cites worse."""
    body = "A reasonably long paragraph of policy text that fills the chunk nicely. " * 8
    text = body + "\n\nShort tail."
    spans = _split_section_text(text, max_chars=400)
    assert all((end - start) >= 100 for start, end in spans)


def test_corpus_statistics_are_reported(corpus: list[PolicyDoc]) -> None:
    produced, stats = chunk_corpus(corpus)
    assert stats.chunks == len(produced)
    assert stats.policies == len(corpus)
    assert stats.sections >= stats.chunks - stats.split_sections
    assert "chunks from" in stats.render()
