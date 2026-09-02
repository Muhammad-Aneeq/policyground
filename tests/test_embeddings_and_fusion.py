"""The two retrieval arms and the fusion that combines them.

The determinism tests matter more than they look. ``HashEmbedder`` uses BLAKE2b rather than
Python's ``hash`` precisely because the latter is salted per process — with it, every ``pg ingest``
would produce a different index, and no eval number would be reproducible across runs. The
subprocess test below is the only way to actually catch that regression, since within one process a
salted hash is perfectly self-consistent.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from policyground.retrieval.embeddings import (
    QUERY_STOPWORDS,
    HashEmbedder,
    cosine_scores,
    tokenize,
    tokenize_query,
)
from policyground.retrieval.fusion import (
    DEFAULT_RRF_K,
    max_possible_score,
    reciprocal_rank_fusion,
)

# ------------------------------------------------------------- embeddings --


def test_vectors_are_unit_norm() -> None:
    embedder = HashEmbedder(dim=128)
    matrix = embedder.embed(["capitalisation threshold", "approval matrix", "petty cash float"])
    norms = np.linalg.norm(matrix, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_dimension_is_respected() -> None:
    assert HashEmbedder(dim=64).embed(["x"]).shape == (1, 64)


def test_identical_text_yields_identical_vectors() -> None:
    embedder = HashEmbedder(dim=128)
    a = embedder.embed(["the capitalisation threshold is USD 5,000"])
    b = embedder.embed(["the capitalisation threshold is USD 5,000"])
    assert np.array_equal(a, b)


def test_embeddings_are_stable_across_processes() -> None:
    """The regression that a same-process test cannot catch (PYTHONHASHSEED randomisation)."""
    code = (
        "from policyground.retrieval.embeddings import HashEmbedder;"
        "import numpy as np;"
        "v = HashEmbedder(dim=64).embed(['three-way match tolerance'])[0];"
        "print(','.join(f'{x:.6f}' for x in v[:8]))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(outputs) == 1, f"HashEmbedder is not deterministic across processes: {outputs}"


def test_character_ngrams_bridge_spelling_variants() -> None:
    """The one thing a hash embedder buys over pure keyword matching."""
    embedder = HashEmbedder(dim=512)
    british, american, unrelated = embedder.embed(
        ["capitalisation threshold", "capitalization threshold", "petty cash custodian"]
    )
    assert float(british @ american) > float(british @ unrelated)


def test_an_empty_string_embeds_to_zero_rather_than_raising() -> None:
    vector = HashEmbedder(dim=64).embed([""])[0]
    assert not np.any(vector)


def test_embedding_no_texts_returns_an_empty_matrix() -> None:
    assert HashEmbedder(dim=64).embed([]).shape == (0, 64)


def test_cosine_scores_handle_an_empty_index() -> None:
    """An unpopulated index is a legitimate state mid-rebuild, not an error."""
    assert (
        cosine_scores(np.zeros(8, dtype=np.float32), np.zeros((0, 8), dtype=np.float32)).size == 0
    )


# --------------------------------------------------------------- tokenizer --


def test_tokenize_lowercases_and_drops_punctuation() -> None:
    assert tokenize("USD 5,000 — Capitalisation!") == ["usd", "5", "000", "capitalisation"]


def test_query_tokenizer_strips_function_words() -> None:
    assert tokenize_query("How much can I claim for a hotel per night?") == [
        "claim",
        "hotel",
        "night",
    ]


def test_query_tokenizer_falls_back_when_everything_is_a_stopword() -> None:
    """An all-stopword query must not empty out — BM25 would then score every document equally."""
    assert tokenize_query("what is the how much") == ["what", "is", "the", "how", "much"]


def test_stopwords_do_not_include_words_that_carry_policy_meaning() -> None:
    """ "not", "above", "below" and "no" change the meaning of a threshold sentence entirely."""
    for word in ("not", "no", "above", "below", "before", "after", "under", "over"):
        assert word not in QUERY_STOPWORDS


def test_indexable_text_includes_provenance(chunks: list) -> None:  # type: ignore[type-arg]
    """A section must be findable by the term that names it, not only by its body."""
    accommodation = next(
        c for c in chunks if c.policy_id == "PG-0006" and "Accommodation" in c.section_path
    )
    rendered = accommodation.indexable_text
    assert accommodation.policy_title in rendered
    assert accommodation.section_path in rendered
    assert rendered.endswith(accommodation.text)


# ------------------------------------------------------------------ fusion --


def test_rrf_matches_a_hand_computed_fixture() -> None:
    fused = reciprocal_rank_fusion([("a", 9.0), ("b", 4.0)], [("b", 0.9), ("c", 0.5)], k=60)
    scores = {result.key: result.score for result in fused}

    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 62)
    # b is found by both arms and wins despite being second on each.
    assert fused[0].key == "b"


def test_a_document_found_by_one_arm_still_surfaces() -> None:
    """The property that makes hybrid worth having — and that matters most here.

    With the fallback embedder the vector arm is weak (BLOCKERS.md B1), so a question it cannot
    place must still be answerable from the keyword arm alone.
    """
    fused = reciprocal_rank_fusion([("keyword-only", 5.0)], [], k=60)
    assert [result.key for result in fused] == ["keyword-only"]
    assert fused[0].vector_rank is None
    assert fused[0].bm25_rank == 1


def test_per_arm_provenance_is_retained() -> None:
    fused = reciprocal_rank_fusion([("a", 9.0)], [("a", 0.8)], k=60)[0]
    assert fused.bm25_rank == 1 and fused.vector_rank == 1
    assert fused.bm25_score == 9.0 and fused.vector_score == 0.8


def test_ties_break_deterministically_by_key() -> None:
    """Without this, an index rebuild could reorder citations and look like an eval regression."""
    forward = reciprocal_rank_fusion([("b", 1.0), ("a", 1.0)], [], k=60)
    assert [r.key for r in forward] == ["b", "a"], "input order defines rank, not the tie-break"

    tied = reciprocal_rank_fusion([("b", 1.0)], [("a", 1.0)], k=60)
    assert [r.key for r in tied] == ["a", "b"], "equal scores must sort by key"


def test_fusing_two_empty_arms_returns_nothing() -> None:
    assert reciprocal_rank_fusion([], [], k=60) == []


def test_rrf_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k must be"):
        reciprocal_rank_fusion([("a", 1.0)], [], k=0)


def test_max_possible_score_bounds_a_top_ranked_document() -> None:
    """The normaliser the sufficiency assessor needs a bounded quantity from."""
    best = reciprocal_rank_fusion([("a", 1.0)], [("a", 1.0)], k=DEFAULT_RRF_K)[0]
    assert best.score == pytest.approx(max_possible_score(DEFAULT_RRF_K))
    assert 0.0 < best.score <= 1.0
