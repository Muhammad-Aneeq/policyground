"""Embedders: the real one, and the deterministic stand-in this build actually runs on.

There is no `OPENAI_API_KEY` in this environment (BLOCKERS.md **B1**), so `HashEmbedder` is what
produces every committed number. It is important to be exact about what that means:

**What HashEmbedder is.** Feature hashing over word unigrams and character n-grams, with sublinear
term weighting, projected into a fixed-dimension vector and L2-normalised. Cosine similarity
between two of its vectors measures *lexical overlap at the sub-word level* — so it does catch
"capitalisation"/"capitalization", plurals, and shared word stems that exact keyword matching
misses.

**What HashEmbedder is not.** It is not semantic. "How much can I spend on a hotel?" and "nightly
room rate cap" share almost no surface form, and the hash embedder will score them near zero where
a real embedding model would score them highly. That failure mode is *measured* rather than hidden:
it pushes cases toward refusal, and the false-refusal rate on answerable questions is one of the
headline eval metrics (PLAN.md P5). The number reported in this repo is therefore a floor, not a
ceiling.

Swapping in the real embedder is an environment variable, not a code change: both satisfy
:class:`Embedder`, both are selected by :func:`build_embedder`, and the ingest artifact records
which one built it so an index can never be silently queried with the wrong embedder.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Protocol, runtime_checkable

import numpy as np

from policyground.config import Settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
#: Character n-gram width. 4 is long enough to be discriminative and short enough that
#: "capitalisation" and "capitalization" still share most of their grams.
_CHAR_NGRAM = 4


@runtime_checkable
class Embedder(Protocol):
    """Text to unit-norm vector."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an ``(len(texts), dim)`` float32 array of L2-normalised row vectors."""
        ...


