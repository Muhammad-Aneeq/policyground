"""``POST /api/ask`` and ``GET /api/answer/{id}`` — spec 08 §7.

The response model is the discriminated union ``Answer | Refusal`` (PLAN.md **D-015**). Both are
returned with HTTP **200**. A refusal is a successful, correct outcome of the system working as
designed — returning 404 or 422 for one would make it an error in every client library, in every
log, and in every dashboard, which is precisely the framing spec 08 §1 argues against.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from policyground.answers.schema import Answer, AskResponse, Refusal
from policyground.api.deps import GraphDep, SessionDep, parse_role
from policyground.db import repo
from policyground.graph.build import PolicyGroundGraph
from policyground.labels import Role

router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    """Spec 08 §7: ``POST /api/ask {question, role}``."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    role: str = Role.STAFF.value
    #: Overriding top_k is exposed for the eval harness and the demo, bounded so a request cannot
    #: ask for the whole corpus and turn the context window into a denial-of-service surface.
    top_k: int | None = Field(default=None, ge=1, le=20)


@router.post("/ask", response_model=AskResponse, response_model_exclude_none=True)
def ask(
    request: AskRequest,
    graph: PolicyGroundGraph = GraphDep,
    session: Session = SessionDep,
) -> Answer | Refusal:
    """Answer a question, or refuse — and record either outcome.

    Persistence is not optional and not conditional. The admin refusal-rate metric (spec 08 §9) is
    computed from these rows, so a refusal that failed to log would quietly bias the headline number
    downward — the one direction that flatters the system.
    """
    role = parse_role(request.role)

    state = graph.run_state(request.question, role=role, top_k=request.top_k)
    response = graph.to_response(state)

    repo.record_response(session, response, state=state)
    return response


class StoredAnswer(BaseModel):
    """Spec 08 §7: ``GET /api/answer/{id}`` returns claims + citations."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    question: str
    role: str
    refused: bool
    refusal_reason: str | None
    sufficiency: float
    claims: list[dict]  # type: ignore[type-arg]
    citations: list[dict]  # type: ignore[type-arg]
    stripped_claims: int
    unknown_citation_ids: list[str]


@router.get("/answer/{query_id}", response_model=StoredAnswer)
def get_answer(query_id: str, session: Session = SessionDep) -> StoredAnswer:
    """Retrieve a stored answer by query id.

    Returns the **rendered** claims — the ones that survived the citation check — never the raw
    draft. The raw draft is retained in the database for audit and is deliberately not reachable
    from a public read endpoint: it is the one place fabricated citations exist, and serving it
    would undo the control that removed them.
    """
    query = repo.get_query(session, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown query id")

    stored = repo.get_answer(session, query_id)

    return StoredAnswer(
        query_id=query.id,
        question=query.text,
        role=query.role,
        refused=query.refused,
        refusal_reason=query.refusal_reason,
        sufficiency=query.sufficiency,
        claims=list(stored.claims_json) if stored else [],
        citations=list(stored.citations_json) if stored else [],
        stripped_claims=stored.stripped_claims if stored else 0,
        unknown_citation_ids=list(stored.unknown_citation_ids) if stored else [],
    )


class TraceStep(BaseModel):
    """One node of the graph run, for the UI's TraceTimeline."""

    model_config = ConfigDict(extra="forbid")

    node: str
    detail: str


class AskTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AskResponse
    node_path: list[str]
    steps: list[TraceStep]
    raw_claim_count: int
    stripped_claim_count: int


@router.post("/ask/trace", response_model=AskTraceResponse, tags=["debug"])
def ask_with_trace(
    request: AskRequest,
    graph: PolicyGroundGraph = GraphDep,
    session: Session = SessionDep,
) -> AskTraceResponse:
    """The same ask, plus which nodes ran and what each did.

    Powers the demo's "show me why" panel. It reports *counts* of raw and stripped claims rather
    than their text: the number is what makes the control visible, and the text is the fabricated
    content the strip exists to withhold.
    """
    role = parse_role(request.role)
    state = graph.run_state(request.question, role=role, top_k=request.top_k)
    response = graph.to_response(state)
    repo.record_response(session, response, state=state)

    assessment = state["assessment"]
    retrieval = state["retrieval"]

    details = {
        "retrieve": (
            f"{len(retrieval.hits)} passage(s) at role={retrieval.role}; "
            f"{retrieval.withheld_count} withheld by label filter"
        ),
        "assess_sufficiency": assessment.explain(),
        "refuse": f"below threshold {state.get('threshold')}; offering closest sections",
        "compose": f"{len(state.get('raw_claims', []))} draft claim(s)",
        "citation_check": (
            f"{len(state.get('claims', []))} kept, {len(state.get('dropped', []))} stripped"
        ),
    }

    return AskTraceResponse(
        response=response,
        node_path=list(state.get("node_path", [])),
        steps=[
            TraceStep(node=node, detail=details.get(node, ""))
            for node in state.get("node_path", [])
        ],
        raw_claim_count=len(state.get("raw_claims", [])),
        stripped_claim_count=len(state.get("dropped", [])),
    )
