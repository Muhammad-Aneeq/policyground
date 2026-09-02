"""Persisting and loading the local index.

The index is two files — ``index.json`` (chunks + provenance) and ``vectors.npy`` — plus one rule
that matters more than the format: **the artifact records what built it.** Embedder name, embedding
dimension, RRF constant and the corpus SHA-256 all travel with the index, and
:func:`load_index` refuses to hand back an index whose embedder does not match the one configured
now.

Without that check, the most confusing possible failure is available: add an API key, restart the
API without re-ingesting, and every query embeds with OpenAI against vectors built by the hash
embedder. Retrieval would not error. It would just quietly return nonsense, and the refusal rate
would climb for reasons no log would explain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from policyground.labels import Label
from policyground.retrieval.base import Chunk

INDEX_SCHEMA = "policyground/index/v1"


class IndexMismatchError(RuntimeError):
    """The stored index was not built with the currently configured embedder."""


@dataclass(frozen=True, slots=True)
class IndexArtifact:
    """An index plus the provenance needed to trust it."""

    chunks: list[Chunk]
    vectors: np.ndarray
    embedder_name: str
    embedding_dim: int
    corpus_sha256: str
    rrf_k: int

    def __len__(self) -> int:
        return len(self.chunks)


def _chunk_to_json(chunk: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "policy_id": chunk.policy_id,
        "policy_title": chunk.policy_title,
        "section_path": chunk.section_path,
        "label": chunk.label.value,
        "version": chunk.version,
        "text": chunk.text,
        "start": chunk.start,
        "end": chunk.end,
        "ordinal": chunk.ordinal,
    }


def _chunk_from_json(payload: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=payload["chunk_id"],
        policy_id=payload["policy_id"],
        policy_title=payload["policy_title"],
        section_path=payload["section_path"],
        label=Label(payload["label"]),
        version=payload["version"],
        text=payload["text"],
        start=payload["start"],
        end=payload["end"],
        ordinal=payload["ordinal"],
    )


def save_index(
    index_path: Path,
    vectors_path: Path,
    *,
    chunks: list[Chunk],
    vectors: np.ndarray,
    embedder_name: str,
    embedding_dim: int,
    corpus_sha256: str,
    rrf_k: int,
) -> None:
    """Write both halves of the index atomically enough for a dev tool.

    Vectors go to ``.npy`` rather than into the JSON: 250 chunks x 384 float32 is 380 KB as binary
    and roughly 4 MB as JSON text, and the JSON round-trip would not be bit-exact.
    """
    index_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": INDEX_SCHEMA,
        "embedder": embedder_name,
        "embedding_dim": embedding_dim,
        "corpus_sha256": corpus_sha256,
        "rrf_k": rrf_k,
        "chunk_count": len(chunks),
        "chunks": [_chunk_to_json(chunk) for chunk in chunks],
    }
    index_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    np.save(vectors_path, vectors.astype(np.float32))


def load_index(
    index_path: Path,
    vectors_path: Path,
    *,
    expected_embedder: str | None = None,
) -> IndexArtifact:
    """Load an index, refusing a mismatch rather than returning quietly wrong results."""
    if not index_path.exists() or not vectors_path.exists():
        raise FileNotFoundError(
            f"no index at {index_path} / {vectors_path}. Run `pg ingest --rebuild` first."
        )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if payload.get("schema") != INDEX_SCHEMA:
        raise IndexMismatchError(
            f"index schema {payload.get('schema')!r} is not {INDEX_SCHEMA!r}; rebuild the index"
        )

    stored_embedder = str(payload["embedder"])
    if expected_embedder is not None and stored_embedder != expected_embedder:
        raise IndexMismatchError(
            f"index was built with embedder {stored_embedder!r} but {expected_embedder!r} is "
            f"configured now. Querying it would return meaningless results rather than an error. "
            f"Run `pg ingest --rebuild`."
        )

    chunks = [_chunk_from_json(item) for item in payload["chunks"]]
    vectors = np.load(vectors_path).astype(np.float32)

    if vectors.shape[0] != len(chunks):
        raise IndexMismatchError(
            f"index is corrupt: {len(chunks)} chunks but {vectors.shape[0]} vectors. Rebuild."
        )

    return IndexArtifact(
        chunks=chunks,
        vectors=vectors,
        embedder_name=stored_embedder,
        embedding_dim=int(payload["embedding_dim"]),
        corpus_sha256=str(payload["corpus_sha256"]),
        rrf_k=int(payload.get("rrf_k", 60)),
    )
