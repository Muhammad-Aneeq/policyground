"""Wire the nodes into the LangGraph graph and run it.

Spec 08 §4 F3 draws the graph as:

    retrieve → assess_sufficiency → [insufficient: refuse] → compose → citation_check → return

That shape is built here and asserted in ``tests/test_graph.py`` against ``state["node_path"]``, so
"the implementation matches the spec diagram" is a test rather than a claim.

:class:`PolicyGroundGraph` wraps the compiled graph and converts terminal state into the public
``Answer``/``Refusal`` union. The conversion is the last place a refusal could accidentally acquire
answer-shaped fields, and it is written so it cannot: the two branches build different types, and
``Refusal`` has no ``claims`` field to populate (PLAN.md **D-015**).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from policyground.answers.schema import (
    REFUSAL_MESSAGE,
    Answer,
    Citation,
    Refusal,
    build_trace,
)
from policyground.config import Settings
from policyground.graph.llm import ChatClient, build_chat_client
from policyground.graph.nodes import (
    citation_check,
    closest_sections,
    make_assess_sufficiency,
    make_compose,
    make_retrieve,
    refuse,
    route_after_sufficiency,
)
from policyground.graph.state import GraphState
from policyground.labels import Role
from policyground.retrieval.base import Retriever
from policyground.retrieval.vocabulary import CorpusVocabulary

#: The node sequence spec 08 §8 specifies, asserted by the tests.
EXPECTED_ANSWER_PATH = ["retrieve", "assess_sufficiency", "compose", "citation_check"]
EXPECTED_REFUSAL_PATH = ["retrieve", "assess_sufficiency", "refuse"]

logger = logging.getLogger(__name__)


def build_graph(
    retriever: Retriever,
    client: ChatClient,
    *,
    threshold: float,
    default_top_k: int,
    vocabulary: CorpusVocabulary | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """Compile the StateGraph.

    ``refuse`` terminates immediately rather than falling through to compose. That is the whole
    economy of the refusal path: an off-corpus question costs one retrieval and no model call.
    """
    graph = StateGraph(GraphState)

    graph.add_node("retrieve", make_retrieve(retriever, default_top_k=default_top_k))
    graph.add_node(
        "assess_sufficiency",
        make_assess_sufficiency(threshold=threshold, vocabulary=vocabulary),
    )
    graph.add_node("refuse", refuse)
    graph.add_node("compose", make_compose(client))
    graph.add_node("citation_check", citation_check)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "assess_sufficiency")
    graph.add_conditional_edges(
        "assess_sufficiency",
        route_after_sufficiency,
        {"compose": "compose", "refuse": "refuse"},
    )
    graph.add_edge("compose", "citation_check")
    graph.add_edge("citation_check", END)
    graph.add_edge("refuse", END)

    return graph.compile()


@dataclass(slots=True)
class PolicyGroundGraph:
    """The answering service: run a question, get an ``Answer`` or a ``Refusal``."""

    retriever: Retriever
    client: ChatClient
    threshold: float
    default_top_k: int
    embedder_name: str
    degraded: bool
    vocabulary: CorpusVocabulary | None = None
    _compiled: CompiledStateGraph[GraphState, None, GraphState, GraphState] | None = None

    def __post_init__(self) -> None:
        self._compiled = build_graph(
            self.retriever,
            self.client,
            threshold=self.threshold,
            default_top_k=self.default_top_k,
            vocabulary=self.vocabulary,
        )

    @classmethod
    def from_settings(cls, settings: Settings, retriever: Retriever) -> PolicyGroundGraph:
        client = build_chat_client(settings)
        embedder_name = getattr(getattr(retriever, "embedder", None), "name", "unknown")

        # A missing vocabulary degrades the off-corpus signal rather than crashing, so an index
        # built before this artifact existed still runs. Ingestion always writes one.
        vocabulary: CorpusVocabulary | None = None
        if settings.vocabulary_path.exists():
            vocabulary = CorpusVocabulary.load(settings.vocabulary_path)
        else:
            logger.warning(
                "no corpus vocabulary at %s: off-corpus detection is weakened. "
                "Run `pg ingest --rebuild`.",
                settings.vocabulary_path,
            )

        return cls(
            retriever=retriever,
            client=client,
            threshold=settings.sufficiency_threshold,
            default_top_k=settings.retrieval_top_k,
            embedder_name=embedder_name,
            degraded=not (settings.has_openai_key or settings.has_azure_openai),
            vocabulary=vocabulary,
        )

    # ------------------------------------------------------------------ run --

    def run_state(
        self,
        question: str,
        *,
        role: Role,
        top_k: int | None = None,
        query_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> GraphState:
        """Execute the graph and return terminal state.

        Exposed separately from :meth:`ask` because the evals and the injection tests need to
        inspect what the *model drafted* (``raw_claims``) and which nodes ran, not only the
        sanitised response. Testing a safety control solely through its sanitised output would mean
        never observing the attempts it blocked.
        """
        initial: GraphState = {
            "question": question,
            "role": role,
            "top_k": top_k or self.default_top_k,
            "query_id": query_id or uuid.uuid4().hex[:16],
            "created_at": now or dt.datetime.now(dt.UTC),
            "node_path": [],
            "raw_claims": [],
            "claims": [],
            "dropped": [],
            "embedder": self.embedder_name,
            "degraded": self.degraded,
            "extras": {},
        }
        assert self._compiled is not None
        # LangGraph types the return as a plain mapping; GraphState is a TypedDict over the
        # same keys, and every node in this graph returns GraphState fragments.
        return cast("GraphState", self._compiled.invoke(initial))

    def ask(
        self,
        question: str,
        *,
        role: Role,
        top_k: int | None = None,
        query_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> Answer | Refusal:
        """The public entry point. Returns one of two types, never a nullable answer."""
        state = self.run_state(question, role=role, top_k=top_k, query_id=query_id, now=now)
        return self.to_response(state)

    # ------------------------------------------------------------- rendering --

    def to_response(self, state: GraphState) -> Answer | Refusal:
        """Terminal state → the public response union.

        The two branches construct different types. There is no shared object that starts as an
        answer and is downgraded, because that is precisely how a refusal ends up carrying
        answer-shaped fields that a careless UI then renders.
        """
        result = state["retrieval"]
        assessment = state["assessment"]

        trace = build_trace(
            result,
            backend=state.get("backend", "unknown"),
            top_k=state.get("top_k", self.default_top_k),
            sufficiency=assessment.score,
            threshold=state.get("threshold", self.threshold),
            embedder=state.get("embedder", self.embedder_name),
            degraded=state.get("degraded", self.degraded),
        )

        query_id = state["query_id"]
        question = state["question"]
        created_at = state["created_at"]

        if state.get("refused") or not state.get("claims"):
            reason = state.get("refusal_reason") or "insufficient_evidence"
            return Refusal(
                query_id=query_id,
                question=question,
                message=REFUSAL_MESSAGE,
                reason=reason,  # type: ignore[arg-type]
                closest_sections=closest_sections(state),
                trace=trace,
                created_at=created_at,
            )

        claims = state["claims"]
        cited = {cid for claim in claims for cid in claim.citation_ids}

        # Only chunks actually cited become citations. Returning all `top_k` would put passages in
        # the sources panel that support nothing in the answer, which teaches a reader that the
        # panel is decorative rather than evidential.
        citations = [
            Citation.from_chunk(chunk) for chunk in result.chunks if chunk.chunk_id in cited
        ]

        return Answer(
            query_id=query_id,
            question=question,
            claims=claims,
            citations=citations,
            trace=trace,
            stripped_claims=len(state.get("dropped", [])),
            created_at=created_at,
        )
