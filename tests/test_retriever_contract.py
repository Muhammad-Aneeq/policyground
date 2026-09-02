"""One contract, both modes — the test that makes the two-mode claim checkable.

PLAN.md **D-003** says LOCAL and AZURE implement a single ``Retriever`` interface so that
everything downstream is identical between modes. That is easy to *assert in a README* and easy to
quietly break. These tests run the same assertions against both implementations, with the Azure
SDK replaced by a fake that behaves like AI Search: it applies the OData ``filter`` itself, so a
retriever that forgot to send one would return restricted documents and fail here.

**AZURE mode has never run against a live Azure AI Search service** (BLOCKERS.md **B2**). What
these tests can prove without a subscription is the part that actually carries the governance
guarantee — that the filter is constructed correctly, sent on every query, and applied before
documents are returned — plus that both modes produce the same ``Chunk`` shape. What they cannot
prove is that the service behaves as documented. That distinction is stated here rather than
implied.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from policyground.labels import Label, Role, allowed_labels
from policyground.retrieval.azure_retriever import (
    AzureSearchRetriever,
    build_label_filter,
    chunks_to_documents,
)
from policyground.retrieval.base import Chunk, Retriever
from policyground.retrieval.embeddings import HashEmbedder
from policyground.retrieval.local_retriever import LocalHybridRetriever

_LABEL_CLAUSE_RE = re.compile(r"label eq '([a-z]+)'")


class FakeSearchClient:
    """Stands in for ``azure.search.documents.SearchClient``.

    It is deliberately not a bare Mock. A Mock records that ``filter=`` was passed but happily
    returns restricted documents anyway, so every leak assertion would pass vacuously. This fake
    *honours* the filter, which is what makes the tests below mean something.
    """

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)

        permitted = set(_LABEL_CLAUSE_RE.findall(kwargs.get("filter") or ""))
        query_terms = {t for t in re.findall(r"[a-z0-9]+", kwargs["search_text"].lower())}

        matched = []
        for document in self.documents:
            if document["label"] not in permitted:
                continue  # the service applies the filter, as AI Search does
            haystack = f"{document['policy_title']} {document['section_path']} {document['text']}"
            overlap = len(query_terms & set(re.findall(r"[a-z0-9]+", haystack.lower())))
            if overlap:
                matched.append({**document, "@search.score": float(overlap)})

        matched.sort(key=lambda d: (-d["@search.score"], d["chunk_id"]))
        return matched[: kwargs.get("top", 6)]

    def get_document(self, *, key: str) -> dict[str, Any] | None:
        for document in self.documents:
            if document["chunk_id"] == key:
                return document
        raise KeyError(key)  # the SDK raises ResourceNotFoundError


@pytest.fixture
def azure_retriever(chunks: list[Chunk], settings) -> AzureSearchRetriever:  # type: ignore[no-untyped-def]
    embedder = HashEmbedder(dim=settings.embedding_dim)
    vectors = embedder.embed([chunk.indexable_text for chunk in chunks])
    documents = chunks_to_documents(chunks, vectors)
    return AzureSearchRetriever(client=FakeSearchClient(documents), embedder=embedder)


@pytest.fixture
def both_retrievers(
    retriever: LocalHybridRetriever, azure_retriever: AzureSearchRetriever
) -> dict[str, Retriever]:
    return {"local": retriever, "azure": azure_retriever}


# ------------------------------------------------------- the shared contract --


def test_both_satisfy_the_retriever_protocol(both_retrievers: dict[str, Retriever]) -> None:
    for name, implementation in both_retrievers.items():
        assert isinstance(implementation, Retriever), f"{name} does not satisfy the Protocol"
        assert implementation.backend_name


@pytest.mark.parametrize("mode", ["local", "azure"])
@pytest.mark.parametrize("role", [Role.GUEST, Role.STAFF, Role.CONTROLLER])
def test_no_disallowed_label_is_ever_returned(
    both_retrievers: dict[str, Retriever], mode: str, role: Role
) -> None:
    """The governance guarantee, asserted identically against both backends."""
    implementation = both_retrievers[mode]
    permitted = allowed_labels(role)

    for question in [
        "executive severance retention award accrual",
        "purchase price allocation goodwill deal costs",
        "litigation provision measurement",
        "capitalisation threshold",
    ]:
        result = implementation.search(question, role=role, top_k=8)
        for hit in result.hits:
            assert hit.chunk.label in permitted, f"{mode}/{role} leaked {hit.chunk.chunk_id}"


@pytest.mark.parametrize("mode", ["local", "azure"])
def test_both_return_the_same_chunk_shape(both_retrievers: dict[str, Retriever], mode: str) -> None:
    """A field lost in the Azure mapping would break citations only in the deployed mode."""
    result = both_retrievers[mode].search("capitalisation threshold", role=Role.STAFF, top_k=3)
    assert result.hits

    for hit in result.hits:
        chunk = hit.chunk
        assert isinstance(chunk, Chunk)
        assert chunk.chunk_id and chunk.policy_id and chunk.policy_title
        assert chunk.section_path and chunk.version and chunk.text
        assert isinstance(chunk.label, Label)
        assert isinstance(chunk.start, int) and isinstance(chunk.end, int)
        assert chunk.end > chunk.start
        assert isinstance(chunk.ordinal, int)


def test_both_agree_on_the_top_result_for_an_unambiguous_question(
    both_retrievers: dict[str, Retriever],
) -> None:
    """Not identical ranking — the scoring differs — but the same policy should win.

    Kept deliberately weak. Asserting identical ordering would encode the fake's scoring as the
    contract, which is not something the real service promises.
    """
    tops = {
        mode: implementation.search(
            "capitalisation threshold for IT equipment", role=Role.STAFF, top_k=5
        )
        for mode, implementation in both_retrievers.items()
    }
    for mode, result in tops.items():
        assert result.hits, f"{mode} returned nothing"
        assert any(hit.chunk.policy_id in {"PG-0003", "PG-0004"} for hit in result.hits), mode


@pytest.mark.parametrize("mode", ["local", "azure"])
def test_get_chunk_is_label_checked_in_both_modes(
    both_retrievers: dict[str, Retriever], mode: str, chunks: list[Chunk]
) -> None:
    """A leaked chunk id must not be a read primitive around the retriever, in either mode."""
    implementation = both_retrievers[mode]
    restricted = next(c for c in chunks if c.label is Label.RESTRICTED)
    public = next(c for c in chunks if c.label is Label.PUBLIC)

    assert implementation.get_chunk(restricted.chunk_id, role=Role.GUEST) is None
    assert implementation.get_chunk(restricted.chunk_id, role=Role.CONTROLLER) is not None
    assert implementation.get_chunk(public.chunk_id, role=Role.GUEST) is not None
    assert implementation.get_chunk("PG-9999::999", role=Role.CONTROLLER) is None


@pytest.mark.parametrize("mode", ["local", "azure"])
def test_result_metadata_is_populated_in_both_modes(
    both_retrievers: dict[str, Retriever], mode: str
) -> None:
    result = both_retrievers[mode].search("approval matrix", role=Role.STAFF, top_k=3)
    assert result.role is Role.STAFF
    assert result.allowed_labels == allowed_labels(Role.STAFF)
    assert result.query == "approval matrix"


# ------------------------------------------------- azure-specific assertions --


@pytest.mark.parametrize("role", list(Role))
def test_label_filter_is_an_allow_list(role: Role) -> None:
    """Fail-closed: a label added tomorrow is invisible until access is granted deliberately.

    A deny-list (``label ne 'restricted'``) would expose any new label to every role by default,
    which is the wrong default for the one control this project is about.
    """
    expression = build_label_filter(role)
    named = set(_LABEL_CLAUSE_RE.findall(expression))

    assert named == {label.value for label in allowed_labels(role)}
    assert " ne " not in expression, "filter must be an allow-list, not a deny-list"

    for label in Label:
        if label not in allowed_labels(role):
            assert f"'{label.value}'" not in expression


def test_every_query_sends_a_filter(azure_retriever: AzureSearchRetriever) -> None:
    """A query without a filter would return restricted documents from the service itself."""
    client = azure_retriever._client
    for role in Role:
        azure_retriever.search("approval limits", role=role, top_k=3)

    assert len(client.calls) == len(Role)
    for call in client.calls:
        assert call.get("filter"), "a search was issued with no label filter"


def test_hybrid_sends_both_arms_in_one_request(azure_retriever: AzureSearchRetriever) -> None:
    """Spec 08 F2 asks for hybrid: vector + keyword. Two sequential searches would not be that."""
    azure_retriever.search("three-way match tolerance", role=Role.STAFF, top_k=3)
    call = azure_retriever._client.calls[-1]

    assert call["search_text"] == "three-way match tolerance"
    assert call["vector_queries"], "no vector arm was sent"
    assert len(call["vector_queries"]) == 1


def test_selected_fields_cover_every_chunk_field(azure_retriever: AzureSearchRetriever) -> None:
    """A field missing from `select` returns None and breaks citations only in AZURE mode."""
    azure_retriever.search("anything", role=Role.STAFF, top_k=1)
    selected = set(azure_retriever._client.calls[-1]["select"])

    assert selected >= {
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
    }


def test_documents_round_trip_through_the_azure_mapping(chunks: list[Chunk], settings) -> None:  # type: ignore[no-untyped-def]
    """Write side and read side agree — the mapping cannot silently diverge."""
    from policyground.retrieval.azure_retriever import _document_to_chunk

    embedder = HashEmbedder(dim=settings.embedding_dim)
    vectors = embedder.embed([chunk.indexable_text for chunk in chunks[:20]])
    documents = chunks_to_documents(chunks[:20], vectors)

    for original, document in zip(chunks[:20], documents, strict=True):
        assert _document_to_chunk(document) == original


def test_azure_index_schema_makes_label_filterable() -> None:
    """The whole server-side filter depends on this one flag."""
    from policyground.ingest.azure_index import index_definition

    definition = index_definition(index_name="policyground-chunks", embedding_dim=384)
    fields = {field["name"]: field for field in definition["fields"]}

    assert fields["label"]["filterable"] is True
    assert fields["chunk_id"]["key"] is True
    assert fields["embedding"]["dimensions"] == 384
    assert (
        definition["vectorSearch"]["profiles"][0]["name"]
        == (fields["embedding"]["vectorSearchProfile"])
    )
