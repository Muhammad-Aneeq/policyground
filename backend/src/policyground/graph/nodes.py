"""The five graph nodes from spec 08 §8.

    retrieve → assess_sufficiency → [insufficient: refuse] → compose → citation_check → return

Each node is a plain function from state to a state update. They are written to be callable
directly — the tests exercise most of them without building a graph at all, because a failure in
``citation_check`` should point at ``citation_check`` and not at a LangGraph traversal.

The one structural rule that spans nodes: **there are two independent paths to a refusal.**
``assess_sufficiency`` refuses before the model is ever called (cheap, and the common case for an
off-corpus question), and ``citation_check`` refuses after it, when nothing the model said survived.
The second path is what makes "no answer without citations, by construction" (spec 08 §11) true even
when retrieval looked adequate and the model then failed to ground itself.
"""

from __future__ import annotations

import logging

from policyground.answers.citation_check import strip_uncited
from policyground.answers.schema import ClosestSection
from policyground.graph.llm import ChatClient
from policyground.graph.state import GraphState
from policyground.graph.sufficiency import assess
from policyground.retrieval.base import Retriever
from policyground.retrieval.vocabulary import CorpusVocabulary

logger = logging.getLogger(__name__)

#: How many near-misses a refusal offers (spec 08 §4 F4: "+ closest sections").
CLOSEST_SECTIONS = 3


def _record(state: GraphState, node: str) -> list[str]:
    return [*state.get("node_path", []), node]


def make_retrieve(retriever: Retriever, *, default_top_k: int = 6):  # type: ignore[no-untyped-def]
    """Node 1: hybrid retrieval, label-filtered by the session role.

    The role is passed straight through to the retriever, which is where filtering happens
    (PLAN.md **D-003**). This node has no ability to widen access even if it wanted to — there is no
    parameter for it on the ``Retriever`` interface.
    """

    def retrieve(state: GraphState) -> GraphState:
        top_k = state.get("top_k") or default_top_k
        result = retriever.search(state["question"], role=state["role"], top_k=top_k)

        return {
            "retrieval": result,
            "top_k": top_k,
            "backend": retriever.backend_name,
            "node_path": _record(state, "retrieve"),
        }

    return retrieve


def make_assess_sufficiency(  # type: ignore[no-untyped-def]
    *,
    threshold: float,
    vocabulary: CorpusVocabulary | None = None,
):
    """Node 2: score the evidence and decide whether answering is warranted.

    Deterministic (PLAN.md **D-006**). The threshold is injected rather than read from settings here
    so the eval harness can sweep it during calibration without mutating global configuration.
    """

    def assess_sufficiency(state: GraphState) -> GraphState:
        result = state["retrieval"]
        assessment = assess(result, vocabulary)
        sufficient = bool(result.hits) and assessment.score >= threshold

        if not sufficient:
            logger.info(
                "refusing %r for role=%s: %s",
                state["question"][:80],
                state["role"],
                assessment.explain(),
            )

        return {
            "assessment": assessment,
            "sufficient": sufficient,
            "threshold": threshold,
            "node_path": _record(state, "assess_sufficiency"),
        }

    return assess_sufficiency


def route_after_sufficiency(state: GraphState) -> str:
    """Conditional edge: the branch spec 08 §8 draws as ``[insufficient: refuse]``."""
    return "compose" if state.get("sufficient") else "refuse"


def refuse(state: GraphState) -> GraphState:
    """Node 3: the refusal path. Not an error path — a first-class outcome.

    Sets ``refusal_reason`` so the eval can distinguish *why* the system refused. "Nothing was
    retrieved at all" and "things were retrieved but none of them matched well" look identical to a
    user and are very different signals to whoever maintains the corpus.
    """
    result = state["retrieval"]
    reason = "empty_retrieval" if not result.hits else "insufficient_evidence"

    return {
        "refused": True,
        "refusal_reason": reason,
        "claims": [],
        "node_path": _record(state, "refuse"),
    }


def make_compose(client: ChatClient):  # type: ignore[no-untyped-def]
    """Node 4: draft claims from the retrieved passages only.

    The result is stored as ``raw_claims``, never as ``claims``. The naming is deliberate: nothing
    downstream should be able to reach for model output that has not passed ``citation_check``, and
    a reader of this file should be able to see that at a glance.

    A compose failure is caught and turned into zero claims rather than an exception. An API error
    mid-demo should produce an honest refusal, not a 500 — and zero claims routes to exactly that.
    """

    def compose(state: GraphState) -> GraphState:
        chunks = state["retrieval"].chunks
        try:
            raw = client.compose(state["question"], chunks)
        except Exception as exc:
            logger.exception("compose failed, degrading to refusal: %s", exc)
            raw = []

        return {
            "raw_claims": raw,
            "composer": client.name,
            "node_path": _record(state, "compose"),
        }

    return compose


def citation_check(state: GraphState) -> GraphState:
    """Node 5: strip unsupported claims; refuse if nothing survives.

    This is where spec 08 §4 F3's "uncited claims stripped before render" actually happens. The
    heavy lifting is in :func:`policyground.answers.citation_check.strip_uncited`, kept as a pure
    function so it can be tested against adversarial fixtures rather than only against whatever the
    composer emitted.
    """
    raw = state.get("raw_claims", [])
    retrieved_ids = state["retrieval"].chunk_ids

    result = strip_uncited(raw, retrieved_ids)

    update: GraphState = {
        "claims": result.kept,
        "dropped": result.dropped,
        "unknown_citation_ids": sorted(result.unknown_ids),
        "node_path": _record(state, "citation_check"),
    }

    if result.unknown_ids:
        # Worth a warning rather than silence: a fabricated id means the model asserted something
        # and attributed it to a source that does not exist. The strip contained it, but the
        # attempt is a signal about the model or the prompt.
        logger.warning(
            "compose cited %d unknown id(s) for %r: %s",
            len(result.unknown_ids),
            state["question"][:60],
            sorted(result.unknown_ids),
        )

    if not result.kept:
        # Either everything was stripped, or the model produced nothing. Both mean the same thing
        # to the reader: there is no cited answer, so there is no answer.
        update["refused"] = True
        update["refusal_reason"] = (
            "no_surviving_claims" if result.dropped else "insufficient_evidence"
        )
    else:
        update["refused"] = False

    return update


def closest_sections(state: GraphState, limit: int = CLOSEST_SECTIONS) -> list[ClosestSection]:
    """Near-misses to offer alongside a refusal (spec 08 §4 F4).

    Drawn from the *retrieved* hits, which are already label-filtered — so a refusal can never
    become a channel that names a restricted policy an unprivileged role could not otherwise see.
    That is a real risk with "did you mean?" features and is worth being explicit about.

    De-duplicated by policy so three sections of one policy do not crowd out two other candidates.
    """
    seen: set[str] = set()
    suggestions: list[ClosestSection] = []

    for hit in state["retrieval"].hits:
        if hit.chunk.policy_id in seen:
            continue
        seen.add(hit.chunk.policy_id)
        suggestions.append(
            ClosestSection(
                policy_id=hit.chunk.policy_id,
                policy_title=hit.chunk.policy_title,
                section_path=hit.chunk.section_path,
                score=round(hit.score, 6),
            )
        )
        if len(suggestions) >= limit:
            break

    return suggestions
