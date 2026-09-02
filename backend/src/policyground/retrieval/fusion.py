"""Reciprocal Rank Fusion — how the keyword and vector arms are combined.

RRF scores a document by ``sum over arms of 1 / (k + rank)``. Two reasons this is the right choice
here rather than a weighted sum of raw scores (PLAN.md **D-005**):

1. **Scale-free.** BM25 scores are unbounded and corpus-dependent; cosine similarities live in
   [-1, 1]. Normalising them onto a common scale requires constants that need retuning whenever the
   corpus changes. Ranks need nothing.

2. **It is what Azure AI Search does.** AI Search fuses hybrid results with RRF. Using the same
   algorithm locally means LOCAL and AZURE modes are *behaviourally* comparable, not merely
   interface-compatible — which matters when the whole point of the two-mode design is that the
   controls behave identically in both.

``k`` defaults to 60, the value from the original RRF paper and the AI Search default. A larger
``k`` flattens the contribution of rank differences; a smaller one lets a single arm's top hit
dominate.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RRF_K = 60


@dataclass(frozen=True, slots=True)
class FusedResult:
    """One document's fused standing, retaining per-arm provenance."""

    key: str
    score: float
    bm25_rank: int | None
    vector_rank: int | None
    bm25_score: float | None
    vector_score: float | None


def _rank_map(ordered: list[tuple[str, float]]) -> dict[str, tuple[int, float]]:
    """``[(key, score)]`` sorted best-first → ``{key: (1-based rank, score)}``."""
    return {key: (index + 1, score) for index, (key, score) in enumerate(ordered)}


def reciprocal_rank_fusion(
    bm25_ranked: list[tuple[str, float]],
    vector_ranked: list[tuple[str, float]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[FusedResult]:
    """Fuse two ranked lists into one, best-first.

    Both inputs must already be sorted best-first. A document found by only one arm still scores —
    that is the property that makes hybrid retrieval worth having, and it matters especially in
    this build where the vector arm is a lexical stand-in (BLOCKERS.md **B1**): a question the hash
    embedder cannot place can still be answered on the keyword arm alone.

    Ties are broken deterministically by key, so two chunks with identical fused scores always come
    back in the same order. Without that, an index rebuild could reorder citations in an otherwise
    unchanged answer and show up as a spurious eval regression.
    """
    if k < 1:
        raise ValueError("RRF k must be >= 1")

    bm25 = _rank_map(bm25_ranked)
    vector = _rank_map(vector_ranked)

    fused: list[FusedResult] = []
    for key in bm25.keys() | vector.keys():
        bm25_entry = bm25.get(key)
        vector_entry = vector.get(key)

        score = 0.0
        if bm25_entry is not None:
            score += 1.0 / (k + bm25_entry[0])
        if vector_entry is not None:
            score += 1.0 / (k + vector_entry[0])

        fused.append(
            FusedResult(
                key=key,
                score=score,
                bm25_rank=bm25_entry[0] if bm25_entry else None,
                vector_rank=vector_entry[0] if vector_entry else None,
                bm25_score=bm25_entry[1] if bm25_entry else None,
                vector_score=vector_entry[1] if vector_entry else None,
            )
        )

    fused.sort(key=lambda result: (-result.score, result.key))
    return fused


def max_possible_score(k: int = DEFAULT_RRF_K) -> float:
    """The fused score of a document ranked first by both arms.

    Used to normalise a fused score into [0, 1] for the sufficiency assessor, which needs a
    bounded quantity rather than a raw RRF value whose magnitude depends only on ``k``.
    """
    return 2.0 / (k + 1)
