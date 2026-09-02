"""Chat clients for the compose step: OpenAI, Azure OpenAI, and the offline extractive stub.

The stub is what this build actually runs on (BLOCKERS.md **B1**), so it is worth being precise
about what it is and — more importantly — what it must **not** be allowed to prove.

**What it is.** An extractive composer. It selects sentences from the retrieved passages that
overlap the question and emits them as claims citing the chunk they came from. It never generates
text that is not in a passage, so it exercises the entire graph — schema validation, the citation
strip, refusal conversion, persistence, the UI — with no model.

**What it must not be allowed to prove.** Being extractive, it is incapable of fabricating a
citation id or importing outside knowledge. If the citation-check tests ran only against its
output, they would pass trivially and demonstrate nothing about the control. That is why
``tests/test_citation_check.py`` drives the strip with **hand-written adversarial model output** —
empty citations, fabricated ids, prose-only claims — rather than with anything this class produces.
The stub proves the pipeline runs; the fixtures prove the pipeline is safe.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol, runtime_checkable

from policyground.answers.schema import Claim
from policyground.config import Settings
from policyground.graph.prompts import SYSTEM_PROMPT, build_user_message
from policyground.retrieval.base import Chunk
from policyground.retrieval.embeddings import term_matches, tokenize, tokenize_query

logger = logging.getLogger(__name__)

#: Sentence boundary: ``.``, ``?`` or ``!`` followed by whitespace and a capital or an opening
#: bracket. Deliberately **not** ``;`` or ``:`` — an earlier version split on those and produced
#: claims like "in full; the general capitalisation threshold of USD 5,000, the IT equipment
#: capitalisation", which cites correctly and reads as broken.
_SENTENCE_RE = re.compile(r"(?<=[.?!])\s+(?=[A-Z(])")

#: Numbered list items ("1. ", "12) "), kept whole like table rows.
_LIST_ITEM_RE = re.compile(r"^\d+[.)]\s")


@runtime_checkable
class ChatClient(Protocol):
    """Turns a question plus passages into draft claims. Output is untrusted by construction."""

    name: str

    def compose(self, question: str, chunks: list[Chunk]) -> list[Claim]:
        """Return draft claims. May be empty, may cite fabricated ids — the caller checks."""
        ...


def parse_claims(payload: str) -> list[Claim]:
    """Parse a model's JSON response into claims, discarding anything malformed.

    Malformed entries are dropped rather than raising. A model that returns nine good claims and
    one with a non-string ``text`` should produce nine claims, not an error page — and the dropped
    one is exactly what the strip would have removed anyway. What is *not* tolerated is inventing a
    default: a claim missing ``citation_ids`` is dropped, never given an empty list, because an
    empty list would then be silently stripped downstream and counted as a different failure.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # Models sometimes wrap JSON in a markdown fence despite being told not to.
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", payload, re.DOTALL)
        if not fenced:
            logger.warning("compose returned unparseable output (%d chars)", len(payload))
            return []
        try:
            data = json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return []

    if not isinstance(data, dict):
        return []

    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list):
        return []

    claims: list[Claim] = []
    for entry in raw_claims:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        ids = entry.get("citation_ids")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(ids, list):
            continue
        claims.append(
            Claim(text=text.strip(), citation_ids=[str(i) for i in ids if isinstance(i, str | int)])
        )
    return claims


