"""The pinned LLM judge, its content-addressed cache, and its offline stand-in.

Adapted from the pattern in the sibling `finagent-evals` project (PLAN.md **D-010**). Three
properties do the work, and all three are structural rather than procedural:

1. **Pinned.** ``JudgeConfig`` carries a provider, a *dated* model snapshot and a rubric version,
   and all three go into every cache key. Re-pinning is a cache miss, not a silent reinterpretation
   of old scores under new instructions.

2. **Content-addressed.** The key is a hash of the exact claims and passages being judged, so
   identical input always yields an identical score. That is what makes a groundedness trend
   comparable across runs rather than a chart of judge variance.

3. **Cache-only in CI, where a miss is fatal.** Not a network call, not a neutral default. A
   neutral default would let the suite pass while measuring nothing, which is the worst outcome
   available: a green gate that guarantees nothing.

**In this build the judge is always the offline proxy** (BLOCKERS.md **B1**). Every judgement it
produces is stamped ``offline-fixture``, that stamp is carried into the run artifact, the
``eval_runs`` table and the admin chart, and ``docs/evals_methodology.md`` says plainly that no
live judge has scored this repo's committed runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.rubric import DIMENSIONS, MAX_PER_DIMENSION, RUBRIC_TEXT, RUBRIC_VERSION, normalised

OFFLINE_PROVIDER = "offline-fixture"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
#: Figures, thresholds and dates — the things FIDELITY is about.
_FIGURE_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
#: Characters illegal in a path component on at least one supported platform. Case ids become
#: directory names, and a cache that only populates on Linux would mean CI scoring from cache while
#: a developer on Windows silently scored nothing.
_PATH_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    """The pin. Every field is part of the cache key."""

    provider: str = OFFLINE_PROVIDER
    model: str = "none"
    #: Provider-side snapshot id. For OpenAI this is the dated model snapshot, never a floating
    #: alias: `gpt-4.1` silently becomes a different model over time, which would make cached
    #: scores incomparable with fresh ones while every cache key stayed identical.
    version: str = "none"
    temperature: float = 0.0
    rubric_version: str = RUBRIC_VERSION

    @property
    def is_offline(self) -> bool:
        return self.provider == OFFLINE_PROVIDER

    @classmethod
    def pinned_openai(cls) -> JudgeConfig:
        return cls(
            provider="openai",
            model="gpt-4.1-2025-04-14",
            version="2025-04-14",
            temperature=0.0,
        )

    @classmethod
    def from_env(cls) -> JudgeConfig:
        """Live pin when a key is present, offline stand-in otherwise (BLOCKERS.md B1)."""
        if os.environ.get("OFFLINE") in {"1", "true", "TRUE"}:
            return cls()
        return cls.pinned_openai() if os.environ.get("OPENAI_API_KEY") else cls()


@dataclass(frozen=True, slots=True)
class Judgement:
    """One judged answer."""

    scores: dict[str, int]
    note: str
    normalised: float
    provider: str
    model: str
    rubric_version: str
    cache_key: str

    @property
    def is_offline(self) -> bool:
        return self.provider == OFFLINE_PROVIDER

    def to_json(self) -> dict[str, Any]:
        return {
            "scores": dict(sorted(self.scores.items())),
            "note": self.note,
            "normalised": self.normalised,
            "provider": self.provider,
            "model": self.model,
            "rubric_version": self.rubric_version,
            "cache_key": self.cache_key,
        }


class JudgeCacheMiss(RuntimeError):
    """Cache-only scoring hit an answer with no cached judgement.

    Deliberately fatal. Returning a neutral score would let the suite pass while silently scoring
    nothing; calling the network would break offline CI.
    """


def build_payload(question: str, passages: list[dict[str, str]], claims: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    """Everything the judge sees.

    There is **no parameter for the expected answer**, by design. The judge assesses whether claims
    are supported by the passages in front of it, and cannot be handed the ground truth to grade
    against — because there is nowhere to put it. Blindness enforced by a function signature
    survives future edits in a way a comment does not.
    """
    return {
        "question": question,
        "passages": [
            {"id": passage["id"], "text": passage["text"]}
            for passage in sorted(passages, key=lambda p: p["id"])
        ],
        "claims": [
            {"text": claim["text"], "citation_ids": sorted(claim["citation_ids"])}
            for claim in claims
        ],
    }


def cache_key(config: JudgeConfig, case_id: str, payload: dict[str, Any]) -> str:
    """(pin, rubric version, case, content hash) → key.

    Canonical JSON so the key depends on the content and not on dict ordering.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(
        "|".join(
            [config.provider, config.model, config.version, config.rubric_version, case_id, body]
        ).encode("utf-8")
    ).hexdigest()


def cache_path(root: Path, config: JudgeConfig, case_id: str, key: str) -> Path:
    """Sharded by pin, then rubric, then case — so a re-pin does not invalidate by deletion.

    Case ids are sanitised because they become directory names. Windows rejects ``:`` in a path
    component, and a cache that only populates on Linux would mean CI scoring from cache while a
    developer on Windows silently scored nothing.
    """
    safe_case = _PATH_UNSAFE_RE.sub("_", case_id)
    return (
        root
        / f"{config.provider}-{config.model}"
        / f"rubric-{config.rubric_version}"
        / safe_case
        / f"{key}.json"
    )


