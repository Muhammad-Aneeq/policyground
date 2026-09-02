"""The data model from spec 08 §6, as SQLAlchemy tables.

    documents(id, policy_id, title, label, version)
    chunks(id, doc_id, section, text, embedding_ref, label)
    queries(id, text, role, answered, groundedness, refused, at)
    answers(id, query_id, claims_json, citations_json)
    unanswered(id, query_text, closest_sections_json, at)
    eval_runs(commit, groundedness, citation_validity, refusal_accuracy, passed)

One model set targets both SQLite (dev) and Postgres (prod), per spec 00 A1. Nothing here uses a
dialect-specific type: JSON payloads go through SQLAlchemy's portable ``JSON``, which maps to
``jsonb`` on Postgres and to a text column on SQLite.

Two additions to the spec's minimum, both earning their place:

* ``queries.refusal_reason`` — the spec records *that* a query was refused. Distinguishing
  "retrieval was too weak" from "every composed claim was uncited" is what makes the unanswered log
  actionable: the first says the corpus has a gap, the second says the model failed on material
  that was actually there.
* ``answers.stripped_claims`` and ``answers.raw_claims_json`` — how many claims the citation check
  removed, and what they were. Without this the admin view can report that the control exists but
  never that it *fired*, which is the more interesting fact.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    """Timezone-aware UTC. SQLite has no native timestamptz, so naive values would round-trip as
    naive and compare wrongly against aware ones in the admin queries."""
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    """One policy. Mirrors ``corpus/MANIFEST.json`` so the database can answer questions about the
    corpus without reading 30 files from disk."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    label: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(16))
    owner: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    effective_date: Mapped[str] = mapped_column(String(24), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    source_path: Mapped[str] = mapped_column(String(200), default="")

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete")


class Chunk(Base):
    """One indexed passage. ``embedding_ref`` names the artifact holding the vector rather than
    storing the vector itself — the vectors live in ``data/vectors.npy`` for LOCAL and in the AI
    Search index for AZURE, and duplicating them here would create a third copy that can drift."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    embedding_ref: Mapped[str] = mapped_column(String(200), default="")
    label: Mapped[str] = mapped_column(String(16), index=True)
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Query(Base):
    """Every question asked, answered or not.

    The admin refusal-rate metric is computed from these rows.
    """

    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24), index=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    refused: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: Populated by the eval harness, not at request time — scoring every live query with a judge
    #: would put a model call on the serving path, which spec 08 §8 reserves for eval only.
    groundedness: Mapped[float | None] = mapped_column(Float, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sufficiency: Mapped[float] = mapped_column(Float, default=0.0)
    withheld_count: Mapped[int] = mapped_column(Integer, default=0)
    backend: Mapped[str] = mapped_column(String(40), default="")
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    answer: Mapped[Answer | None] = relationship(
        back_populates="query", cascade="all, delete", uselist=False
    )


# The admin dashboard's headline query is "refusal rate over the last N days, by role".
Index("ix_queries_at_role", Query.at, Query.role)


class Answer(Base):
    """The rendered answer. ``claims_json`` holds what survived the citation check; the raw draft is
    kept separately so the control's effect is auditable rather than merely asserted."""

    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_id: Mapped[str] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), index=True, unique=True
    )
    claims_json: Mapped[list] = mapped_column(JSON, default=list)  # type: ignore[type-arg]
    citations_json: Mapped[list] = mapped_column(JSON, default=list)  # type: ignore[type-arg]
    raw_claims_json: Mapped[list] = mapped_column(JSON, default=list)  # type: ignore[type-arg]
    stripped_claims: Mapped[int] = mapped_column(Integer, default=0)
    unknown_citation_ids: Mapped[list] = mapped_column(JSON, default=list)  # type: ignore[type-arg]
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    query: Mapped[Query] = relationship(back_populates="answer")


class Unanswered(Base):
    """Spec 08 §4 F4's "should this be a policy?" log — described in spec 08 §1 as "the 'unanswered
    questions' log as a feature", and in the launch hooks as "a roadmap for policies you're
    missing".

    ``times_asked`` is not in the spec's column list and is the field that makes the log useful. A
    flat list of 400 one-off questions is noise; the same question asked eleven times is a policy
    that needs writing. Repeats are folded onto one row via ``normalised_text``.
    """

    __tablename__ = "unanswered"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_text: Mapped[str] = mapped_column(Text)
    #: Lowercased, whitespace-collapsed, punctuation-stripped — the dedupe key.
    normalised_text: Mapped[str] = mapped_column(String(500), index=True)
    closest_sections_json: Mapped[list] = mapped_column(JSON, default=list)  # type: ignore[type-arg]
    role: Mapped[str] = mapped_column(String(24), default="")
    refusal_reason: Mapped[str] = mapped_column(String(40), default="")
    times_asked: Mapped[int] = mapped_column(Integer, default=1)
    first_asked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class EvalRun(Base):
    """One CI eval run, per spec 08 §6. Feeds the admin groundedness trend chart.

    ``commit`` is the primary key in the spec. It is *not* here: re-running the suite on the same
    commit (offline versus live judge, or a threshold sweep) is a normal thing to do, and a
    commit-keyed table would silently overwrite the earlier run. The commit is kept and indexed.
    """

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    commit: Mapped[str] = mapped_column(String(40), index=True, default="")
    groundedness: Mapped[float] = mapped_column(Float, default=0.0)
    citation_validity: Mapped[float] = mapped_column(Float, default=0.0)
    refusal_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    false_refusal_rate: Mapped[float] = mapped_column(Float, default=0.0)
    label_leaks: Mapped[int] = mapped_column(Integer, default=0)
    cases: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: True when produced by the offline deterministic proxy rather than a live pinned judge. It is
    #: carried into the API and rendered as a badge, so no chart can imply a model scored these.
    offline: Mapped[bool] = mapped_column(Boolean, default=True)
    judge: Mapped[str] = mapped_column(String(80), default="")
    embedder: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
