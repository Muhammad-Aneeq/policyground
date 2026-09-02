"""Shared FastAPI dependencies: settings, retriever, graph, database session, and the session role.

The role dependency is the one worth reading. Spec 08 §11 says the role comes "from an
authenticated session (simulated in v1)", and this is that simulation — the role arrives as a
request field. It is honest about being a simulation, and it is also the *only* place a role enters
the system, so replacing it with a claim from a validated token later is a change to this file and
nothing else.

It validates rather than trusts blindly: an unknown role value is rejected with 422 instead of
falling back to a default. A permissive default here would be a privilege-escalation bug, and
"guest" as a safe default would be equally wrong in the other direction — silently downgrading a
controller's session and making the product look broken.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi import Query as QueryParam
from sqlalchemy.orm import Session

from policyground.config import Settings, get_settings
from policyground.db.session import get_engine, init_db, session_factory
from policyground.graph.build import PolicyGroundGraph
from policyground.labels import Role
from policyground.retrieval.base import Retriever
from policyground.retrieval.factory import get_retriever


def settings_dep() -> Settings:
    return get_settings()


def retriever_dep() -> Retriever:
    return get_retriever()


@lru_cache(maxsize=1)
def _graph() -> PolicyGroundGraph:
    """Built once per process. It loads the index and the vocabulary, which should not happen per
    request."""
    return PolicyGroundGraph.from_settings(get_settings(), get_retriever())


def graph_dep() -> PolicyGroundGraph:
    return _graph()


def reset_graph_cache() -> None:
    """Drop the cached graph — used after a reindex and by tests."""
    _graph.cache_clear()


def db_session() -> Iterator[Session]:
    init_db(get_engine())
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def parse_role(value: str) -> Role:
    """String → :class:`Role`, rejecting anything unrecognised.

    Rejecting is deliberate. Defaulting an unknown role to ``controller`` would be an escalation
    bug; defaulting it to ``guest`` would silently strip a legitimate user's access and read as a
    broken product. A 422 says exactly what went wrong.
    """
    try:
        return Role(value)
    except ValueError:
        raise HTTPException(
            status_code=422,  # unprocessable content
            detail=(f"unknown role {value!r}. Valid roles: {', '.join(r.value for r in Role)}."),
        ) from None


def role_query(role: str = QueryParam(default=Role.STAFF.value)) -> Role:
    """Role for GET endpoints, where it arrives as a query parameter.

    Note this is part of the cache key for any client-side caching: the roles demo depends on the
    same URL with a different role returning different content, and on the client not reusing a
    cached response across a role switch.
    """
    return parse_role(role)


SessionDep = Depends(db_session)
GraphDep = Depends(graph_dep)
RetrieverDep = Depends(retriever_dep)
SettingsDep = Depends(settings_dep)
RoleDep = Depends(role_query)
