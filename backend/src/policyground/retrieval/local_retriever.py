"""LOCAL mode retrieval: BM25 + vector search + RRF fusion, with label filtering applied first.

**The one thing to read in this file** is that the label filter is applied to the candidate set
*before* either arm scores anything (:meth:`LocalHybridRetriever._permitted_indices`). Spec 08 §4
F6 says restricted chunks must "never enter context for unprivileged roles". A post-filter would
technically satisfy a leak test on the final answer while restricted text had already been loaded,
ranked, logged and traced. Filtering first means the text is never read at all.

There is a second, quieter benefit: filtering first keeps ``top_k`` honest. Retrieve-then-filter
returns fewer than ``top_k`` results for unprivileged roles, so a guest silently gets a thinner
evidence set — and thinner evidence means more refusals, which would look like a retrieval quality
problem rather than the governance behaviour it actually is.
"""

from __future__ import annotations

import numpy as np
from rank_bm25 import BM25Okapi

from policyground.labels import Label, Role, allowed_labels
from policyground.retrieval.base import Chunk, Hit, RetrievalResult
from policyground.retrieval.embeddings import Embedder, tokenize, tokenize_query
from policyground.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion

#: How many candidates each arm contributes before fusion. Wider than ``top_k`` so that a chunk
#: ranked modestly by both arms can still out-rank a chunk ranked highly by only one.
ARM_CANDIDATES = 30


