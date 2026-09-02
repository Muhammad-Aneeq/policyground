"""Shared fixtures. The real corpus is loaded once per session — it is read-only and 30 files."""

from __future__ import annotations

from pathlib import Path

import pytest

from policyground.config import Settings, get_settings
from policyground.corpus.chunker import chunk_corpus
from policyground.corpus.consistency import load_canaries
from policyground.corpus.loader import load_corpus
from policyground.corpus.models import PolicyDoc
from policyground.retrieval.base import Chunk
from policyground.retrieval.embeddings import HashEmbedder
from policyground.retrieval.local_retriever import LocalHybridRetriever


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def corpus(settings: Settings) -> list[PolicyDoc]:
    """Every authored policy, in policy-id order."""
    return load_corpus(settings.policies_dir)


@pytest.fixture(scope="session")
def constants_path(settings: Settings) -> Path:
    return settings.constants_path


@pytest.fixture(scope="session")
def canaries_path(settings: Settings) -> Path:
    return settings.canaries_path


@pytest.fixture(scope="session")
def canaries(canaries_path: Path) -> dict[str, str]:
    return load_canaries(canaries_path)


@pytest.fixture(scope="session")
def chunks(corpus: list[PolicyDoc]) -> list[Chunk]:
    return chunk_corpus(corpus)[0]


@pytest.fixture(scope="session")
def retriever(chunks: list[Chunk], settings: Settings) -> LocalHybridRetriever:
    """A retriever built in-process from the corpus.

    Built from source rather than loaded from ``data/index.json`` on purpose: tests must fail when
    the *corpus* and the *code* disagree, not when someone forgot to re-run ``pg ingest``. A stale
    committed index would otherwise let a corpus edit pass the whole suite.
    """
    embedder = HashEmbedder(dim=settings.embedding_dim)
    vectors = embedder.embed([chunk.indexable_text for chunk in chunks])
    return LocalHybridRetriever(
        chunks=chunks, vectors=vectors, embedder=embedder, rrf_k=settings.rrf_k
    )