class Judge:
    """Scores groundedness, from cache where possible."""

    def __init__(self, config: JudgeConfig, cache_root: Path, *, cache_only: bool = False) -> None:
        self.config = config
        self.cache_root = cache_root
        self.cache_only = cache_only
        self.hits = 0
        self.misses = 0

    def judge(
        self,
        case_id: str,
        question: str,
        passages: list[dict[str, str]],
        claims: list[dict[str, Any]],
    ) -> Judgement | None:
        """One judgement per answer. Returns ``None`` when there is nothing to judge.

        ``None`` is not zero. A refusal made no claims, so it has no groundedness — folding a 0.0
        into the mean would punish the system for refusing, which is the behaviour this project
        exists to encourage. Refusal correctness is measured separately.
        """
        if not claims:
            return None

        payload = build_payload(question, passages, claims)
        key = cache_key(self.config, case_id, payload)
        path = cache_path(self.cache_root, self.config, case_id, key)

        if path.exists():
            self.hits += 1
            return Judgement(**json.loads(path.read_text(encoding="utf-8")))

        self.misses += 1
        if self.cache_only:
            raise JudgeCacheMiss(
                f"no cached judgement for {case_id} (key {key[:12]}...).\n"
                f"  expected at: {path}\n"
                "  Scoring is cache-only, so nothing was called and no default was invented.\n"
                "  Run `uv run python -m evals.harness --write-cache` to populate it."
            )

        scores, note = (
            _offline_score(payload)
            if self.config.is_offline
            else _openai_score(self.config, payload)
        )
        judgement = Judgement(
            scores=scores,
            note=note,
            normalised=normalised(scores),
            provider=self.config.provider,
            model=self.config.model,
            rubric_version=self.config.rubric_version,
            cache_key=key,
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(judgement.to_json(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return judgement


# ------------------------------------------------- the offline stand-in --


def _offline_score(payload: dict[str, Any]) -> tuple[dict[str, int], str]:
    """Deterministic groundedness proxy, with no model (BLOCKERS.md **B1**).

    **Be clear about what this is.** It reads surface features — token overlap between a claim and
    its cited passage, whether the figures in a claim appear in that passage, whether the claim's
    vocabulary stays inside the passage set. It cannot assess meaning, so it cannot detect a claim
    that reuses a passage's words to say something the passage does not.

    **What it is nonetheless good at**, and why it is not merely decorative: the extractive
    composer this build runs on emits verbatim spans, so a claim whose figures are absent from its
    cited passage indicates a *real* pipeline defect (wrong citation attached to a claim), not a
    model hallucination. On this build's output the proxy is measuring something specific and true.

    Every judgement is stamped ``offline-fixture`` and the methodology page states that no live
    judge has scored this repo's committed runs.
    """
    passages = {passage["id"]: passage["text"] for passage in payload["passages"]}
    all_text = " ".join(passages.values()).lower()
    all_tokens = set(_TOKEN_RE.findall(all_text))

    support_total = fidelity_total = scope_total = 0
    claims = payload["claims"]

    for claim in claims:
        text = claim["text"]
        lowered = text.lower()
        claim_tokens = set(_TOKEN_RE.findall(lowered))

        cited_text = " ".join(passages.get(cid, "") for cid in claim["citation_ids"]).lower()
        cited_tokens = set(_TOKEN_RE.findall(cited_text))

        # SUPPORT: how much of the claim's vocabulary appears in the passage it cites. A verbatim
        # span scores 1.0; a paraphrase drops; an unrelated assertion collapses.
        overlap = len(claim_tokens & cited_tokens) / max(1, len(claim_tokens))
        if overlap >= 0.95:
            support = 3
        elif overlap >= 0.75:
            support = 2
        elif overlap >= 0.4:
            support = 1
        else:
            support = 0
        support_total += support

        # FIDELITY: every figure in the claim must appear in the passage it cites. This is the
        # dimension the proxy measures most honestly — it is an exact check, not a heuristic.
        figures = set(_FIGURE_RE.findall(text))
        cited_figures = set(_FIGURE_RE.findall(cited_text))
        if not figures:
            fidelity = 3  # nothing numeric to get wrong
        elif figures <= cited_figures:
            fidelity = 3
        elif figures & cited_figures:
            fidelity = 1
        else:
            fidelity = 0
        fidelity_total += fidelity

        # SCOPE: vocabulary outside the whole passage set is material from somewhere else.
        outside = claim_tokens - all_tokens
        outside_share = len(outside) / max(1, len(claim_tokens))
        if outside_share == 0.0:
            scope = 3
        elif outside_share <= 0.1:
            scope = 2
        elif outside_share <= 0.3:
            scope = 1
        else:
            scope = 0
        scope_total += scope

    count = max(1, len(claims))
    scores = {
        "support": min(MAX_PER_DIMENSION, round(support_total / count)),
        "fidelity": min(MAX_PER_DIMENSION, round(fidelity_total / count)),
        "scope": min(MAX_PER_DIMENSION, round(scope_total / count)),
    }
    note = (
        f"offline deterministic proxy over {len(claims)} claim(s); "
        "token overlap, figure containment and out-of-passage vocabulary. No language "
        "understanding."
    )
    return scores, note


# ------------------------------------------------------- the live judge --


def _openai_score(config: JudgeConfig, payload: dict[str, Any]) -> tuple[dict[str, int], str]:
    """Call the pinned model. Only reached when a key is present and OFFLINE is not set.

    Untested against the live API in this build (BLOCKERS.md B1). Deliberately minimal: temperature
    0, JSON response format, one call per case.
    """
    from openai import OpenAI

    client = OpenAI()
    response = client.chat.completions.create(
        model=config.model,
        temperature=config.temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": RUBRIC_TEXT},
            {"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=False)},
        ],
    )
    raw = json.loads(response.choices[0].message.content or "{}")
    scores = {dimension: int(raw.get(dimension, 0)) for dimension in DIMENSIONS}
    return scores, str(raw.get("note", ""))[:280]
