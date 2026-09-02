"""The FastAPI application factory.

Startup does two things worth noting. It **syncs the corpus into the database** so the source
browser and the retriever are describing the same 30 policies, and it **logs the degraded-mode
banner** when no model credential is present, so anyone running this sees the caveat in their own
terminal rather than only in BLOCKERS.md.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from policyground.api import routes_admin, routes_ask, routes_corpus
from policyground.config import Settings, get_settings
from policyground.db import repo
from policyground.db.session import get_engine, init_db, session_scope
from policyground.labels import Label, Role

logger = logging.getLogger(__name__)

DESCRIPTION = """\
Governed finance RAG over a synthetic accounting policy manual.

Every claim is cited, weak retrieval refuses rather than guessing, and sensitivity labels are
applied inside the retriever so restricted passages never enter model context for an unprivileged
role.

**All corpus content is synthetic.**
"""


def _sync_corpus_on_startup(settings: Settings) -> None:
    """Mirror the corpus into ``documents``/``chunks``.

    Failure here is logged and swallowed rather than raised. A missing index should surface as a
    clear error on the first ``/api/ask`` — which says to run ``pg ingest`` — and not as an
    application that refuses to start, which is a far worse first experience.
    """
    try:
        from policyground.corpus.chunker import chunk_corpus
        from policyground.corpus.loader import load_corpus

        docs = load_corpus(settings.policies_dir)
        chunks, _ = chunk_corpus(docs)
        with session_scope() as session:
            policies, chunk_count = repo.sync_corpus(session, chunks, docs)
        logger.info("corpus synced: %d policies, %d chunks", policies, chunk_count)
    except Exception as exc:
        logger.warning("corpus sync skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_db(get_engine())
    _sync_corpus_on_startup(settings)

    if not (settings.has_openai_key or settings.has_azure_openai):
        logger.warning(
            "DEGRADED MODE: no model credential. Embeddings use the deterministic hash embedder "
            "and compose uses the offline extractive stub. Citation enforcement, label filtering "
            "and refusal are unaffected — they are deterministic. See BLOCKERS.md B1."
        )
    logger.info("PolicyGround ready in %s mode", settings.app_mode.value)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="PolicyGround",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )

    # The SPA runs on Vite's dev server on a different origin. Restricted to localhost: this is a
    # demo API with a simulated role in the request body, so a permissive CORS policy would let any
    # page a developer visits query it as a controller.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(routes_ask.router)
    app.include_router(routes_corpus.router)
    app.include_router(routes_admin.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        """Liveness plus the facts a reader needs to interpret every other response.

        ``degraded`` and ``synthetic_corpus`` are here so an honest caveat is available
        programmatically, not only in prose someone has to read.
        """
        return {
            "status": "ok",
            "app_mode": settings.app_mode.value,
            "degraded": not (settings.has_openai_key or settings.has_azure_openai),
            "synthetic_corpus": True,
            "roles": [role.value for role in Role],
            "labels": [label.value for label in Label],
        }

    return app


app = create_app()
