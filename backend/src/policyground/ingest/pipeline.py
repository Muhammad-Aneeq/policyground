"""One command rebuilds everything: ``pg ingest --rebuild``.

Spec 08 §4 F2 requires ingestion to be rebuildable, and the brief makes it a one-command
guarantee. That is not just convenience — CI rebuilds the index from the corpus before running the
evals, so a policy edit that would change an answer can never pass tests against a stale committed
index.

The pipeline refuses to build an index from an inconsistent corpus. Running the consistency check
first (PLAN.md **D-011**) means a threshold that drifted between two policies is caught before it
becomes a confidently-cited wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from policyground.config import AppMode, Settings
from policyground.corpus.chunker import chunk_corpus
from policyground.corpus.consistency import check_corpus
from policyground.corpus.loader import load_corpus
from policyground.ingest.manifest import build_manifest, corpus_digest, write_manifest
from policyground.retrieval.base import Chunk
from policyground.retrieval.embeddings import build_embedder
from policyground.retrieval.vector_store import save_index
from policyground.retrieval.vocabulary import CorpusVocabulary


class IngestError(RuntimeError):
    """Ingestion refused to build an index."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What a rebuild produced — printed by the CLI and asserted in tests."""

    mode: AppMode
    policies: int
    chunks: int
    embedder: str
    embedding_dim: int
    corpus_sha256: str
    stats_line: str
    target: str
    degraded: bool

    def render(self) -> str:
        lines = [
            f"ingest ({self.mode.value}) -> {self.target}",
            f"  {self.stats_line}",
            f"  embedder: {self.embedder} (dim {self.embedding_dim})",
            f"  corpus:   {self.corpus_sha256[:12]}...",
        ]
        if self.degraded:
            lines.append(
                "  NOTE: no model credential found, so a deterministic hash embedder was used. "
                "It has no semantic similarity (BLOCKERS.md B1)."
            )
        return "\n".join(lines)


def run_ingest(settings: Settings, *, mode: AppMode, rebuild: bool = False) -> IngestResult:
    """Load → check → chunk → embed → persist.

    ``rebuild`` currently only affects messaging: the local index is always written whole, because
    an incremental path would be a second code path capable of producing a *different* index from
    the same corpus, and having two ways to build the thing every guarantee rests on is worse than
    the seconds it saves on 30 policies.
    """
    docs = load_corpus(settings.policies_dir)

    report = check_corpus(
        docs,
        constants_path=settings.constants_path,
        canaries_path=settings.canaries_path,
    )
    if not report.ok:
        raise IngestError(
            "refusing to index an inconsistent corpus — a threshold that disagrees between two "
            "policies would be cited confidently and wrongly.\n" + report.render()
        )

    chunks, stats = chunk_corpus(docs)
    embedder = build_embedder(settings)
    degraded = not settings.has_openai_key

    # `Chunk.indexable_text` is shared with the BM25 arm and with Azure ingestion, so no two
    # paths can disagree about what a document is.
    vectors = embedder.embed([chunk.indexable_text for chunk in chunks])

    digest = corpus_digest(docs)

    # The vocabulary is derived from the corpus, not from the backend, so it is written in
    # BOTH modes. Refusal behaviour must not differ between LOCAL and AZURE, and it would if
    # the off-corpus signal were only available in one of them.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    CorpusVocabulary.from_chunks(chunks).save(settings.vocabulary_path)

    chunk_counts: dict[str, int] = {}
    for chunk in chunks:
        chunk_counts[chunk.policy_id] = chunk_counts.get(chunk.policy_id, 0) + 1
    write_manifest(settings.manifest_path, build_manifest(docs, chunk_counts=chunk_counts))

    if mode is AppMode.AZURE:
        target = _ingest_azure(settings, chunks, vectors, embedder.name)
    else:
        save_index(
            settings.index_path,
            settings.vectors_path,
            chunks=chunks,
            vectors=vectors,
            embedder_name=embedder.name,
            embedding_dim=embedder.dim,
            corpus_sha256=digest,
            rrf_k=settings.rrf_k,
        )
        target = str(settings.index_path)

    return IngestResult(
        mode=mode,
        policies=len(docs),
        chunks=len(chunks),
        embedder=embedder.name,
        embedding_dim=embedder.dim,
        corpus_sha256=digest,
        stats_line=stats.render(),
        target=target,
        degraded=degraded,
    )


def _ingest_azure(
    settings: Settings,
    chunks: list[Chunk],
    vectors: np.ndarray,
    embedder_name: str,
) -> str:
    """Push the same chunks to Azure AI Search.

    Deliberately the *same* chunks and the *same* vectors as LOCAL mode — chunking and embedding
    happen before the mode branch, so the two backends cannot drift apart in how they represent a
    passage. Only the destination differs.

    Never executed in this build (BLOCKERS.md **B2**): there is no Search endpoint to push to.
    """
    if not settings.has_azure_search:
        raise IngestError(
            "APP_MODE=azure needs AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY. "
            "See DEPLOY_RUNBOOK.md; this build has neither (BLOCKERS.md B2)."
        )

    from policyground.ingest.azure_index import upload_chunks

    upload_chunks(settings, chunks, vectors, embedder_name=embedder_name)
    return f"{settings.azure_search_endpoint}/indexes/{settings.azure_search_index}"
