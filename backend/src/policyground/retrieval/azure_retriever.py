"""AZURE mode retrieval: the same `Retriever` contract, backed by Azure AI Search.

**This code has never run against a live Azure AI Search service.** There is no subscription in
this build environment (BLOCKERS.md **B2**). It is written to be deployable and is covered by
contract tests with the SDK mocked, but nothing here should be read as "tested in production".

What the tests *can* prove without a subscription, and do:

* the OData filter string excludes every label the role may not see, for every role;
* both retrieval arms are sent in one request (hybrid), not two sequential searches;
* results map into exactly the same :class:`~policyground.retrieval.base.Chunk` shape as LOCAL
  mode — the shared contract test in ``tests/test_retriever_contract.py`` runs the identical
  assertions against both implementations.

The one design point that matters as much as in LOCAL mode: **the label filter is a search
parameter, not a post-filter.** AI Search applies ``filter`` before returning documents, so
restricted text never crosses the network. Filtering client-side would put it in the process, in
memory, and in any request log along the way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyground.config import Settings
from policyground.labels import Label, Role, allowed_labels
from policyground.retrieval.base import Chunk, Hit, RetrievalResult
from policyground.retrieval.embeddings import Embedder, build_embedder, tokenize_query
from policyground.retrieval.fusion import DEFAULT_RRF_K

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

#: How many candidates to ask AI Search for before trimming to ``top_k``. AI Search performs its
#: own RRF across the vector and keyword arms server-side, so this is a single ``k``, not one per
#: arm as in LOCAL mode.
SEARCH_CANDIDATES = 30


def build_label_filter(role: Role) -> str:
    """The OData filter restricting results to labels this role may see.

    Written as an **allow-list** (``label eq 'public' or label eq 'internal'``) rather than a
    deny-list (``label ne 'restricted'``). The difference matters on the day a fourth label is
    added: an allow-list keeps new labels invisible until someone grants access deliberately, while
    a deny-list would expose them to everyone by default. Fail-closed, not fail-open.
    """
    permitted = sorted(label.value for label in allowed_labels(role))
    if not permitted:  # pragma: no cover - defensive; every role has at least public
        return "label eq '__none__'"
    return " or ".join(f"label eq '{value}'" for value in permitted)


class AzureSearchRetriever:
    """Hybrid vector + keyword retrieval against an Azure AI Search index."""

    backend_name = "azure-ai-search"

    def __init__(
        self,
        client: Any,
        embedder: Embedder,
        *,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        # The client is injected rather than constructed here so the contract tests can pass a
        # mock. It is typed ``Any`` because ``azure-search-documents`` is an optional extra and
        # importing it for a type would make the package unimportable without Azure installed.
        self._client = client
        self.embedder = embedder
        self.rrf_k = rrf_k

    @classmethod
    def from_settings(cls, settings: Settings) -> AzureSearchRetriever:
        """Construct from configuration. Requires the ``azure`` extra and live credentials."""
        if not settings.has_azure_search:
            raise RuntimeError(
                "APP_MODE=azure needs AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY. "
                "See DEPLOY_RUNBOOK.md; this build environment has neither (BLOCKERS.md B2)."
            )

        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        assert settings.azure_search_endpoint is not None
        assert settings.azure_search_api_key is not None

        client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index,
            credential=AzureKeyCredential(settings.azure_search_api_key),
        )
        return cls(client=client, embedder=build_embedder(settings), rrf_k=settings.rrf_k)

    # ---------------------------------------------------------------- search --

    def _vector_query(self, query: str, top_k: int) -> Any:
        """Build the vectorised query for the ANN arm.

        The query text is the same stopword-filtered string the keyword arm receives, so the two
        arms answer the same question — matching LOCAL mode exactly.

        The SDK's ``VectorizedQuery`` is used when ``azure-search-documents`` is installed, and the
        equivalent REST payload otherwise. That fallback is not a shortcut: it is what lets CI
        verify the label filter, the hybrid request shape and the chunk mapping **without**
        installing an optional cloud SDK it has no service to talk to. Since ``VectorizedQuery`` is
        a thin wrapper that serialises to exactly this dict, testing against the dict tests the
        same request — and the governance guarantee lives in ``filter``, not in this object.
        """
        vector = self.embedder.embed([" ".join(tokenize_query(query))])[0]

        try:
            from azure.search.documents.models import VectorizedQuery
        except ImportError:
            return {
                "kind": "vector",
                "vector": vector.tolist(),
                "k": top_k,
                "fields": "embedding",
            }

        return VectorizedQuery(
            vector=vector.tolist(),
            k_nearest_neighbors=top_k,
            fields="embedding",
        )

    def search(self, query: str, *, role: Role, top_k: int = 6) -> RetrievalResult:
        label_filter = build_label_filter(role)

        # One request carrying both arms: `search_text` drives BM25 and `vector_queries` drives
        # ANN. AI Search fuses them with RRF server-side — the same algorithm LOCAL mode runs
        # in-process (PLAN.md D-005), which is what keeps the two modes comparable.
        results = self._client.search(
            search_text=query,
            vector_queries=[self._vector_query(query, SEARCH_CANDIDATES)],
            filter=label_filter,
            top=top_k,
            select=[
                "chunk_id",
                "policy_id",
                "policy_title",
                "section_path",
                "label",
                "version",
                "text",
                "start_offset",
                "end_offset",
                "ordinal",
            ],
        )

        permitted = allowed_labels(role)
        hits: list[Hit] = []
        for document in results:
            chunk = _document_to_chunk(document)
            # Defence in depth. The service already applied `filter`, so this can only fire if the
            # filter string is wrong or the index has documents with an unexpected label — exactly
            # the failure that must never be silent.
            if chunk.label not in permitted:  # pragma: no cover - defensive
                raise AssertionError(
                    f"AI Search returned {chunk.chunk_id} ({chunk.label}) for {role} "
                    f"despite filter {label_filter!r}"
                )
            hits.append(Hit(chunk=chunk, score=float(document.get("@search.score", 0.0))))

        return RetrievalResult(
            query=query,
            role=role,
            hits=hits,
            # Azure applies the filter server-side, so the withheld documents are never returned
            # and cannot be counted without a second, unfiltered query. Issuing one purely to
            # populate a UI counter would mean deliberately asking the service for restricted
            # documents on behalf of a user not entitled to them — the opposite of the control.
            # The count is reported as 0; the roles demo runs in LOCAL mode where it is free.
            withheld_count=0,
            allowed_labels=permitted,
        )

    def get_chunk(self, chunk_id: str, *, role: Role) -> Chunk | None:
        """Label-checked lookup by id.

        Returns ``None`` both for "not found" and for "not permitted", matching LOCAL mode: a
        distinguishable error would confirm that a restricted chunk exists.
        """
        try:
            document = self._client.get_document(key=chunk_id)
        except Exception:
            # The SDK raises ResourceNotFoundError for an unknown key. Catching broadly keeps this
            # module importable without the Azure packages installed.
            return None

        if document is None:
            return None

        chunk = _document_to_chunk(document)
        if chunk.label not in allowed_labels(role):
            return None
        return chunk


def _document_to_chunk(document: Any) -> Chunk:
    """Map an AI Search document into the shared :class:`Chunk`.

    ``start``/``end`` are stored as ``start_offset``/``end_offset`` in the index because ``start``
    and ``end`` are awkward field names in OData expressions. The mapping is asserted by the shared
    contract test, so the two modes cannot drift in what a chunk contains.
    """
    return Chunk(
        chunk_id=document["chunk_id"],
        policy_id=document["policy_id"],
        policy_title=document["policy_title"],
        section_path=document["section_path"],
        label=Label(document["label"]),
        version=document["version"],
        text=document["text"],
        start=int(document["start_offset"]),
        end=int(document["end_offset"]),
        ordinal=int(document["ordinal"]),
    )


def chunks_to_documents(chunks: Iterable[Chunk], vectors: Any) -> list[dict[str, Any]]:
    """Serialise chunks into AI Search documents, used by ``ingest.azure_index``.

    Kept here beside :func:`_document_to_chunk` so the write and read sides of the mapping are
    edited together. Splitting them across modules is how an index schema and its reader silently
    diverge.
    """
    documents: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        documents.append(
            {
                "chunk_id": chunk.chunk_id,
                "policy_id": chunk.policy_id,
                "policy_title": chunk.policy_title,
                "section_path": chunk.section_path,
                "label": chunk.label.value,
                "version": chunk.version,
                "text": chunk.text,
                "start_offset": chunk.start,
                "end_offset": chunk.end,
                "ordinal": chunk.ordinal,
                "embedding": vectors[index].tolist(),
            }
        )
    return documents
