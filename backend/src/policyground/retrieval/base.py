"""The `Retriever` contract — the one interface LOCAL and AZURE modes both implement.

Spec 08 §4 F6 requires that "restricted docs never enter context for unprivileged roles". The
design decision that makes that guarantee real rather than aspirational is visible in the
signature below: :meth:`Retriever.search` takes a ``role`` and there is **no** way to ask for
unfiltered results (PLAN.md **D-003**). A caller cannot forget to filter, because filtering is not
something the caller does.

Two consequences follow deliberately:

* There is no ``search_all``, no ``include_restricted=True``, and no ``labels=`` override. Adding
  one would create exactly the bypass an injection attempt goes looking for.
* Because both implementations satisfy the same Protocol, the contract tests in
  ``tests/test_retriever_contract.py`` run against *both* — so AZURE mode's filtering is tested
  even though it has never been deployed (BLOCKERS.md **B2**).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from policyground.labels import Label, Role


@dataclass(frozen=True, slots=True)
class Chunk:
    """One indexed passage: the unit of retrieval and the unit of citation.

    ``chunk_id`` is stable across rebuilds — derived from the policy id and the section path, not
    from a counter — so a citation recorded in the ``answers`` table still resolves after a
    re-ingest, and so the judge cache is not invalidated by an unrelated corpus edit.

    ``start``/``end`` are offsets into the policy's raw markdown (PLAN.md **D-017**). They are what
    the Source Viewer highlights with, and they are carried all the way through retrieval so the
    UI never has to re-find the passage by string matching.
    """

    chunk_id: str
    policy_id: str
    policy_title: str
    section_path: str
    label: Label
    version: str
    text: str
    start: int
    end: int
    ordinal: int

    @property
    def citation_label(self) -> str:
        """How this chunk reads in a citation: ``PG-0003 - 2. Thresholds``."""
        return f"{self.policy_id} - {self.section_path}"

    @property
    def indexable_text(self) -> str:
        """The representation BOTH retrieval arms index, and both modes embed.

        Prefixing the policy title and section path is not decoration. Authored prose rarely
        repeats its own subject — the section headed "4. Accommodation" in PG-0006 barely uses the
        word again in its body — so indexing the body alone leaves a section unfindable by the very
        term that names it.

        It lives on ``Chunk`` so the keyword arm, the vector arm, local ingestion and Azure
        ingestion cannot drift apart in what they consider a document. One definition, four callers.
        """
        return f"{self.policy_title}\n{self.section_path}\n{self.text}"


@dataclass(frozen=True, slots=True)
class Hit:
    """A chunk plus why it surfaced.

    The per-arm scores are kept rather than collapsed into one number because the admin view and
    the sufficiency assessor both need to distinguish "matched strongly on keywords" from "matched
    weakly on both arms" — a distinction that decides whether the system answers or refuses.
    """

    chunk: Chunk
    score: float
    bm25_rank: int | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    vector_score: float | None = None

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def arms(self) -> tuple[str, ...]:
        """Which retrieval arms found this chunk — used in the UI to explain the result."""
        found = []
        if self.bm25_rank is not None:
            found.append("keyword")
        if self.vector_rank is not None:
            found.append("vector")
        return tuple(found)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Everything the graph needs from retrieval, including what was withheld.

    ``withheld_count`` is the number of chunks that matched the query but were excluded by the
    label filter. It is a **count only** — never the chunks, never their titles, never their
    policy ids — so the roles demo can honestly show "3 passages hidden at your role" without the
    number itself becoming a disclosure channel. A count reveals that governance is operating; a
    title would reveal what is being governed.
    """

    query: str
    role: Role
    hits: list[Hit] = field(default_factory=list)
    withheld_count: int = 0
    allowed_labels: frozenset[Label] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.hits)

    @property
    def chunk_ids(self) -> list[str]:
        return [hit.chunk_id for hit in self.hits]

    @property
    def chunks(self) -> list[Chunk]:
        return [hit.chunk for hit in self.hits]

    def top_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0


@runtime_checkable
class Retriever(Protocol):
    """Hybrid keyword + vector retrieval with label filtering applied *inside* the retriever."""

    #: Identifies the implementation in logs, eval artifacts and the admin UI, so a reader can
    #: always tell which mode produced a number.
    backend_name: str

    def search(self, query: str, *, role: Role, top_k: int = 6) -> RetrievalResult:
        """Return at most ``top_k`` chunks this ``role`` is permitted to see.

        Implementations must apply the label filter *before* scoring or ranking, not after. A
        post-filter would leave restricted text in memory, in logs and in any trace of the
        retrieval call — and would silently return fewer than ``top_k`` results for unprivileged
        roles, which is a subtle correctness bug on top of a governance one.
        """
        ...

    def get_chunk(self, chunk_id: str, *, role: Role) -> Chunk | None:
        """Fetch one chunk by id, still subject to the role's labels.

        Used by the citations panel. It is separately label-checked on purpose: a chunk id that
        leaked into a client through any other path must not become a retrieval bypass.
        """
        ...
