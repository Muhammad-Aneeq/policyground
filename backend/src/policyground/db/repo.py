"""Persistence for queries, answers, refusals and the unanswered log.

Every ask is recorded, answered or refused, because the two admin metrics spec 08 §9 asks for —
groundedness trend and **refusal rate** — cannot be computed from answers alone. A refusal that
leaves no trace is a refusal that never happened as far as the dashboard is concerned.

The one piece of real logic here is unanswered-log deduplication. Spec 08 §1 calls the log "a
feature" and the launch hooks call it "a roadmap for policies you're missing" — but a flat append
produces 400 near-identical rows and nobody reads it. Folding repeats onto one row with a counter
turns it into a ranked list of what to write next, which is the thing that was actually promised.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from policyground.answers.schema import Answer as AnswerModel
from policyground.answers.schema import Refusal as RefusalModel
from policyground.corpus.models import PolicyDoc
from policyground.db.models import (
    Answer,
    Chunk,
    Document,
    EvalRun,
    Query,
    Unanswered,
    utcnow,
)
from policyground.graph.state import GraphState
from policyground.labels import Label, Role
from policyground.retrieval.base import Chunk as RetrievedChunk

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalise_question(text: str) -> str:
    """The dedupe key for the unanswered log.

    Lowercase, strip punctuation, collapse whitespace, drop a trailing "please". Deliberately
    conservative: it folds *"What is the crypto policy?"* onto *"what is the crypto policy"* but
    makes no attempt at semantic matching. An aggressive matcher would merge genuinely different
    questions and hide a gap — the failure that matters here is a false merge, not a missed one.
    """
    lowered = _PUNCTUATION_RE.sub(" ", text.lower())
    collapsed = _WHITESPACE_RE.sub(" ", lowered).strip()
    return collapsed.removesuffix(" please").strip()


def _new_id() -> str:
    return uuid.uuid4().hex[:24]


# ------------------------------------------------------------------ writes --


def record_response(
    session: Session,
    response: AnswerModel | RefusalModel,
    *,
    state: GraphState | None = None,
) -> Query:
    """Persist one ask. Returns the ``Query`` row.

    Handles both branches of the response union in one function so it is impossible to add a code
    path that answers without logging.
    """
    trace = response.trace
    refused = response.kind == "refusal"

    query = Query(
        id=response.query_id,
        text=response.question,
        role=str(trace.role),
        answered=not refused,
        refused=refused,
        refusal_reason=response.reason if isinstance(response, RefusalModel) else None,
        sufficiency=trace.sufficiency,
        withheld_count=trace.withheld_count,
        backend=trace.backend,
        at=response.created_at,
    )
    session.add(query)

    if isinstance(response, AnswerModel):
        session.add(
            Answer(
                id=_new_id(),
                query_id=query.id,
                claims_json=[claim.model_dump(mode="json") for claim in response.claims],
                citations_json=[c.model_dump(mode="json") for c in response.citations],
                raw_claims_json=[
                    claim.model_dump(mode="json") for claim in (state or {}).get("raw_claims", [])
                ],
                stripped_claims=response.stripped_claims,
                unknown_citation_ids=list((state or {}).get("unknown_citation_ids", [])),
                at=response.created_at,
            )
        )
    else:
        record_unanswered(session, response)

    return query


def record_unanswered(session: Session, refusal: RefusalModel) -> Unanswered:
    """Add to the unanswered log, folding a repeat onto its existing row."""
    key = normalise_question(refusal.question)
    existing = session.scalar(select(Unanswered).where(Unanswered.normalised_text == key))

    closest = [section.model_dump(mode="json") for section in refusal.closest_sections]

    if existing is not None:
        existing.times_asked += 1
        existing.at = refusal.created_at
        # Refresh the near-misses: the corpus may have changed since the question was first asked,
        # and a stale suggestion list is worse than none.
        existing.closest_sections_json = closest
        existing.refusal_reason = refusal.reason
        return existing

    entry = Unanswered(
        id=_new_id(),
        query_text=refusal.question,
        normalised_text=key,
        closest_sections_json=closest,
        role=str(refusal.trace.role),
        refusal_reason=refusal.reason,
        times_asked=1,
        first_asked_at=refusal.created_at,
        at=refusal.created_at,
    )
    session.add(entry)
    return entry


def sync_corpus(
    session: Session, chunks: list[RetrievedChunk], docs: list[PolicyDoc]
) -> tuple[int, int]:
    """Replace the ``documents`` and ``chunks`` tables from the current corpus.

    Full replace rather than an upsert: the index is rebuilt whole (see ``ingest.pipeline``), and
    the database mirroring it must be rebuilt the same way or a deleted policy would linger in the
    source browser while being absent from retrieval.
    """
    session.query(Chunk).delete()
    session.query(Document).delete()

    for doc in docs:
        session.add(
            Document(
                id=doc.policy_id,
                policy_id=doc.policy_id,
                title=doc.title,
                label=doc.label.value,
                version=doc.front_matter.version,
                owner=doc.front_matter.owner,
                category=doc.front_matter.category,
                effective_date=doc.front_matter.effective_date.isoformat(),
                source_path=doc.source_path,
            )
        )

    for chunk in chunks:
        session.add(
            Chunk(
                id=chunk.chunk_id,
                doc_id=chunk.policy_id,
                section=chunk.section_path,
                text=chunk.text,
                embedding_ref=f"vectors.npy#{chunk.ordinal}",
                label=chunk.label.value,
                start_offset=chunk.start,
                end_offset=chunk.end,
                ordinal=chunk.ordinal,
            )
        )

    return len(docs), len(chunks)


def record_eval_run(session: Session, **fields: object) -> EvalRun:
    run = EvalRun(id=_new_id(), **fields)
    session.add(run)
    return run


# ------------------------------------------------------------------- reads --


@dataclass(frozen=True, slots=True)
class AdminMetrics:
    """What ``GET /api/admin/metrics`` reports (spec 08 §7, §9)."""

    total_queries: int
    answered: int
    refused: int
    refusal_rate: float
    unanswered_unique: int
    unanswered_total_asks: int
    avg_sufficiency: float
    claims_stripped: int
    answers_with_stripped_claims: int
    queries_by_role: dict[str, int]
    refusals_by_reason: dict[str, int]


def admin_metrics(session: Session, *, since: dt.datetime | None = None) -> AdminMetrics:
    stmt = select(Query)
    if since is not None:
        stmt = stmt.where(Query.at >= since)
    queries = list(session.scalars(stmt))

    total = len(queries)
    refused = sum(1 for q in queries if q.refused)
    answered = total - refused

    by_role: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for query in queries:
        by_role[query.role] = by_role.get(query.role, 0) + 1
        if query.refused and query.refusal_reason:
            by_reason[query.refusal_reason] = by_reason.get(query.refusal_reason, 0) + 1

    stripped_total = session.scalar(select(func.sum(Answer.stripped_claims))) or 0
    answers_stripped = (
        session.scalar(select(func.count()).select_from(Answer).where(Answer.stripped_claims > 0))
        or 0
    )
    unique_unanswered = session.scalar(select(func.count()).select_from(Unanswered)) or 0
    total_asks = session.scalar(select(func.sum(Unanswered.times_asked))) or 0

    return AdminMetrics(
        total_queries=total,
        answered=answered,
        refused=refused,
        # Reported as 0.0 for an empty log rather than as a division error. A fresh deployment has
        # no refusal rate; it does not have an undefined one.
        refusal_rate=round(refused / total, 4) if total else 0.0,
        unanswered_unique=int(unique_unanswered),
        unanswered_total_asks=int(total_asks),
        avg_sufficiency=round(sum(q.sufficiency for q in queries) / total, 4) if total else 0.0,
        claims_stripped=int(stripped_total),
        answers_with_stripped_claims=int(answers_stripped),
        queries_by_role=dict(sorted(by_role.items())),
        refusals_by_reason=dict(sorted(by_reason.items())),
    )


def unanswered_log(session: Session, *, limit: int = 200) -> list[Unanswered]:
    """The log, most-asked first — the order that makes it a roadmap rather than a list."""
    return list(
        session.scalars(
            select(Unanswered)
            .order_by(Unanswered.times_asked.desc(), Unanswered.at.desc())
            .limit(limit)
        )
    )


def eval_run_history(session: Session, *, limit: int = 50) -> list[EvalRun]:
    """Oldest-first, so the trend chart plots left to right without reversing in the client."""
    runs = list(session.scalars(select(EvalRun).order_by(EvalRun.at.desc()).limit(limit)))
    return list(reversed(runs))


def visible_documents(session: Session, role: Role) -> list[Document]:
    """Policies this role may browse.

    Filtered in the query, not after it. The source browser is a second retrieval surface and must
    honour the same rule as the retriever — spec 08 §9's roles demo shows content vanishing from
    *both*, and a browser that filtered in the template would leak titles through the API.
    """
    from policyground.labels import allowed_labels

    permitted = [label.value for label in allowed_labels(role)]
    return list(
        session.scalars(
            select(Document).where(Document.label.in_(permitted)).order_by(Document.policy_id)
        )
    )


def get_answer(session: Session, query_id: str) -> Answer | None:
    return session.scalar(select(Answer).where(Answer.query_id == query_id))


def get_query(session: Session, query_id: str) -> Query | None:
    return session.get(Query, query_id)


def label_counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(Document.label, func.count()).group_by(Document.label)).all()
    counts = {label.value: 0 for label in Label}
    counts.update({str(label): int(count) for label, count in rows})
    return counts


__all__ = [
    "AdminMetrics",
    "admin_metrics",
    "eval_run_history",
    "get_answer",
    "get_query",
    "label_counts",
    "normalise_question",
    "record_eval_run",
    "record_response",
    "record_unanswered",
    "sync_corpus",
    "unanswered_log",
    "utcnow",
    "visible_documents",
]
