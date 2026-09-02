"""``corpus/MANIFEST.json`` — a content hash per policy, committed to the repo.

The manifest answers two questions that come up constantly with a RAG corpus and are otherwise
guesswork: *is the index I am querying built from the policies in this commit?* and *which
policies changed since the last ingest?*

Hashes cover the **whole file including front-matter**, because a label changed from ``internal``
to ``restricted`` must invalidate the index just as surely as edited prose would — that edit
changes who may retrieve the chunk.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from policyground.corpus.models import PolicyDoc


def policy_digest(doc: PolicyDoc) -> str:
    """SHA-256 of the file's exact bytes, normalised for line endings.

    Normalisation matters on Windows: without it, the same content checked out with CRLF produces
    a different manifest than on CI, and every policy would look changed on every platform switch.
    """
    normalised = doc.raw.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalised).hexdigest()


def build_manifest(
    docs: list[PolicyDoc], *, chunk_counts: dict[str, int] | None = None
) -> dict[str, Any]:
    """The manifest payload, deterministic for a given corpus."""
    entries = []
    for doc in sorted(docs, key=lambda d: d.policy_id):
        entry: dict[str, Any] = {
            "policy_id": doc.policy_id,
            "title": doc.title,
            "label": doc.label.value,
            "version": doc.front_matter.version,
            "owner": doc.front_matter.owner,
            "effective_date": doc.front_matter.effective_date.isoformat(),
            "category": doc.front_matter.category,
            "source_path": doc.source_path,
            "sections": len(doc.sections),
            "bytes": len(doc.raw.replace("\r\n", "\n").encode("utf-8")),
            "sha256": policy_digest(doc),
        }
        if chunk_counts is not None:
            entry["chunks"] = chunk_counts.get(doc.policy_id, 0)
        entries.append(entry)

    labels: dict[str, int] = {}
    for doc in docs:
        labels[doc.label.value] = labels.get(doc.label.value, 0) + 1

    payload: dict[str, Any] = {
        "schema": "policyground/manifest/v1",
        "policy_count": len(entries),
        "labels": dict(sorted(labels.items())),
        "corpus_sha256": corpus_digest(docs),
        "policies": entries,
    }
    if chunk_counts is not None:
        payload["chunk_count"] = sum(chunk_counts.values())
    return payload


def corpus_digest(docs: list[PolicyDoc]) -> str:
    """One hash over the whole corpus — the value an index artifact records to prove provenance."""
    joined = "\n".join(
        f"{doc.policy_id}:{policy_digest(doc)}" for doc in sorted(docs, key=lambda d: d.policy_id)
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Write with a trailing newline and stable key order, so re-running produces no diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