#: Function words stripped from *queries* only. Deliberately small and closed — a long stopword
#: list starts deleting meaning ("no", "not", "above", "before" all matter in a policy corpus).
#:
#: Why queries and not documents: BM25 weights a term by how often it appears in a document, and
#: policy prose is dense with "per" ("per diem", "per night", "per attendee"). Asking "how much can
#: I claim for a hotel per night?" therefore scored the *Meals* section above *Accommodation* —
#: not because meals were more relevant, but because that section says "per" more often. Removing
#: the function words from the question leaves the terms that carry the intent. Document tokens are
#: left intact so BM25's length normalisation and document frequencies stay honest.
QUERY_STOPWORDS = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "many",
        "may",
        "me",
        "much",
        "my",
        "of",
        "on",
        "or",
        "our",
        "per",
        "please",
        "should",
        "so",
        "some",
        "tell",
        "that",
        "the",
        "then",
        "there",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. Shared with the BM25 arm so both see the same vocabulary."""
    return _TOKEN_RE.findall(text.lower())


def tokenize_query(text: str) -> list[str]:
    """Query tokens with function words removed — see :data:`QUERY_STOPWORDS`.

    Falls back to the unfiltered tokens when filtering would empty the query. A question made
    entirely of stopwords should retrieve badly and then refuse, but it must not crash on the way
    there, and an empty token list would make BM25 score every document identically.
    """
    tokens = tokenize(text)
    filtered = [token for token in tokens if token not in QUERY_STOPWORDS]
    return filtered or tokens


#: Prefix length for morphological near-matching. Shared by the sufficiency assessor, the offline
#: composer and the corpus vocabulary, so all three agree on what "this term appears" means. Three
#: separate notions of matching would give a system that scores a term as covered, reports it as
#: unknown to the corpus, and fails to extract the sentence containing it — all at once.
NEAR_MATCH_PREFIX = 5


def term_matches(term: str, tokens: set[str]) -> bool:
    """Whether ``term`` appears in ``tokens``, allowing a simple morphological near-match.

    "capitalisation" counts as present when the text says "capitalised", and "night" when it says
    "nightly". Without it, coverage under-reports and the system refuses questions it can answer —
    and spec 08 §10 treats a false refusal as seriously as a wrong answer.

    Deliberately not a stemmer: a five-character prefix rule is predictable and dependency-free,
    where a stemmer would introduce vocabulary behaviour the corpus authors cannot see or reason
    about.
    """
    if term in tokens:
        return True
    if len(term) < NEAR_MATCH_PREFIX:
        return False
    stem = term[:NEAR_MATCH_PREFIX]
    return any(token.startswith(stem) for token in tokens if len(token) >= NEAR_MATCH_PREFIX)


def _char_ngrams(token: str, width: int = _CHAR_NGRAM) -> list[str]:
    """Character n-grams of a single token, padded so short tokens still contribute."""
    padded = f"#{token}#"
    if len(padded) <= width:
        return [padded]
    return [padded[i : i + width] for i in range(len(padded) - width + 1)]


class HashEmbedder:
    """Deterministic feature-hashing embedder — the offline fallback (PLAN.md **D-004**).

    Determinism is the point and is load-bearing for reproducibility: it uses BLAKE2b rather than
    Python's built-in ``hash``, which is randomised per process by PYTHONHASHSEED and would produce
    a different index on every run.
    """

    name = "hash-embedder-v1"

    def __init__(self, dim: int = 384) -> None:
        if dim < 32:
            raise ValueError("embedding dim must be at least 32")
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        """Map a feature to (index, sign).

        The signed variant of feature hashing: the sign makes collisions cancel on average instead
        of always adding, which measurably reduces the distortion from sharing 384 buckets among
        tens of thousands of features.
        """
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def embed_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize(text)
        if not tokens:
            return vector

        counts: Counter[str] = Counter()
        for token in tokens:
            counts[f"w:{token}"] += 1
            for gram in _char_ngrams(token):
                counts[f"c:{gram}"] += 1

        for feature, count in counts.items():
            index, sign = self._bucket(feature)
            # Sublinear (log) term weighting: a word used ten times is more relevant than one
            # used once, but not ten times more -- the intuition BM25 encodes on the other arm.
            vector[index] += sign * (1.0 + math.log(count))

        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector /= norm
        return vector

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.embed_one(text) for text in texts]).astype(np.float32)


class OpenAIEmbedder:
    """The real embedder. Selected automatically when a key is present.

    Untested against the live API in this build (BLOCKERS.md **B1**) — there is no key to test
    with. Kept deliberately minimal so there is little to be wrong: batched calls, explicit
    normalisation, no retry cleverness that would mask an error during a demo.
    """

    def __init__(self, model: str, api_key: str, dim: int = 1536, batch_size: int = 128) -> None:
        self.name = f"openai:{model}"
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self._api_key = api_key

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        from openai import OpenAI

        client = OpenAI(api_key=self._api_key)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = client.embeddings.create(model=self.model, input=batch)
            vectors.extend(item.embedding for item in response.data)

        array = np.asarray(vectors, dtype=np.float32)
        norms: np.ndarray = np.linalg.norm(array, axis=1, keepdims=True)
        # The API already returns unit vectors; normalising anyway means cosine similarity is a
        # dot product regardless of what a future model version does.
        normalised: np.ndarray = array / np.where(norms == 0.0, 1.0, norms)
        return normalised


def build_embedder(settings: Settings) -> Embedder:
    """Pick the embedder from the environment, never raising for a missing key.

    A missing credential selects the documented fallback rather than failing, because the whole
    product must run end to end offline. Which one was chosen is logged at ingest and recorded in
    the index artifact, so a reader can always tell what produced a number.
    """
    if settings.has_openai_key:
        assert settings.openai_api_key is not None
        return OpenAIEmbedder(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
        )
    return HashEmbedder(dim=settings.embedding_dim)


def cosine_scores(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one unit vector against a matrix of unit vectors.

    Both sides are already L2-normalised, so this is a dot product. Returns an empty array for an
    empty matrix rather than raising — an unpopulated index is a legitimate state during a rebuild.
    """
    if matrix.size == 0:
        return np.zeros(0, dtype=np.float32)
    scores: np.ndarray = matrix @ query_vector
    return scores
