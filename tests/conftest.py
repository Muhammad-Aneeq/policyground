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
from policyground.retrieval.vocabulary import CorpusVocabulary


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


@pytest.fixture(scope="session")
def offline_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A scratch ``data/`` holding an index built by :class:`HashEmbedder`, built once per session.

    This exists so the **API** tests can run the way every other test in this suite already does:
    offline, deterministically, and without a credential. Those tests boot the real application,
    which loads ``<repo>/data/index.json`` — so with a real key configured they were embedding and
    composing against the live API, on every ``POST /api/ask``, on every run. That contradicted the
    README's "254 unit tests (LLM mocked)" and would bill the project's owner for CI.

    Session-scoped because building it is the expensive part (chunk + embed 256 passages) and the
    content is identical for every test. The one test that *writes* here — the reindex endpoint —
    regenerates the same bytes from the same corpus, so sharing it is safe.
    """
    from policyground.config import AppMode, Settings
    from policyground.ingest.pipeline import run_ingest

    data_dir = tmp_path_factory.mktemp("offline-data")
    run_ingest(
        Settings(openai_api_key=None, pg_data_dir=data_dir),
        mode=AppMode.LOCAL,
        rebuild=True,
    )
    return data_dir


@pytest.fixture(scope="session")
def vocabulary(chunks: list[Chunk]) -> CorpusVocabulary:
    """Corpus document frequencies, built in-process from the same chunks the retriever uses.

    Built rather than loaded from ``data/vocabulary.json`` for the same reason as the retriever
    fixture: the tests must fail when the corpus and the code disagree, not when someone forgot to
    re-run ``pg ingest``.
    """
    return CorpusVocabulary.from_chunks(chunks)
