"""Corpus vocabulary and document frequencies — what makes "off-corpus" detectable.

This exists because of a concrete measurement failure. The first sufficiency assessor scored a
question about cryptocurrency custody at 0.50 and one about biological assets at 0.68, against a
0.45 refusal threshold — it answered both from unrelated policies. The cause was that it treated
every query term as equally informative, so *"What is **our policy** on cryptocurrency custody?"*
earned most of its coverage from the word "policy", which appears in all 30 documents.

Document frequency fixes that. A term the corpus has never seen — "cryptocurrency", "biological",
"IAS" — is maximally informative *by its absence*: its presence in the question and absence from
the corpus is the single strongest available signal that the corpus cannot answer. Weighting
coverage by IDF makes that signal dominate, and makes matching a ubiquitous word worth almost
nothing.

The vocabulary is a property of the **corpus**, not of the retrieval backend, so it is built during
ingestion and persisted alongside the index. Both LOCAL and AZURE load the same artifact — refusal
behaviour must not change between modes, and it would if this were derived from whatever the
backend happened to expose.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from policyground.retrieval.base import Chunk
from policyground.retrieval.embeddings import NEAR_MATCH_PREFIX, tokenize

VOCABULARY_SCHEMA = "policyground/vocabulary/v1"

#: IDF assigned to a term the corpus has never contained. Computed as if the term appeared in half
#: a document — slightly rarer than the rarest real term, so an unknown term always outweighs a
#: known-but-rare one without being so extreme that one unknown word alone decides the outcome.
_UNKNOWN_DF = 0.5


@dataclass(frozen=True, slots=True)
class CorpusVocabulary:
    """Document frequencies over the chunk collection."""

    document_count: int
    document_frequency: dict[str, int]

    @property
    def _prefixes(self) -> frozenset[str]:
        """Five-character prefixes of every known term, for morphological near-matching.

        Without this, "night" is unknown to a corpus that says "nightly" and "capitalise" is
        unknown to one that says "capitalisation" — and the unknown-term penalty would fire on
        perfectly answerable questions, turning a vocabulary quirk into a false refusal.
        """
        return frozenset(
            term[:NEAR_MATCH_PREFIX]
            for term in self.document_frequency
            if len(term) >= NEAR_MATCH_PREFIX
        )

    @classmethod
    def from_chunks(cls, chunks: list[Chunk]) -> CorpusVocabulary:
        """Build from every chunk, regardless of label.

        Restricted chunks are included deliberately. This holds *counts of terms*, never text, and
        excluding them would make "severance" look like an unknown word to a guest — so the
        assessor would treat a question the corpus genuinely answers as off-corpus, and the refusal
        message would be wrong about why it was refusing. The honest answer to a guest asking about
        severance is "there is material here you may not see", which is what ``withheld_count``
        reports; it is not "this company has no severance policy".
        """
        frequency: dict[str, int] = {}
        for chunk in chunks:
            for term in set(tokenize(chunk.indexable_text)):
                frequency[term] = frequency.get(term, 0) + 1
        return cls(document_count=len(chunks), document_frequency=frequency)

    def idf(self, term: str) -> float:
        """Inverse document frequency, smoothed, with unknown terms scored highest.

        Uses the standard ``log(1 + N/df)`` form, which stays positive for a term appearing in every
        document (unlike ``log(N/df)``, which goes to zero and would make a ubiquitous term
        contribute literally nothing rather than nearly nothing).
        """
        df = self.document_frequency.get(term, 0) or _UNKNOWN_DF
        return math.log(1.0 + self.document_count / df)

    def is_known(self, term: str) -> bool:
        """Whether the corpus contains this term, allowing the same morphological near-match the
        sufficiency assessor uses when checking whether a term appears in retrieved text."""
        if term in self.document_frequency:
            return True
        return len(term) >= NEAR_MATCH_PREFIX and term[:NEAR_MATCH_PREFIX] in self._prefixes

    def unknown_terms(self, terms: list[str]) -> list[str]:
        """Query terms the corpus has never contained — the clearest off-corpus signal there is.

        Two exclusions, both to stop the signal firing on things that are not topics:

        * **Numbers.** *"Who approves a purchase of 60,000 dollars?"* tokenises to include "60" and
          "000", neither of which appears in the corpus. A number in a question is a *parameter*,
          not a subject, and counting it as evidence of off-corpus made that perfectly answerable
          question refuse.
        * **Very short tokens.** A three-letter token absent from a 22,000-word corpus is far more
          likely to be an abbreviation or noise than a topic the manual fails to cover.
        """
        return [
            term
            for term in terms
            if len(term) >= 4 and not term.isdigit() and not self.is_known(term)
        ]

    # ------------------------------------------------------------ persistence --

    def to_json(self) -> dict[str, object]:
        return {
            "schema": VOCABULARY_SCHEMA,
            "document_count": self.document_count,
            # Sorted so the artifact is byte-stable across rebuilds and produces no spurious diff.
            "document_frequency": dict(sorted(self.document_frequency.items())),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json(), indent=0, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def load(cls, path: Path) -> CorpusVocabulary:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != VOCABULARY_SCHEMA:
            raise ValueError(
                f"vocabulary schema {payload.get('schema')!r} is not {VOCABULARY_SCHEMA!r}; "
                "run `pg ingest --rebuild`"
            )
        return cls(
            document_count=int(payload["document_count"]),
            document_frequency={str(k): int(v) for k, v in payload["document_frequency"].items()},
        )
