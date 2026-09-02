"""The answer schema. Citations are structural here, not requested politely in a prompt.

Spec 08 §4 F3: *"answer schema = claims[{text, citation_ids[]}]; uncited claims stripped before
render."* Two decisions in this file do the work:

**1. `citation_ids` is required on `Claim`.** Not optional-with-a-default. A model response that
omits it fails validation rather than producing a claim that renders as evidence-backed prose while
citing nothing.

**2. `Answer` and `Refusal` are separate types in a discriminated union, and `Refusal` has no
`claims` field at all** (PLAN.md **D-015**). Spec 08 §9 requires refusals to be styled
"distinctly, never like a normal answer". A single response type with `refused: bool` makes that a
convention the UI must remember to honour; two types make it a thing the UI *cannot* get wrong,
because a refusal has nothing to render in answer shape. The guarantee moves from discipline to
the type system.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from policyground.labels import Label, Role
from policyground.retrieval.base import Chunk, RetrievalResult


class Citation(BaseModel):
    """A retrieved passage offered as evidence, in the shape the UI needs to render it.

    Carries ``start``/``end`` offsets so the Source Viewer highlights the exact passage rather than
    re-finding it by string match (PLAN.md **D-017**), and carries ``label`` so the UI can show
    *which* sensitivity tier an answer drew on — a controller should be able to see at a glance that
    an answer rests on restricted material.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str
    policy_id: str
    policy_title: str
    section_path: str
    label: Label
    version: str
    snippet: str
    start: int
    end: int

    @classmethod
    def from_chunk(cls, chunk: Chunk, *, snippet_chars: int = 400) -> Citation:
        text = chunk.text.strip()
        snippet = text if len(text) <= snippet_chars else text[:snippet_chars].rstrip() + "…"
        return cls(
            citation_id=chunk.chunk_id,
            policy_id=chunk.policy_id,
            policy_title=chunk.policy_title,
            section_path=chunk.section_path,
            label=chunk.label,
            version=chunk.version,
            snippet=snippet,
            start=chunk.start,
            end=chunk.end,
        )


class Claim(BaseModel):
    """One assertion and the passages that support it.

    ``citation_ids`` has **no default**. Making it `list[str] = []` would let a model omit the field
    entirely and still produce a valid claim — the exact failure this schema exists to prevent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    citation_ids: list[str]


class ClosestSection(BaseModel):
    """A near-miss offered with a refusal: "not here, but you might mean this."

    Spec 08 §4 F4 requires refusals to suggest the closest sections. The score is retained so the
    UI can show how weak the match actually was, rather than presenting a near-miss with the same
    visual confidence as a real citation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    policy_title: str
    section_path: str
    score: float


class RetrievalTrace(BaseModel):
    """What retrieval did, surfaced to the UI and the admin view.

    ``withheld_count`` is a count and never content — see
    ``policyground.retrieval.base.RetrievalResult``. It is what lets the roles demo say "3 passages
    hidden at your role" honestly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str
    role: Role
    top_k: int
    retrieved: int
    withheld_count: int
    sufficiency: float
    threshold: float
    allowed_labels: list[Label]
    embedder: str
    degraded: bool = False


class Answer(BaseModel):
    """A cited answer. Every claim here has already survived the citation check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["answer"] = "answer"
    query_id: str
    question: str
    claims: list[Claim] = Field(min_length=1)
    citations: list[Citation]
    trace: RetrievalTrace
    stripped_claims: int = 0
    created_at: dt.datetime

    @property
    def cited_ids(self) -> set[str]:
        return {cid for claim in self.claims for cid in claim.citation_ids}


class Refusal(BaseModel):
    """An explicit "not found in the policies".

    **There is deliberately no ``claims`` field.** A refusal carries a message and near-misses, and
    nothing that could be rendered as an answer. That is what makes spec 08 §9's "never styled like
    a normal answer" a structural property rather than a styling convention (PLAN.md **D-015**).

    ``reason`` distinguishes *why* the system refused, which matters for the eval: refusing because
    retrieval was weak and refusing because every composed claim was uncited are different failures
    and are counted separately.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["refusal"] = "refusal"
    query_id: str
    question: str
    message: str
    reason: Literal["insufficient_evidence", "no_surviving_claims", "empty_retrieval"]
    closest_sections: list[ClosestSection]
    trace: RetrievalTrace
    #: Spec 08 §4 F4: the prompt that feeds the unanswered log.
    suggestion_prompt: str = "Should this be a policy? This question has been logged."
    created_at: dt.datetime


#: The API's response type. Pydantic discriminates on ``kind``, so a client that switches on it is
#: exhaustive by construction and cannot silently fall through to rendering a refusal as an answer.
AskResponse = Annotated[Answer | Refusal, Field(discriminator="kind")]


REFUSAL_MESSAGE = (
    "I can't find this in the policies. Nothing in the policy manual answers this question at a "
    "level of confidence worth reporting, so rather than infer an answer, this is a refusal."
)


def build_trace(
    result: RetrievalResult,
    *,
    backend: str,
    top_k: int,
    sufficiency: float,
    threshold: float,
    embedder: str,
    degraded: bool,
) -> RetrievalTrace:
    return RetrievalTrace(
        backend=backend,
        role=result.role,
        top_k=top_k,
        retrieved=len(result.hits),
        withheld_count=result.withheld_count,
        sufficiency=round(sufficiency, 4),
        threshold=threshold,
        allowed_labels=sorted(result.allowed_labels),
        embedder=embedder,
        degraded=degraded,
    )
