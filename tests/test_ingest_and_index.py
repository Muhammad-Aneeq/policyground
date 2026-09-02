"""Ingestion rebuilds are deterministic, provenance-checked, and refuse a bad corpus.

The embedder-mismatch guard is the test that earns its keep. Without it, the most confusing
possible failure is one environment variable away: add an API key, restart the API without
re-ingesting, and every query embeds with OpenAI against vectors built by the hash embedder.
Nothing errors. Retrieval just returns quietly meaningless results and the refusal rate climbs
for reasons no log explains.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from policyground.config import AppMode, Settings
from policyground.corpus.chunker import chunk_corpus
from policyground.corpus.models import PolicyDoc
from policyground.ingest.manifest import build_manifest, corpus_digest, policy_digest
from policyground.ingest.pipeline import IngestError, run_ingest
from policyground.retrieval.embeddings import HashEmbedder
from policyground.retrieval.vector_store import (
    IndexMismatchError,
    load_index,
    save_index,
)


@pytest.fixture
def scratch_settings(tmp_path: Path, settings: Settings) -> Settings:
    """Settings pointed at a temp copy of the corpus and a temp data directory."""
    corpus_copy = tmp_path / "corpus"
    shutil.copytree(settings.corpus_dir, corpus_copy)

    class ScratchSettings(Settings):  # type: ignore[misc]
        @property
        def corpus_dir(self) -> Path:
            return corpus_copy

        @property
        def policies_dir(self) -> Path:
            return corpus_copy / "policies"

        @property
        def constants_path(self) -> Path:
            return corpus_copy / "constants.yaml"

        @property
        def canaries_path(self) -> Path:
            return corpus_copy / "canaries.yaml"

        @property
        def manifest_path(self) -> Path:
            return corpus_copy / "MANIFEST.json"

        @property
        def data_dir(self) -> Path:
            return tmp_path / "data"

        @property
        def index_path(self) -> Path:
            return tmp_path / "data" / "index.json"

        @property
        def vectors_path(self) -> Path:
            return tmp_path / "data" / "vectors.npy"

    return ScratchSettings(openai_api_key=None)


# ------------------------------------------------------------- the pipeline --


def test_one_command_builds_a_complete_index(scratch_settings: Settings) -> None:
    """Spec 08 F2: ingestion is rebuildable by one command."""
    result = run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)

    assert result.policies == 30
    assert result.chunks > 200
    assert result.embedder == "hash-embedder-v1"
    assert result.degraded is True  # no key in this environment (BLOCKERS.md B1)
    assert scratch_settings.index_path.exists()
    assert scratch_settings.vectors_path.exists()
    assert scratch_settings.manifest_path.exists()
    assert "BLOCKERS.md B1" in result.render()


def test_ingestion_is_idempotent(scratch_settings: Settings) -> None:
    """Two runs over an unchanged corpus produce byte-identical artifacts."""
    first = run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)
    index_bytes = scratch_settings.index_path.read_bytes()
    vector_bytes = scratch_settings.vectors_path.read_bytes()
    manifest_bytes = scratch_settings.manifest_path.read_bytes()

    second = run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)

    assert first.corpus_sha256 == second.corpus_sha256
    assert scratch_settings.index_path.read_bytes() == index_bytes
    assert scratch_settings.vectors_path.read_bytes() == vector_bytes
    assert scratch_settings.manifest_path.read_bytes() == manifest_bytes


def test_ingestion_refuses_an_inconsistent_corpus(scratch_settings: Settings) -> None:
    """A drifted threshold must not become a confidently-cited wrong answer."""
    target = scratch_settings.policies_dir / "PG-0007-delegation-of-authority.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "Finance Director may approve commitments up to USD 100,000",
            "Finance Director may approve commitments up to USD 150,000",
        ),
        encoding="utf-8",
    )

    with pytest.raises(IngestError, match="inconsistent corpus"):
        run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)

    assert not scratch_settings.index_path.exists(), "a rejected corpus must leave no index behind"


def test_azure_mode_without_credentials_fails_clearly(scratch_settings: Settings) -> None:
    """The error names the missing variables and points at the runbook, not a stack trace."""
    with pytest.raises(IngestError, match="AZURE_SEARCH_ENDPOINT"):
        run_ingest(scratch_settings, mode=AppMode.AZURE, rebuild=True)


def test_a_corpus_edit_changes_the_corpus_hash(scratch_settings: Settings) -> None:
    before = run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True).corpus_sha256

    target = scratch_settings.policies_dir / "PG-0029-inventory-valuation.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n\n## 9. Addendum\n\nNew guidance.\n",
        encoding="utf-8",
    )

    after = run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True).corpus_sha256
    assert before != after


# --------------------------------------------------------------- provenance --


def test_index_records_what_built_it(scratch_settings: Settings) -> None:
    run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)
    payload = json.loads(scratch_settings.index_path.read_text(encoding="utf-8"))

    assert payload["embedder"] == "hash-embedder-v1"
    assert payload["embedding_dim"] == scratch_settings.embedding_dim
    assert len(payload["corpus_sha256"]) == 64
    assert payload["chunk_count"] == len(payload["chunks"])


def test_loading_with_a_different_embedder_raises(scratch_settings: Settings) -> None:
    """THE guard: querying an index with the wrong embedder must be loud, not quiet."""
    run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)

    with pytest.raises(IndexMismatchError, match="meaningless results"):
        load_index(
            scratch_settings.index_path,
            scratch_settings.vectors_path,
            expected_embedder="openai:text-embedding-3-small",
        )


def test_loading_with_the_matching_embedder_succeeds(scratch_settings: Settings) -> None:
    run_ingest(scratch_settings, mode=AppMode.LOCAL, rebuild=True)
    artifact = load_index(
        scratch_settings.index_path,
        scratch_settings.vectors_path,
        expected_embedder="hash-embedder-v1",
    )
    assert len(artifact.chunks) == artifact.vectors.shape[0]
    assert artifact.embedding_dim == scratch_settings.embedding_dim


def test_a_missing_index_says_how_to_build_one(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="pg ingest --rebuild"):
        load_index(tmp_path / "index.json", tmp_path / "vectors.npy")


def test_a_chunk_vector_count_mismatch_is_detected(tmp_path: Path, corpus: list[PolicyDoc]) -> None:
    """Corruption caught at load, rather than as a confusing IndexError during a query."""
    produced, _ = chunk_corpus(corpus)
    embedder = HashEmbedder(dim=64)
    vectors = embedder.embed([chunk.indexable_text for chunk in produced])

    index_path, vectors_path = tmp_path / "index.json", tmp_path / "vectors.npy"
    save_index(
        index_path,
        vectors_path,
        chunks=produced,
        vectors=vectors,
        embedder_name="hash-embedder-v1",
        embedding_dim=64,
        corpus_sha256="0" * 64,
        rrf_k=60,
    )
    np.save(vectors_path, vectors[:-5])  # drop rows behind the index's back

    with pytest.raises(IndexMismatchError, match="corrupt"):
        load_index(index_path, vectors_path)


def test_round_trip_preserves_every_chunk_field(tmp_path: Path, corpus: list[PolicyDoc]) -> None:
    produced, _ = chunk_corpus(corpus)
    embedder = HashEmbedder(dim=64)
    vectors = embedder.embed([chunk.indexable_text for chunk in produced])

    index_path, vectors_path = tmp_path / "index.json", tmp_path / "vectors.npy"
    save_index(
        index_path,
        vectors_path,
        chunks=produced,
        vectors=vectors,
        embedder_name="hash-embedder-v1",
        embedding_dim=64,
        corpus_sha256="0" * 64,
        rrf_k=60,
    )
    artifact = load_index(index_path, vectors_path)

    assert artifact.chunks == produced, "a chunk field was lost or altered by the round trip"
    assert np.array_equal(artifact.vectors, vectors)


# ----------------------------------------------------------------- manifest --


def test_manifest_covers_every_policy(corpus: list[PolicyDoc]) -> None:
    payload = build_manifest(corpus)
    assert payload["policy_count"] == len(corpus)
    assert {entry["policy_id"] for entry in payload["policies"]} == {
        doc.policy_id for doc in corpus
    }
    assert payload["labels"] == {"internal": 14, "public": 10, "restricted": 6}


def test_manifest_hashes_are_line_ending_independent(corpus: list[PolicyDoc]) -> None:
    """Otherwise every policy looks changed when the repo is checked out on Windows."""
    doc = corpus[0]
    crlf = PolicyDoc(
        front_matter=doc.front_matter,
        raw=doc.raw.replace("\n", "\r\n"),
        body_start=doc.body_start,
        sections=doc.sections,
        source_path=doc.source_path,
    )
    assert policy_digest(crlf) == policy_digest(doc)


def test_corpus_digest_changes_when_any_policy_changes(corpus: list[PolicyDoc]) -> None:
    baseline = corpus_digest(corpus)
    mutated = PolicyDoc(
        front_matter=corpus[0].front_matter,
        raw=corpus[0].raw + "\nextra\n",
        body_start=corpus[0].body_start,
        sections=corpus[0].sections,
        source_path=corpus[0].source_path,
    )
    assert corpus_digest([mutated, *corpus[1:]]) != baseline


def test_corpus_digest_is_order_independent(corpus: list[PolicyDoc]) -> None:
    """The hash identifies the corpus, not the order the loader happened to return it in."""
    assert corpus_digest(corpus) == corpus_digest(list(reversed(corpus)))
