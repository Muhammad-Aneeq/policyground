"""The source browser: ``GET /api/policies`` and ``GET /api/policies/{id}``.

This is the **second retrieval surface**, and it is the one that is easy to forget. Spec 08 §9's
roles demo shows restricted content vanishing from retrieval *and* from the source browser; a
browser that filtered in the template rather than in the query would still ship every restricted
title over the wire, and the demo would be a lie that happened to look right.

So every endpoint here applies the same rule as the retriever, and
``tests/test_api.py`` sweeps all three roles against all 30 policies to prove it.

The full policy text is served as **raw markdown**, deliberately. The Source Viewer highlights the
cited passage using the ``start``/``end`` offsets recorded at ingest (PLAN.md **D-017**), and those
offsets index into exactly this string. Server-side rendering to HTML would invalidate every one of
them.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from policyground.api.deps import RetrieverDep, RoleDep, SessionDep
from policyground.db import repo
from policyground.db.models import Document
from policyground.labels import Label, Role, allowed_labels, hidden_labels
from policyground.retrieval.base import Retriever

router = APIRouter(prefix="/api", tags=["corpus"])


class PolicySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    title: str
    label: Label
    version: str
    owner: str
    category: str
    effective_date: str


class PolicyList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    policies: list[PolicySummary]
    visible_count: int
    #: How many whole policies this role cannot see. A **count**, never titles or ids — enough to
    #: make the control visible, not enough to disclose what is behind it. This number is what the
    #: roles demo animates when the role is switched.
    hidden_count: int
    hidden_labels: list[Label]


@router.get("/policies", response_model=PolicyList)
def list_policies(
    role: Role = RoleDep,
    session: Session = SessionDep,
) -> PolicyList:
    """Policies this role may browse, plus a count of what is withheld."""
    documents = repo.visible_documents(session, role)
    total = session.query(Document).count()

    return PolicyList(
        role=role,
        policies=[
            PolicySummary(
                policy_id=doc.policy_id,
                title=doc.title,
                label=Label(doc.label),
                version=doc.version,
                owner=doc.owner,
                category=doc.category,
                effective_date=doc.effective_date,
            )
            for doc in documents
        ],
        visible_count=len(documents),
        hidden_count=total - len(documents),
        hidden_labels=sorted(hidden_labels(role)),
    )


class PolicyDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    title: str
    label: Label
    version: str
    owner: str
    category: str
    effective_date: str
    #: Raw markdown. Offsets from citations index into this exact string — see module docstring.
    markdown: str
    sections: list[dict]  # type: ignore[type-arg]


@router.get("/policies/{policy_id}", response_model=PolicyDetail)
def get_policy(
    policy_id: str,
    role: Role = RoleDep,
    session: Session = SessionDep,
    retriever: Retriever = RetrieverDep,
) -> PolicyDetail:
    """Full text of one policy, if this role may see it.

    A policy the role may not see returns **404, not 403**. "Forbidden" confirms the document
    exists, which is itself a disclosure — someone enumerating ``PG-0001``…``PG-0040`` would learn
    exactly which ids are restricted without reading a word of them. Absent and forbidden must be
    indistinguishable from outside.
    """
    document = session.get(Document, policy_id)
    if document is None or Label(document.label) not in allowed_labels(role):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")

    chunks = [
        chunk
        for chunk in getattr(retriever, "chunks", [])
        if chunk.policy_id == policy_id and chunk.label in allowed_labels(role)
    ]
    chunks.sort(key=lambda c: c.start)

    if not chunks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not indexed")

    # Reconstruct the document text from its own chunks. They tile the body exactly (asserted in
    # tests/test_chunker.py), so this reproduces the authored markdown without a second read from
    # disk and without the API needing filesystem access to the corpus at request time.
    markdown = "".join(chunk.text for chunk in chunks)
    offset_base = chunks[0].start

    return PolicyDetail(
        policy_id=document.policy_id,
        title=document.title,
        label=Label(document.label),
        version=document.version,
        owner=document.owner,
        category=document.category,
        effective_date=document.effective_date,
        markdown=markdown,
        sections=[
            {
                "chunk_id": chunk.chunk_id,
                "section_path": chunk.section_path,
                # Offsets rebased onto `markdown`, because the client receives the reconstructed
                # body and not the original file (whose offsets include the front-matter block).
                "start": chunk.start - offset_base,
                "end": chunk.end - offset_base,
            }
            for chunk in chunks
        ],
    )
