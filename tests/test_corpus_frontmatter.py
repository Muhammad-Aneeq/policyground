"""The corpus meets its authoring contract.

Spec 08 §4 F1 asks for "~30 synthetic accounting policies … with section structure + sensitivity
labels (public/internal/restricted)". These tests turn each clause of that sentence into an
assertion, including the parts a reader would otherwise have to take on trust: that the section
offsets are exact, and that there really are enough restricted policies for the roles demo to
show anything.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections import Counter
from pathlib import Path

import pytest

from policyground.corpus.loader import CorpusError, load_policy, parse_sections, split_front_matter
from policyground.corpus.models import PolicyDoc
from policyground.labels import Label

MIN_POLICIES = 28
MIN_RESTRICTED = 5
MIN_SECTIONS_PER_POLICY = 3


def test_corpus_has_roughly_thirty_policies(corpus: list[PolicyDoc]) -> None:
    assert len(corpus) >= MIN_POLICIES, f"spec 08 F1 asks for ~30 policies, found {len(corpus)}"


def test_policy_ids_are_unique_and_well_formed(corpus: list[PolicyDoc]) -> None:
    ids = [doc.policy_id for doc in corpus]
    assert len(set(ids)) == len(ids)
    assert all(pid.startswith("PG-") and len(pid) == 7 for pid in ids)


def test_filename_carries_its_policy_id(corpus: list[PolicyDoc]) -> None:
    """A citation should be resolvable to a file without a lookup table."""
    for doc in corpus:
        assert doc.source_path.startswith(doc.policy_id)


def test_every_label_is_represented(corpus: list[PolicyDoc]) -> None:
    counts = Counter(doc.label for doc in corpus)
    for label in Label:
        assert counts[label] > 0, f"no policy carries label {label}"


def test_enough_restricted_policies_for_the_roles_demo(corpus: list[PolicyDoc]) -> None:
    """The brief asks for at least 5 restricted policies so the roles demo has something to hide."""
    restricted = [doc for doc in corpus if doc.label is Label.RESTRICTED]
    assert len(restricted) >= MIN_RESTRICTED


def test_every_policy_has_section_structure(corpus: list[PolicyDoc]) -> None:
    for doc in corpus:
        assert len(doc.sections) >= MIN_SECTIONS_PER_POLICY, (
            f"{doc.policy_id} has {len(doc.sections)} section(s); "
            f"section-aware chunking needs real structure to work with"
        )


def test_section_offsets_are_exact(corpus: list[PolicyDoc]) -> None:
    """``raw[start:end] == section.text`` — the invariant the Source Viewer highlight rests on.

    If this ever fails, highlighting silently points at the wrong passage while still looking
    plausible, which is the worst failure mode a citation product can have (PLAN.md D-017).
    """
    for doc in corpus:
        for section in doc.sections:
            assert doc.raw[section.start : section.end] == section.text, (
                f"{doc.policy_id} section {section.path_str!r} offsets do not match its text"
            )


def test_sections_tile_the_body_without_gaps_or_overlap(corpus: list[PolicyDoc]) -> None:
    """No authored sentence is unindexable, and none is indexed twice."""
    for doc in corpus:
        ordered = sorted(doc.sections, key=lambda s: s.start)
        assert ordered[0].start == doc.body_start
        for earlier, later in itertools.pairwise(ordered):
            assert earlier.end == later.start, f"{doc.policy_id}: gap/overlap at {later.path_str!r}"
        assert ordered[-1].end == len(doc.raw)


def test_section_paths_record_the_heading_trail(corpus: list[PolicyDoc]) -> None:
    for doc in corpus:
        for section in doc.sections:
            assert section.path, f"{doc.policy_id}: section {section.heading!r} has no path"
            assert section.path[-1] == section.heading


def test_front_matter_fields_are_populated(corpus: list[PolicyDoc]) -> None:
    for doc in corpus:
        fm = doc.front_matter
        assert fm.title.strip()
        assert fm.owner.strip()
        assert isinstance(fm.effective_date, dt.date)
        assert fm.category.strip()
        assert fm.tags, f"{doc.policy_id} has no tags"


def test_restricted_policies_declare_their_distribution(corpus: list[PolicyDoc]) -> None:
    """A restricted policy that reads like a public one teaches the demo nothing.

    Each restricted document states who may read it and why it is restricted, so a reviewer can
    see the label is a property of the content rather than a flag sprinkled on at random.
    """
    for doc in corpus:
        if doc.label is not Label.RESTRICTED:
            continue
        body = doc.body.lower()
        assert "distribution:" in body, f"{doc.policy_id} does not state its distribution list"
        assert "why this policy is restricted" in body, (
            f"{doc.policy_id} does not explain why it is restricted"
        )


# --------------------------------------------------------------- parser unit tests --


def test_split_front_matter_reports_a_missing_fence() -> None:
    with pytest.raises(CorpusError, match="front-matter fence"):
        split_front_matter("# No front matter\n", source="x.md")


def test_split_front_matter_reports_an_unclosed_block() -> None:
    with pytest.raises(CorpusError, match="not closed"):
        split_front_matter("---\npolicy_id: PG-0001\n", source="x.md")


def test_body_offset_points_at_real_content() -> None:
    raw = "---\npolicy_id: PG-9999\n---\n\n# Heading\n\nBody.\n"
    mapping, body_start = split_front_matter(raw, source="x.md")
    assert mapping["policy_id"] == "PG-9999"
    assert raw[body_start:].startswith("# Heading")


def test_unquoted_version_is_rejected(tmp_path: Path) -> None:
    """``version: 3.10`` parses as the float 3.1 and would silently look like a regression."""
    path = tmp_path / "PG-9999-x.md"
    path.write_text(
        "---\n"
        "policy_id: PG-9999\n"
        "title: Test Policy Title\n"
        "label: public\n"
        "version: 3.10\n"
        "owner: Someone Senior\n"
        "effective_date: 2026-01-01\n"
        "category: test\n"
        "tags: [t]\n"
        "---\n\n## 1. A\n\ntext\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="version"):
        load_policy(path)


def test_unknown_front_matter_key_is_rejected(tmp_path: Path) -> None:
    """``extra="forbid"`` in action: a misspelled key must never be silently ignored."""
    path = tmp_path / "PG-9998-x.md"
    path.write_text(
        "---\n"
        "policy_id: PG-9998\n"
        "title: Test Policy Title\n"
        "labell: restricted\n"
        "label: public\n"
        "version: '1.0'\n"
        "owner: Someone Senior\n"
        "effective_date: 2026-01-01\n"
        "category: test\n"
        "tags: [t]\n"
        "---\n\n## 1. A\n\ntext\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="invalid front-matter"):
        load_policy(path)


def test_parse_sections_captures_nested_heading_trail() -> None:
    raw = "---\nx: 1\n---\n# Top\n\nintro\n\n## One\n\na\n\n### One A\n\nb\n\n## Two\n\nc\n"
    _, body_start = split_front_matter(raw, source="x.md")
    sections = parse_sections(raw, body_start)
    paths = [s.path for s in sections]
    assert ("Top",) in paths
    assert ("Top", "One") in paths
    assert ("Top", "One", "One A") in paths
    # "Two" is a sibling of "One", so "One A" must not remain in its trail.
    assert ("Top", "Two") in paths
