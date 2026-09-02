"""The graph's state object.

A plain ``TypedDict`` because that is what LangGraph passes between nodes. Two things are worth
noting about what it carries:

* ``node_path`` records the nodes actually visited. It is asserted in the tests against spec 08 §8's
  stated sequence, which turns "the graph matches the spec" from a claim in a README into a test.
  It also drives the TraceTimeline in the UI.
* ``raw_claims`` (the model's draft) is kept alongside ``claims`` (what survived the strip). Keeping
  both is what makes the citation control *auditable*: the admin view and the injection tests can
  see what the model tried to say, not only what was allowed through.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, TypedDict

from policyground.answers.citation_check import DroppedClaim
from policyground.answers.schema import Claim
from policyground.graph.sufficiency import SufficiencyAssessment
from policyground.labels import Role
from policyground.retrieval.base import RetrievalResult


class GraphState(TypedDict, total=False):
    """State threaded through the five nodes of spec 08 section 8."""

    # --- inputs ---
    question: str
    role: Role
    top_k: int
    query_id: str
    created_at: dt.datetime

    # --- retrieve ---
    retrieval: RetrievalResult

    # --- assess_sufficiency ---
    assessment: SufficiencyAssessment
    sufficient: bool

    # --- compose ---
    #: The model's draft, before any checking. Deliberately retained — see module docstring.
    raw_claims: list[Claim]

    # --- citation_check ---
    claims: list[Claim]
    dropped: list[DroppedClaim]
    unknown_citation_ids: list[str]

    # --- outcome ---
    refused: bool
    refusal_reason: str
    node_path: list[str]

    # --- diagnostics carried into the response trace ---
    backend: str
    embedder: str
    composer: str
    degraded: bool
    threshold: float
    extras: dict[str, Any]