class LocalHybridRetriever:
    """Hybrid retrieval over an in-memory index built by ``ingest.pipeline``."""

    backend_name = "local-hybrid"

    def __init__(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        embedder: Embedder,
        *,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"index inconsistent: {len(chunks)} chunks but {vectors.shape[0]} vectors"
            )

        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder
        self.rrf_k = rrf_k

        self._by_id: dict[str, int] = {chunk.chunk_id: i for i, chunk in enumerate(chunks)}

        # Both arms index the *same* document representation — policy title, section path, then
        # body — via `indexable_text`. Letting them differ would mean the two arms disagree about
        # what a document even is, so a fused score would mix two different notions of relevance.
        # It also fixes a concrete retrieval failure: a section headed "4. Accommodation" is nearly
        # unfindable from its body alone, because the body never repeats its own subject.
        self._tokenised: list[list[str]] = [tokenize(chunk.indexable_text) for chunk in chunks]

        # BM25 is fitted over the whole corpus, deliberately. Corpus statistics (document
        # frequency, average length) must not depend on who is asking: refitting per role would
        # make a term's rarity vary by session, so the same question would score differently for a
        # guest and a controller for reasons unrelated to what they may see. Filtering happens on
        # the candidate set, after scoring, but before anything is *read* — the scores of
        # disallowed chunks are computed as numbers and discarded without their text being touched.
        self._bm25 = BM25Okapi(self._tokenised) if chunks else None

        # Precomputed label index, so filtering is a set lookup rather than a scan per query.
        self._indices_by_label: dict[Label, list[int]] = {label: [] for label in Label}
        for index, chunk in enumerate(chunks):
            self._indices_by_label[chunk.label].append(index)

    # ------------------------------------------------------------- internals --

    def _permitted_indices(self, role: Role) -> np.ndarray:
        """Row indices this role may see. The governance boundary, in one function."""
        permitted: list[int] = []
        for label in allowed_labels(role):
            permitted.extend(self._indices_by_label[label])
        return np.array(sorted(permitted), dtype=np.int64)

    def _bm25_arm(self, query: str, permitted: np.ndarray, limit: int) -> list[tuple[str, float]]:
        if self._bm25 is None or permitted.size == 0:
            return []

        scores = np.asarray(self._bm25.get_scores(tokenize_query(query)), dtype=np.float64)
        permitted_scores = scores[permitted]

        # Zero-scoring chunks share no query term at all. Including them would pad the ranked list
        # with arbitrary documents that then earn a fusion contribution purely from position.
        nonzero = permitted_scores > 0.0
        if not nonzero.any():
            return []

        candidate_rows = permitted[nonzero]
        candidate_scores = permitted_scores[nonzero]
        order = np.argsort(-candidate_scores, kind="stable")[:limit]

        return [
            (self.chunks[int(candidate_rows[i])].chunk_id, float(candidate_scores[i]))
            for i in order
        ]

    def _vector_arm(self, query: str, permitted: np.ndarray, limit: int) -> list[tuple[str, float]]:
        if permitted.size == 0 or self.vectors.size == 0:
            return []

        # The same stopword-filtered query the keyword arm sees, so the two arms are answering the
        # same question rather than two slightly different ones.
        query_vector = self.embedder.embed([" ".join(tokenize_query(query))])[0]
        if not np.any(query_vector):
            return []

        similarities = self.vectors[permitted] @ query_vector

        # A near-zero cosine is noise, not a weak match, and with the hash embedder it is the
        # common case for a paraphrased question (BLOCKERS.md B1). Admitting those would let the
        # vector arm contribute rank signal it has not earned.
        nonzero = similarities > 1e-6
        if not nonzero.any():
            return []

        candidate_rows = permitted[nonzero]
        candidate_scores = similarities[nonzero]
        order = np.argsort(-candidate_scores, kind="stable")[:limit]

        return [
            (self.chunks[int(candidate_rows[i])].chunk_id, float(candidate_scores[i]))
            for i in order
        ]

    def _count_withheld(self, query: str, role: Role, top_k: int) -> int:
        """How many results the label filter actually removed from this role's top-k.

        The obvious implementation — count every disallowed chunk sharing a term with the query —
        is useless in practice. Almost any chunk shares *some* common word, so it reports ~50 of 256
        for every query and tells a user nothing except that the corpus is large.

        This instead answers the question the roles demo is really asking: **of the passages you
        would have seen, how many were withheld?** It fuses the unfiltered ranking and counts how
        many of its top ``top_k`` carry a label this role may not see. A guest asking about
        capitalisation gets 0 (nothing restricted is relevant); a guest asking about severance
        accrual gets a number, because governance genuinely removed the best answers.

        Only chunk ids and scores are touched. No withheld text is read, returned, or logged —
        see ``RetrievalResult.withheld_count`` for why the count alone is safe and a title is not.
        """
        if self._bm25 is None or not self.chunks:
            return 0

        every_index = np.arange(len(self.chunks), dtype=np.int64)
        unfiltered = reciprocal_rank_fusion(
            self._bm25_arm(query, every_index, ARM_CANDIDATES),
            self._vector_arm(query, every_index, ARM_CANDIDATES),
            k=self.rrf_k,
        )

        permitted = allowed_labels(role)
        return sum(
            1
            for result in unfiltered[:top_k]
            if self.chunks[self._by_id[result.key]].label not in permitted
        )

    # ---------------------------------------------------------- the interface --

    def search(self, query: str, *, role: Role, top_k: int = 6) -> RetrievalResult:
        permitted = self._permitted_indices(role)

        bm25_ranked = self._bm25_arm(query, permitted, ARM_CANDIDATES)
        vector_ranked = self._vector_arm(query, permitted, ARM_CANDIDATES)

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=self.rrf_k)

        hits: list[Hit] = []
        for result in fused[:top_k]:
            chunk = self.chunks[self._by_id[result.key]]
            # Belt and braces: the candidate sets were already label-filtered, so this can only
            # fire if a future edit breaks that. It is cheap, and the failure it guards against is
            # the one failure this system must not have.
            if chunk.label not in allowed_labels(role):  # pragma: no cover - defensive
                raise AssertionError(
                    f"label filter bypassed: {chunk.chunk_id} ({chunk.label}) surfaced for {role}"
                )
            hits.append(
                Hit(
                    chunk=chunk,
                    score=result.score,
                    bm25_rank=result.bm25_rank,
                    vector_rank=result.vector_rank,
                    bm25_score=result.bm25_score,
                    vector_score=result.vector_score,
                )
            )

        return RetrievalResult(
            query=query,
            role=role,
            hits=hits,
            withheld_count=self._count_withheld(query, role, top_k),
            allowed_labels=allowed_labels(role),
        )

    def get_chunk(self, chunk_id: str, *, role: Role) -> Chunk | None:
        """Label-checked lookup by id.

        Returns ``None`` for a chunk this role may not see — the same answer as for a chunk that
        does not exist. Distinguishing "forbidden" from "absent" would confirm the existence of
        restricted content to anyone probing ids, which is a disclosure in itself.
        """
        index = self._by_id.get(chunk_id)
        if index is None:
            return None
        chunk = self.chunks[index]
        if chunk.label not in allowed_labels(role):
            return None
        return chunk

    # ------------------------------------------------------------- reporting --

    def visible_policies(self, role: Role) -> list[str]:
        """Policy ids this role may browse — powers the Source Viewer's policy list."""
        permitted = allowed_labels(role)
        seen: dict[str, None] = {}
        for chunk in self.chunks:
            if chunk.label in permitted:
                seen.setdefault(chunk.policy_id, None)
        return list(seen)

    def hidden_policy_count(self, role: Role) -> int:
        """How many whole policies are invisible at this role. Count only, never identities."""
        permitted = allowed_labels(role)
        all_policies = {chunk.policy_id for chunk in self.chunks}
        visible = {chunk.policy_id for chunk in self.chunks if chunk.label in permitted}
        return len(all_policies - visible)

    def __len__(self) -> int:
        return len(self.chunks)
