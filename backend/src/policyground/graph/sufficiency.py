"""Does the retrieved evidence actually support answering? The refusal decision, made in code.

Spec 08 §8: *"Sufficiency assessor = small model + retrieval-score heuristic (cheap,
deterministic-leaning)."* This implementation is fully deterministic (PLAN.md **D-006**): CI must
run offline and refusal correctness is a gated metric, the refusal decision is the product's most
visible behaviour and should be reproducible rather than a coin flip, and refusing should cost
nothing — off-corpus questions are exactly the ones you do not want to pay a model to answer.

## The signal that does not work, and why it is absent

The obvious candidate is "how strong was the top retrieval score?". With RRF that is **useless**,
and measurably so: RRF scores a document by ``1/(k+rank)``, so the top result always sits within a
whisker of the ceiling whether it is a perfect match or unrelated. Measured across the question
bank, the first version of this module reported ``rank_strength`` of 0.98-0.99 for *every* query
including "What is our policy on cryptocurrency custody?" — contributing a flat, uninformative
0.30 to every score and pushing off-corpus questions above the refusal threshold.

That component is gone. What replaced it are two signals that actually vary with match quality.

## The three signals used

1. **IDF-weighted coverage** (dominant). What fraction of the question's *informative* content is
   present in the retrieved passages, weighting each term by how rare it is in the corpus. This is
   the fix for the failure above: "cryptocurrency" and "biological" are unknown to the corpus and
   therefore carry the highest weight, so failing to match them crushes the score — while matching
   "policy", which occurs in all 30 documents, is worth almost nothing.
2. **Lexical match strength.** The top BM25 score, saturated. Unlike an RRF score, BM25 magnitude
   reflects how well the query actually matched, so it distinguishes "best of a weak field" from
   "genuinely strong match".
3. **Agreement.** Whether both arms found the top result, and how much of the result set clusters
   on one policy. A question the corpus answers pulls several sections of the *same* policy; a
   question it does not pulls one section each from five unrelated ones.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from policyground.retrieval.base import RetrievalResult
from policyground.retrieval.embeddings import tokenize, tokenize_query
from policyground.retrieval.vocabulary import CorpusVocabulary

#: Coverage dominates: it is the signal that most directly separates "the corpus discusses this"
#: from "it does not", and the only one that does not degrade when the vector arm is a lexical
#: stand-in (BLOCKERS.md B1).
W_COVERAGE = 0.65
W_LEXICAL = 0.20
W_AGREEMENT = 0.15

#: Coverage is measured over the top few chunks only. Over all of `top_k`, a large result set
#: accumulates the query's words across unrelated documents and manufactures coverage that no
#: single passage actually provides.
COVERAGE_DEPTH = 3

#: Ceiling on the unknown-term penalty. At 0.5, a question made entirely of words the corpus
#: has never seen keeps half its score rather than collapsing to zero — enough to refuse, not
#: so much that the penalty alone decides every outcome and the other signals stop mattering.
MAX_UNKNOWN_PENALTY = 0.5

#: BM25 score at which lexical strength is treated as ~0.76 (tanh midpoint-ish). Chosen from the
#: observed distribution on this corpus: a solid single-section match scores around 8-15.
BM25_SATURATION = 10.0


@dataclass(frozen=True, slots=True)
class SufficiencyAssessment:
    """The score and its components, so a refusal can be explained rather than merely asserted."""

    score: float
    coverage: float
    lexical: float
    agreement: float
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    unknown_terms: tuple[str, ...]

    def explain(self) -> str:
        parts = [
            f"sufficiency={self.score:.3f}",
            f"coverage={self.coverage:.2f}",
            f"lexical={self.lexical:.2f}",
            f"agreement={self.agreement:.2f}",
        ]
        if self.unknown_terms:
            parts.append(f"not in corpus: {', '.join(self.unknown_terms)}")
        elif self.missing_terms:
            parts.append(f"unmatched: {', '.join(self.missing_terms)}")
        return " | ".join(parts)


def assess(
    result: RetrievalResult,
    vocabulary: CorpusVocabulary | None = None,
    *,
    coverage_depth: int = COVERAGE_DEPTH,
) -> SufficiencyAssessment:
    """Score how well the retrieved evidence supports answering ``result.query``.

    Returns a score in [0, 1]. This function deliberately does not know the refusal threshold: the
    *measurement* lives here and the *decision* lives in the graph, which is what lets the threshold
    be calibrated against the question bank without touching this logic (PLAN.md **D-019**).

    ``vocabulary`` is optional so the assessor degrades rather than crashes if an index predates it;
    without it, terms are weighted equally and the off-corpus signal is much weaker. Ingestion
    always writes one.
    """
    query_terms = list(dict.fromkeys(tokenize_query(result.query)))

    if not result.hits or not query_terms:
        unknown = vocabulary.unknown_terms(query_terms) if vocabulary else []
        return SufficiencyAssessment(
            score=0.0,
            coverage=0.0,
            lexical=0.0,
            agreement=0.0,
            matched_terms=(),
            missing_terms=tuple(query_terms),
            unknown_terms=tuple(unknown),
        )

    # --- 1. IDF-weighted coverage -----------------------------------------
    top_tokens = set(
        tokenize(" ".join(hit.chunk.indexable_text for hit in result.hits[:coverage_depth]))
    )

    matched: list[str] = []
    missing: list[str] = []
    matched_weight = 0.0
    total_weight = 0.0

    for term in query_terms:
        weight = vocabulary.idf(term) if vocabulary else 1.0
        total_weight += weight
        if _term_present(term, top_tokens):
            matched.append(term)
            matched_weight += weight
        else:
            missing.append(term)

    coverage = matched_weight / total_weight if total_weight else 0.0

    # --- 2. lexical match strength ----------------------------------------
    # BM25 magnitude, unlike an RRF score, reflects how well the query actually matched.
    # tanh saturates so one enormous score cannot dominate, and so the value stays in [0, 1].
    top_bm25 = max((hit.bm25_score or 0.0) for hit in result.hits)
    lexical = math.tanh(top_bm25 / BM25_SATURATION)

    # --- 3. agreement ------------------------------------------------------
    arms_agree = 1.0 if len(result.hits[0].arms) >= 2 else 0.35
    policy_counts = Counter(hit.chunk.policy_id for hit in result.hits)
    dominant_share = policy_counts.most_common(1)[0][1] / len(result.hits)
    agreement = 0.6 * arms_agree + 0.4 * dominant_share

    score = W_COVERAGE * coverage + W_LEXICAL * lexical + W_AGREEMENT * agreement

    # --- 4. unknown-term penalty ------------------------------------------
    # A word the corpus has *never contained* is the strongest off-corpus evidence available, and
    # coverage alone under-weights it when the rest of the question matches something real. Two
    # measured failures motivated this: "What is the policy on **space** travel?" scored 0.54 and
    # "What is our **cybersecurity** incident escalation procedure?" scored 0.49 — both above the
    # refusal threshold — because "travel" and "escalation" are strong lexical matches in this
    # corpus. A purely lexical system cannot tell space travel from business travel; naming the
    # unknown term is how it can.
    #
    # Multiplicative and capped, deliberately. A question with one unfamiliar word alongside
    # several familiar ones is still answerable, so this attenuates rather than vetoes.
    unknown = vocabulary.unknown_terms(query_terms) if vocabulary else []
    if unknown and vocabulary is not None:
        unknown_weight = sum(vocabulary.idf(term) for term in unknown)
        unknown_share = unknown_weight / total_weight if total_weight else 0.0
        score *= 1.0 - MAX_UNKNOWN_PENALTY * min(1.0, unknown_share)

    return SufficiencyAssessment(
        score=round(min(1.0, max(0.0, score)), 6),
        coverage=round(coverage, 4),
        lexical=round(lexical, 4),
        agreement=round(agreement, 4),
        matched_terms=tuple(matched),
        missing_terms=tuple(missing),
        unknown_terms=tuple(unknown),
    )


def _term_present(term: str, tokens: set[str]) -> bool:
    """Whether a query term appears, allowing a simple morphological near-match.

    "capitalisation" should count as present when the text says "capitalised", and "night" when it
    says "nightly". Without this, coverage systematically under-reports and the system refuses
    questions it can answer — and spec 08 §10 measures false refusals as seriously as wrong answers.

    Deliberately not a stemmer: a five-character prefix rule is predictable and dependency-free,
    where a stemmer would introduce vocabulary behaviour the corpus authors cannot see or reason
    about.
    """
    if term in tokens:
        return True
    if len(term) < 5:
        return False
    stem = term[:5]
    return any(token.startswith(stem) for token in tokens if len(token) >= 5)
