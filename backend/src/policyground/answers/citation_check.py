"""The citation check. This is the load-bearing function of the whole product.

Spec 08 §4 F3: *"uncited claims stripped before render."* Spec 08 §8: the compose step is
*"forbidden from using non-retrieved knowledge (system prompt + citation_check enforcement)"*.

The system prompt is the polite half of that and is not a guarantee — a model can ignore it, and
under adversarial input it sometimes will. This module is the half that holds regardless, because
it runs *after* the model and does not ask for cooperation.

**Two failure classes are dropped, not one** (PLAN.md **D-007**):

1. A claim with **no citations**. Obvious, and the one most implementations handle.
2. A claim citing an id **not in the retrieved set**. Less obvious and more dangerous. A fabricated
   id renders in the UI as a superscript identical to a real one; the reader sees evidence-backed
   prose and has no way to tell. Dropping only the first class would let the more convincing failure
   through.

A claim citing a mix of valid and invalid ids keeps the claim and prunes the bad ids: the assertion
is still supported by real evidence, and discarding it would lose a correct answer over a
formatting error. But if *every* id on a claim is fabricated, the claim goes.

**Zero surviving claims converts the response into a refusal.** The caller does that; this module
reports it via :attr:`StripResult.all_dropped`. An empty answer is not an answer — it is a refusal
that has not admitted it yet.

Everything here is a pure function over plain data: no I/O, no model, no settings. That is what
makes the guarantee testable against hand-written adversarial model output rather than only against
whatever the offline stub happens to emit.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from policyground.answers.schema import Claim


class DropReason(StrEnum):
    """Why a claim was removed. Recorded per claim so the admin view can report *which* control
    fired, rather than only that something was stripped."""

    NO_CITATIONS = "no_citations"
    ALL_CITATIONS_UNKNOWN = "all_citations_unknown"
    EMPTY_TEXT = "empty_text"


@dataclass(frozen=True, slots=True)
class DroppedClaim:
    """A claim that did not survive, kept for the trace."""

    text: str
    citation_ids: tuple[str, ...]
    reason: DropReason


@dataclass(frozen=True, slots=True)
class StripResult:
    """Outcome of the check: what survived, what did not, and what the caller must do next."""

    kept: list[Claim] = field(default_factory=list)
    dropped: list[DroppedClaim] = field(default_factory=list)
    #: Ids that were cited but do not exist in the retrieved set — fabrications, in other words.
    unknown_ids: frozenset[str] = frozenset()
    #: Ids pruned from claims that were otherwise kept.
    pruned_ids: frozenset[str] = frozenset()

    @property
    def all_dropped(self) -> bool:
        """True when nothing survived and the caller must convert this to a refusal.

        Note this is False for an empty input: a compose step that returned no claims at all is an
        empty retrieval or a model failure, not a *stripping* outcome, and the caller distinguishes
        the two so the eval can count them separately.
        """
        return bool(self.dropped) and not self.kept

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def cited_ids(self) -> set[str]:
        """Ids actually referenced by surviving claims — the set the UI must render."""
        return {cid for claim in self.kept for cid in claim.citation_ids}


def strip_uncited(claims: Sequence[Claim], retrieved_ids: Iterable[str]) -> StripResult:
    """Remove claims that are not supported by the retrieved evidence.

    ``claims`` is never mutated: :class:`Claim` is frozen and surviving claims with pruned ids are
    rebuilt as new objects. Mutating the input would make the model's raw output unrecoverable, and
    the raw output is what the trace and the injection tests need to inspect.

    Order is preserved. The compose step orders claims to read as prose, and reordering them during
    a *safety* check would silently change the answer's meaning.
    """
    valid = set(retrieved_ids)

    kept: list[Claim] = []
    dropped: list[DroppedClaim] = []
    unknown: set[str] = set()
    pruned: set[str] = set()

    for claim in claims:
        ids = tuple(claim.citation_ids)

        if not claim.text.strip():
            # An empty claim cites nothing meaningful even when it carries ids. It would render as
            # a stray superscript attached to no assertion.
            dropped.append(DroppedClaim(claim.text, ids, DropReason.EMPTY_TEXT))
            continue

        if not ids:
            dropped.append(DroppedClaim(claim.text, ids, DropReason.NO_CITATIONS))
            continue

        # De-duplicate while preserving first-seen order: a model repeating the same id three times
        # would otherwise render three identical superscripts on one sentence.
        seen: dict[str, None] = {}
        for cid in ids:
            if cid in valid:
                seen.setdefault(cid, None)
            else:
                unknown.add(cid)

        surviving = list(seen)
        if not surviving:
            # Every id was fabricated. This is the dangerous case: without this branch the claim
            # would render as cited prose backed by nothing at all.
            dropped.append(DroppedClaim(claim.text, ids, DropReason.ALL_CITATIONS_UNKNOWN))
            continue

        if len(surviving) != len(ids):
            pruned.update(cid for cid in ids if cid not in valid)

        kept.append(
            claim if surviving == list(ids) else Claim(text=claim.text, citation_ids=surviving)
        )

    return StripResult(
        kept=kept,
        dropped=dropped,
        unknown_ids=frozenset(unknown),
        pruned_ids=frozenset(pruned),
    )


def citation_validity(claims: Sequence[Claim], retrieved_ids: Iterable[str]) -> float:
    """Fraction of claims that carry at least one *resolvable* citation.

    This is the eval's headline structural metric, and it must be exactly 1.0 (spec 08 §10:
    "Citation-validity 100 % structural"). Computed over claims *as rendered*, so it is a check on
    the pipeline's output rather than on the model's raw draft — the whole point being that the
    model's draft is allowed to be wrong as long as nothing wrong reaches the reader.

    Returns 1.0 for an empty list. No claims were rendered, so no invalid claim was rendered; the
    "did it refuse when it should have?" question is a separate metric and is not smuggled in here.
    """
    rendered = list(claims)
    if not rendered:
        return 1.0

    valid = set(retrieved_ids)
    supported = sum(1 for claim in rendered if any(cid in valid for cid in claim.citation_ids))
    return supported / len(rendered)
