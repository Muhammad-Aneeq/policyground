"""Admin surface: metrics, the unanswered log, its CSV export, and reindex (spec 08 §7, §9).

The unanswered log is the screen spec 08 §1 calls "a feature" and the launch hooks call "a roadmap
for policies you're missing". It is served **most-asked first**, because that ordering is the whole
difference between a list and a roadmap.

Every metrics payload carries ``offline`` and ``degraded`` flags. Spec 08 §14 asks for judge
agreement to be published rather than assumed; the smaller version of that honesty is that a
groundedness chart in this build was produced by a deterministic proxy, not a model, and the API
says so rather than leaving the UI to remember.
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter
from fastapi import Query as QueryParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from policyground.api.deps import SessionDep, SettingsDep, reset_graph_cache
from policyground.config import Settings
from policyground.db import repo
from policyground.labels import Label

router = APIRouter(prefix="/api/admin", tags=["admin"])


class EvalRunPoint(BaseModel):
    """One point on the groundedness trend chart (spec 08 §9 screen 3)."""

    model_config = ConfigDict(extra="forbid")

    at: dt.datetime
    commit: str
    groundedness: float
    citation_validity: float
    refusal_accuracy: float
    false_refusal_rate: float
    label_leaks: int
    cases: int
    passed: bool
    offline: bool
    judge: str


class MetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_queries: int
    answered: int
    refused: int
    refusal_rate: float
    avg_sufficiency: float
    unanswered_unique: int
    unanswered_total_asks: int
    claims_stripped: int
    answers_with_stripped_claims: int
    queries_by_role: dict[str, int]
    refusals_by_reason: dict[str, int]
    corpus_labels: dict[str, int]
    eval_runs: list[EvalRunPoint]
    #: True when no model credential is configured, so embeddings and compose ran on the documented
    #: deterministic fallbacks (BLOCKERS.md B1). Rendered as a badge; never silently omitted.
    degraded: bool
    app_mode: str


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    days: int | None = QueryParam(default=None, ge=1, le=365),
    session: Session = SessionDep,
    settings: Settings = SettingsDep,
) -> MetricsResponse:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days) if days else None
    summary = repo.admin_metrics(session, since=since)

    return MetricsResponse(
        total_queries=summary.total_queries,
        answered=summary.answered,
        refused=summary.refused,
        refusal_rate=summary.refusal_rate,
        avg_sufficiency=summary.avg_sufficiency,
        unanswered_unique=summary.unanswered_unique,
        unanswered_total_asks=summary.unanswered_total_asks,
        claims_stripped=summary.claims_stripped,
        answers_with_stripped_claims=summary.answers_with_stripped_claims,
        queries_by_role=summary.queries_by_role,
        refusals_by_reason=summary.refusals_by_reason,
        corpus_labels=repo.label_counts(session),
        eval_runs=[
            EvalRunPoint(
                at=run.at,
                commit=run.commit,
                groundedness=run.groundedness,
                citation_validity=run.citation_validity,
                refusal_accuracy=run.refusal_accuracy,
                false_refusal_rate=run.false_refusal_rate,
                label_leaks=run.label_leaks,
                cases=run.cases,
                passed=run.passed,
                offline=run.offline,
                judge=run.judge,
            )
            for run in repo.eval_run_history(session)
        ],
        degraded=not (settings.has_openai_key or settings.has_azure_openai),
        app_mode=settings.app_mode.value,
    )


class UnansweredEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    query_text: str
    times_asked: int
    role: str
    refusal_reason: str
    closest_sections: list[dict]  # type: ignore[type-arg]
    first_asked_at: dt.datetime
    last_asked_at: dt.datetime


class UnansweredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[UnansweredEntry]
    total_unique: int
    total_asks: int


@router.get("/unanswered", response_model=UnansweredResponse)
def unanswered(
    limit: int = QueryParam(default=200, ge=1, le=1000),
    session: Session = SessionDep,
) -> UnansweredResponse:
    """The "policies to write" log, most-asked first."""
    entries = repo.unanswered_log(session, limit=limit)
    summary = repo.admin_metrics(session)

    return UnansweredResponse(
        entries=[
            UnansweredEntry(
                id=entry.id,
                query_text=entry.query_text,
                times_asked=entry.times_asked,
                role=entry.role,
                refusal_reason=entry.refusal_reason,
                closest_sections=list(entry.closest_sections_json),
                first_asked_at=entry.first_asked_at,
                last_asked_at=entry.at,
            )
            for entry in entries
        ],
        total_unique=summary.unanswered_unique,
        total_asks=summary.unanswered_total_asks,
    )


@router.get("/unanswered.csv")
def unanswered_csv(session: Session = SessionDep) -> StreamingResponse:
    """Spec 08 §9: the unanswered log, "exportable: 'policies to write'".

    CSV rather than JSON because the consumer is a policy owner with a spreadsheet, not a program.
    The closest-section column is flattened to readable text for the same reason — a nested JSON
    blob in a cell helps nobody.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "times_asked",
            "question",
            "first_asked",
            "last_asked",
            "role",
            "refusal_reason",
            "closest_sections",
        ]
    )

    for entry in repo.unanswered_log(session, limit=1000):
        closest = "; ".join(
            f"{section.get('policy_id', '?')} {section.get('section_path', '')}".strip()
            for section in entry.closest_sections_json
        )
        writer.writerow(
            [
                entry.times_asked,
                entry.query_text,
                entry.first_asked_at.isoformat(),
                entry.at.isoformat(),
                entry.role,
                entry.refusal_reason,
                closest,
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="policies-to-write.csv"'},
    )


class ReindexResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policies: int
    chunks: int
    embedder: str
    corpus_sha256: str
    degraded: bool
    message: str


@router.post("/reindex", response_model=ReindexResponse)
def reindex(
    session: Session = SessionDep,
    settings: Settings = SettingsDep,
) -> ReindexResponse:
    """Rebuild the index from ``corpus/`` (spec 08 §7).

    Runs the same ``run_ingest`` the CLI does, so there is exactly one way to build an index. A
    second implementation reachable only through the API could produce a *different* index from the
    same corpus, and every guarantee downstream rests on the index matching the policies.

    Corpus consistency is checked first, so a reindex refuses a drifted corpus rather than serving
    contradictory thresholds.
    """
    from policyground.corpus.chunker import chunk_corpus
    from policyground.corpus.loader import load_corpus
    from policyground.ingest.pipeline import run_ingest
    from policyground.retrieval.factory import reset_retriever_cache

    result = run_ingest(settings, mode=settings.app_mode, rebuild=True)

    docs = load_corpus(settings.policies_dir)
    chunks, _ = chunk_corpus(docs)
    repo.sync_corpus(session, chunks, docs)

    # Both caches must be dropped together. Refreshing the retriever while the graph still holds a
    # reference to the old one would serve stale content from a page that just said "reindexed".
    reset_retriever_cache()
    reset_graph_cache()

    return ReindexResponse(
        policies=result.policies,
        chunks=result.chunks,
        embedder=result.embedder,
        corpus_sha256=result.corpus_sha256,
        degraded=result.degraded,
        message=result.stats_line,
    )


class LabelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int]
    labels: list[Label]


@router.get("/labels", response_model=LabelSummary)
def labels(session: Session = SessionDep) -> LabelSummary:
    """Corpus label distribution — the denominator for the roles demo's "N hidden" counter."""
    return LabelSummary(counts=repo.label_counts(session), labels=list(Label))
