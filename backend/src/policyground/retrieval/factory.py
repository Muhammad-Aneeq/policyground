"""Build the configured retriever. The only place in the application that reads ``APP_MODE``.

Keeping the mode switch in one function is what makes the two-mode claim checkable: everything
downstream — the graph, citation enforcement, refusal, the API, the evals — receives a
:class:`~policyground.retrieval.base.Retriever` and cannot tell which one it got. If a second
``if settings.app_mode == ...`` ever appears elsewhere, the claim that the modes behave identically
has quietly stopped being structural.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from policyground.config import AppMode, Settings, get_settings
from policyground.retrieval.base import Retriever
from policyground.retrieval.embeddings import build_embedder
from policyground.retrieval.local_retriever import LocalHybridRetriever
from policyground.retrieval.vector_store import load_index

logger = logging.getLogger(__name__)


def build_retriever(settings: Settings) -> Retriever:
    """Return the retriever for the configured mode.

    The embedder is built *before* the index is loaded so its name can be checked against the
    index's provenance — a mismatch raises rather than returning silently meaningless results
    (see ``vector_store.load_index``).
    """
    if settings.app_mode is AppMode.AZURE:
        # Imported lazily: the azure extra is optional, and LOCAL mode must not require it.
        from policyground.retrieval.azure_retriever import AzureSearchRetriever

        azure: Retriever = AzureSearchRetriever.from_settings(settings)
        return azure

    embedder = build_embedder(settings)
    artifact = load_index(
        settings.index_path,
        settings.vectors_path,
        expected_embedder=embedder.name,
    )

    if not settings.has_openai_key:
        logger.warning(
            "no model credential: retrieval is using %s, which measures lexical overlap and "
            "not meaning (BLOCKERS.md B1)",
            embedder.name,
        )

    return LocalHybridRetriever(
        chunks=artifact.chunks,
        vectors=artifact.vectors,
        embedder=embedder,
        rrf_k=artifact.rrf_k,
    )


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Process-wide retriever, so the API does not reload a 250-chunk index per request."""
    return build_retriever(get_settings())


def reset_retriever_cache() -> None:
    """Drop the cached retriever — used after a reindex and by tests."""
    get_retriever.cache_clear()