class OfflineComposer:
    """Extractive composer used when no model credential is available.

    Every claim it emits is a verbatim span of a retrieved passage, citing that passage. It cannot
    hallucinate because it does not generate.
    """

    name = "offline-extractive"

    def __init__(self, max_claims: int = 4, min_overlap: int = 1) -> None:
        self.max_claims = max_claims
        self.min_overlap = min_overlap

    def compose(self, question: str, chunks: list[Chunk]) -> list[Claim]:
        query_terms = set(tokenize_query(question))
        if not query_terms or not chunks:
            return []

        scored: list[tuple[float, int, str, str]] = []

        for rank, chunk in enumerate(chunks):
            for sentence in self._sentences(chunk.text):
                terms = set(tokenize(sentence))
                # Near-match, not exact: the sentence stating the nightly room rate cap does
                # not contain the word "night", and an exact-match composer skipped it while
                # happily citing an adjacent sentence that did.
                overlap = sum(1 for term in query_terms if term_matches(term, terms))
                if overlap < self.min_overlap:
                    continue
                # Favour overlap, then earlier-ranked chunks; normalise by length so a long
                # paragraph does not win merely by containing more words.
                score = overlap / (1.0 + len(terms) ** 0.5) - rank * 0.001
                scored.append((score, rank, sentence, chunk.chunk_id))

        scored.sort(key=lambda item: (-item[0], item[1], item[3]))

        claims: list[Claim] = []
        seen: set[str] = set()
        for _, _, sentence, chunk_id in scored:
            key = sentence.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append(Claim(text=sentence.strip(), citation_ids=[chunk_id]))
            if len(claims) >= self.max_claims:
                break

        return claims

    @staticmethod
    def _sentences(text: str) -> list[str]:
        """Split a passage into candidate claims.

        Three rules, each fixing something observed in the output rather than anticipated:

        * **Split only on sentence-ending punctuation followed by a capital.** An earlier version
          also split on ``;`` and ``:``, which produced claims like *"in full; the general
          capitalisation threshold of USD 5,000, the IT equipment capitalisation"* — a fragment that
          cites correctly and reads as broken. A claim the reader cannot parse is not an answer.
        * **Keep table rows and list items whole.** In this corpus the answer to "who approves a
          purchase of X?" often *is* a table row, and splitting one mid-row produces nonsense.
        * **Drop fragments that start mid-sentence.** A piece beginning with a lowercase word is
          almost always the tail of a sentence whose head was on the previous line.
        """
        pieces: list[str] = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith(("|", "-", "*")) or _LIST_ITEM_RE.match(stripped):
                pieces.append(stripped)
                continue

            pieces.extend(part.strip() for part in _SENTENCE_RE.split(stripped) if part.strip())

        return [
            piece
            for piece in pieces
            if len(piece) > 25 and (piece[0].isupper() or not piece[0].isalpha())
        ]


class OpenAIComposer:
    """The real compose step. Untested against the live API in this build (BLOCKERS.md **B1**)."""

    def __init__(self, model: str, api_key: str, temperature: float = 0.0) -> None:
        self.name = f"openai:{model}"
        self.model = model
        self.temperature = temperature
        self._api_key = api_key

    def _client(self) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=self._api_key)

    def compose(self, question: str, chunks: list[Chunk]) -> list[Claim]:
        response = self._client().chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(question, chunks)},
            ],
        )
        return parse_claims(response.choices[0].message.content or "{}")


class AzureOpenAIComposer(OpenAIComposer):
    """Azure OpenAI variant. Same prompt, same parsing, different endpoint.

    Subclassing rather than duplicating keeps the *prompt* and the *parsing* identical between
    modes by construction — the two things that would change answers if they drifted.
    """

    def __init__(
        self,
        deployment: str,
        endpoint: str,
        api_key: str,
        api_version: str = "2024-10-21",
        temperature: float = 0.0,
    ) -> None:
        super().__init__(model=deployment, api_key=api_key, temperature=temperature)
        self.name = f"azure-openai:{deployment}"
        self._endpoint = endpoint
        self._api_version = api_version

    def _client(self) -> Any:
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=self._endpoint,
            api_key=self._api_key,
            api_version=self._api_version,
        )


def build_chat_client(settings: Settings) -> ChatClient:
    """Select the composer from the environment, never raising for a missing credential.

    Falls back to the offline stub rather than failing, because the whole product must run end to
    end with no key. Which composer was used is recorded on every answer's trace, so a reader can
    always tell whether a number came from a model or from the stub.
    """
    if settings.has_azure_openai:
        assert settings.azure_openai_endpoint is not None
        assert settings.azure_openai_api_key is not None
        return AzureOpenAIComposer(
            deployment=settings.azure_openai_chat_deployment,
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
        )
    if settings.has_openai_key:
        assert settings.openai_api_key is not None
        return OpenAIComposer(model=settings.openai_chat_model, api_key=settings.openai_api_key)

    logger.warning(
        "no model credential: compose is using the offline extractive stub, which selects "
        "sentences from retrieved passages rather than writing an answer (BLOCKERS.md B1)"
    )
    return OfflineComposer()
