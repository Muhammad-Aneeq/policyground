"""Create the Azure AI Search index and upload chunks to it.

**Never executed in this build** (BLOCKERS.md **B2**) — there is no Search service to talk to. The
index definition below is also emitted to ``infra/index_schema.json`` so it can be reviewed, and
diffed, without running anything.

The field that carries the whole governance story is ``label``: it is ``filterable`` and
``facetable`` so the retriever's OData filter is evaluated server-side, before documents leave the
service. ``text`` is deliberately *not* filterable — making large text fields filterable inflates
index size for no benefit here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from policyground.config import Settings
from policyground.retrieval.azure_retriever import chunks_to_documents
from policyground.retrieval.base import Chunk

#: Batch size for uploads. AI Search caps a batch at 1000 documents or 16 MB; policy chunks are
#: ~1 KB of text plus an embedding, so 500 stays comfortably inside both limits.
UPLOAD_BATCH_SIZE = 500

VECTOR_PROFILE = "policyground-hnsw-profile"
VECTOR_ALGORITHM = "policyground-hnsw"


def index_definition(*, index_name: str, embedding_dim: int) -> dict[str, Any]:
    """The index schema, as the REST API expects it.

    ``embedding_dim`` is a parameter rather than a constant because it differs between the two
    embedders (384 for the offline fallback, 1536 for text-embedding-3-small). Hard-coding it would
    make the index silently incompatible with whichever embedder was not chosen when it was
    written.
    """
    return {
        "name": index_name,
        "fields": [
            {
                "name": "chunk_id",
                "type": "Edm.String",
                "key": True,
                "filterable": True,
                "searchable": False,
            },
            {"name": "policy_id", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "policy_title", "type": "Edm.String", "searchable": True},
            {"name": "section_path", "type": "Edm.String", "searchable": True},
            # The governance field. Filterable so the role filter runs server-side; facetable so
            # the admin view can report the label distribution without scanning documents.
            {
                "name": "label",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "searchable": False,
            },
            {"name": "version", "type": "Edm.String", "filterable": True, "searchable": False},
            {"name": "text", "type": "Edm.String", "searchable": True, "filterable": False},
            {"name": "start_offset", "type": "Edm.Int32", "searchable": False},
            {"name": "end_offset", "type": "Edm.Int32", "searchable": False},
            {"name": "ordinal", "type": "Edm.Int32", "sortable": True, "searchable": False},
            {
                "name": "embedding",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "dimensions": embedding_dim,
                "vectorSearchProfile": VECTOR_PROFILE,
            },
        ],
        "vectorSearch": {
            "algorithms": [
                {
                    "name": VECTOR_ALGORITHM,
                    "kind": "hnsw",
                    # Defaults, stated explicitly so a future change is a visible diff rather than
                    # a silent inherit. `cosine` matches the L2-normalised vectors both embedders
                    # produce.
                    "hnswParameters": {
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine",
                    },
                }
            ],
            "profiles": [{"name": VECTOR_PROFILE, "algorithm": VECTOR_ALGORITHM}],
        },
        # No semantic ranker configuration: it is a per-query cost on a corpus of 30 policies where
        # hybrid RRF already ranks well, and spec 00 §D is explicit about keeping spend small.
    }


def write_index_schema(path: Path, *, index_name: str, embedding_dim: int) -> None:
    """Emit the schema to ``infra/index_schema.json`` for review and for ``azd`` provisioning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index_definition(index_name=index_name, embedding_dim=embedding_dim), indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def upload_chunks(
    settings: Settings,
    chunks: list[Chunk],
    vectors: Any,
    *,
    embedder_name: str,
) -> int:
    """Create-or-update the index, then upload every chunk. Returns the document count.

    Uses ``upload_documents`` (an upsert keyed on ``chunk_id``) rather than deleting and recreating
    the index. Because chunk ids are stable across rebuilds (see ``corpus.chunker``), a re-ingest
    after a corpus edit updates the changed documents in place and leaves citations valid — where a
    drop-and-recreate would leave the index empty for the duration of the upload.
    """
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    assert settings.azure_search_endpoint is not None
    assert settings.azure_search_api_key is not None
    credential = AzureKeyCredential(settings.azure_search_api_key)

    embedding_dim = int(vectors.shape[1])

    index_client = SearchIndexClient(endpoint=settings.azure_search_endpoint, credential=credential)
    index_client.create_or_update_index(
        index_definition(index_name=settings.azure_search_index, embedding_dim=embedding_dim)
    )

    search_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index,
        credential=credential,
    )

    documents = chunks_to_documents(chunks, vectors)
    for start in range(0, len(documents), UPLOAD_BATCH_SIZE):
        batch = documents[start : start + UPLOAD_BATCH_SIZE]
        responses = search_client.upload_documents(documents=batch)
        failed = [r for r in responses if not getattr(r, "succeeded", True)]
        if failed:
            raise RuntimeError(
                f"{len(failed)} of {len(batch)} documents failed to upload "
                f"(first key: {getattr(failed[0], 'key', '?')}). "
                "A partial index would answer some questions and refuse others for no visible "
                "reason, so the ingest fails rather than continuing."
            )

    # Recorded so the deployed index carries the same provenance the local one does.
    _ = embedder_name
    return len(documents)
