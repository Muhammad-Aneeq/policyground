"""The citation strip, driven by adversarial model output.

Spec 08 §4 F3: *"uncited claims stripped before render."*

**Why these fixtures are hand-written.** The offline composer this build runs on is *extractive* —
it selects sentences from retrieved passages and cites the chunk they came from, so it is
structurally incapable of fabricating a citation id or omitting one. Testing the strip against its
output would pass every assertion below while proving nothing whatsoever about the control.

So every case here is a hand-authored model response of the kind a real model actually produces
under pressure: prose with no citation, a plausible-looking but nonexistent id, a mix of real and
invented ids, an id repeated three times, an empty claim. These are the inputs the strip exists for.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from policyground.answers.citation_check import (
    DropReason,
    citation_validity,
    strip_uncited,
)
from policyground.answers.schema import Claim

RETRIEVED = ["PG-0003::002", "PG-0007::003", "PG-0009::004"]


def claim(text: str, *ids: str) -> Claim:
    return Claim(text=text, citation_ids=list(ids))


# ------------------------------------------------------ the two drop classes --


def test_a_claim_with_no_citations_is_dropped() -> None:
    """Failure class 1: confident prose, no evidence."""
    result = strip_uncited([claim("The threshold is USD 5,000.")], RETRIEVED)

    assert result.kept == []
    assert result.dropped[0].reason is DropReason.NO_CITATIONS
    assert result.all_dropped


def test_a_claim_citing_only_a_fabricated_id_is_dropped() -> None:
    """Failure class 2 — the dangerous one.

    A fabricated id renders as a superscript identical to a real one. The reader sees
    evidence-backed prose and has no way to tell it is unsupported. An implementation that dropped
    only uncited claims would let this through (PLAN.md **D-007**).
    """
    result = strip_uncited(
        [claim("Crypto assets are held at fair value.", "PG-0099::001")], RETRIEVED
    )

    assert result.kept == []
    assert result.dropped[0].reason is DropReason.ALL_CITATIONS_UNKNOWN
    assert result.unknown_ids == frozenset({"PG-0099::001"})
    assert result.all_dropped


def test_a_fabricated_id_that_looks_exactly_like_a_real_one_is_still_dropped() -> None:
    """Off-by-one on a real id is the most plausible hallucination, and the hardest to eyeball."""
    result = strip_uncited([claim("Something plausible.", "PG-0003::003")], RETRIEVED)
    assert result.kept == []
    assert "PG-0003::003" in result.unknown_ids


def test_an_empty_claim_is_dropped_even_when_it_cites() -> None:
    """It would render as a stray superscript attached to no assertion."""
    result = strip_uncited([claim("   ", "PG-0003::002")], RETRIEVED)
    assert result.kept == []
    assert result.dropped[0].reason is DropReason.EMPTY_TEXT


# -------------------------------------------------------------- what survives --


def test_a_properly_cited_claim_survives_unchanged() -> None:
    original = claim("The general threshold is USD 5,000.", "PG-0003::002")
    result = strip_uncited([original], RETRIEVED)

    assert result.kept == [original]
    assert not result.dropped
    assert not result.all_dropped


def test_a_mixed_claim_keeps_the_text_and_prunes_the_bad_id() -> None:
    """Real evidence plus one invention: the assertion is still supported, so it stays.

    Dropping the whole claim would lose a correct, evidenced answer over a formatting error — which
    is a false refusal, and spec 08 §10 counts those as failures too.
    """
    result = strip_uncited(
        [claim("Approval limits escalate by band.", "PG-0007::003", "PG-0404::999")],
        RETRIEVED,
    )

    assert len(result.kept) == 1
    assert result.kept[0].citation_ids == ["PG-0007::003"]
    assert result.kept[0].text == "Approval limits escalate by band."
    assert result.pruned_ids == frozenset({"PG-0404::999"})
    assert result.unknown_ids == frozenset({"PG-0404::999"})


def test_duplicate_citation_ids_are_collapsed() -> None:
    """Three identical superscripts on one sentence is a rendering bug, not evidence."""
    result = strip_uncited(
        [claim("Cited thrice.", "PG-0003::002", "PG-0003::002", "PG-0003::002")], RETRIEVED
    )
    assert result.kept[0].citation_ids == ["PG-0003::002"]


def test_citation_order_within_a_claim_is_preserved() -> None:
    result = strip_uncited([claim("Two sources.", "PG-0009::004", "PG-0003::002")], RETRIEVED)
    assert result.kept[0].citation_ids == ["PG-0009::004", "PG-0003::002"]


def test_claim_order_is_preserved() -> None:
    """The composer orders claims to read as prose; a *safety* check must not reorder them."""
    claims = [
        claim("First.", "PG-0003::002"),
        claim("Second.", "PG-0007::003"),
        claim("Third.", "PG-0009::004"),
    ]
    result = strip_uncited(claims, RETRIEVED)
    assert [c.text for c in result.kept] == ["First.", "Second.", "Third."]


def test_surviving_claims_are_reported_with_their_ids() -> None:
    result = strip_uncited([claim("A.", "PG-0003::002"), claim("B.", "PG-0009::004")], RETRIEVED)
    assert result.cited_ids() == {"PG-0003::002", "PG-0009::004"}


# ------------------------------------------------------------ mixed batches --


def test_a_realistic_mixed_response_keeps_only_the_supported_claims() -> None:
    """What a real model response under pressure looks like: some good, some not."""
    claims = [
        claim("Capitalisation starts at USD 5,000.", "PG-0003::002"),
        claim("Anything below that is expensed immediately."),  # no citation
        claim("The CFO approves above USD 500,000.", "PG-0007::003"),
        claim("IFRS 16 requires this treatment.", "IFRS-16::001"),  # outside knowledge
        claim("Invoices match three ways.", "PG-0009::004", "PG-0000::000"),  # partly real
    ]

    result = strip_uncited(claims, RETRIEVED)

    assert [c.text for c in result.kept] == [
        "Capitalisation starts at USD 5,000.",
        "The CFO approves above USD 500,000.",
        "Invoices match three ways.",
    ]
    assert result.dropped_count == 2
    assert {d.reason for d in result.dropped} == {
        DropReason.NO_CITATIONS,
        DropReason.ALL_CITATIONS_UNKNOWN,
    }
    assert not result.all_dropped  # something survived, so this is still an answer


def test_all_dropped_signals_the_caller_to_refuse() -> None:
    """Spec: no citations at all → the response converts to a refusal."""
    result = strip_uncited(
        [claim("Unsupported one."), claim("Unsupported two.", "PG-9999::999")], RETRIEVED
    )
    assert result.kept == []
    assert result.all_dropped


def test_an_empty_input_is_not_reported_as_all_dropped() -> None:
    """Zero claims from compose is a *different* failure from every claim being stripped.

    The eval counts them separately: one says the model produced nothing, the other says it
    produced only unsupported assertions.
    """
    result = strip_uncited([], RETRIEVED)
    assert result.kept == []
    assert result.dropped == []
    assert not result.all_dropped


# ------------------------------------------------------------- immutability --


def test_the_input_claims_are_never_mutated() -> None:
    """The raw draft must stay recoverable — it is what the trace and injection tests inspect."""
    original = claim("Mixed.", "PG-0003::002", "PG-BAD::001")
    snapshot = list(original.citation_ids)

    strip_uncited([original], RETRIEVED)

    assert original.citation_ids == snapshot


def test_claim_is_frozen() -> None:
    """Structural: nothing downstream can quietly edit a claim's citations after the check."""
    with pytest.raises(ValidationError):
        claim("x", "PG-0003::002").text = "y"  # type: ignore[misc]


def test_citation_ids_has_no_default() -> None:
    """A model omitting the field must fail validation, not produce an uncited claim silently."""
    with pytest.raises(ValidationError):
        Claim(text="No ids field at all.")  # type: ignore[call-arg]


# ------------------------------------------------------- the headline metric --


def test_citation_validity_is_one_for_a_fully_cited_answer() -> None:
    claims = [claim("A.", "PG-0003::002"), claim("B.", "PG-0007::003")]
    assert citation_validity(claims, RETRIEVED) == 1.0


def test_citation_validity_detects_an_unsupported_rendered_claim() -> None:
    """If this ever drops below 1.0 in the eval, something reached a reader uncited."""
    claims = [claim("A.", "PG-0003::002"), claim("B.", "PG-NOPE::001")]
    assert citation_validity(claims, RETRIEVED) == 0.5


def test_citation_validity_of_stripped_output_is_always_one() -> None:
    """The invariant the eval gate asserts: post-strip output is 100% valid by construction."""
    messy = [
        claim("Good.", "PG-0003::002"),
        claim("Uncited."),
        claim("Fabricated.", "PG-XXXX::001"),
        claim("Partly good.", "PG-0009::004", "PG-YYYY::002"),
    ]
    result = strip_uncited(messy, RETRIEVED)
    assert citation_validity(result.kept, RETRIEVED) == 1.0


def test_citation_validity_of_no_claims_is_one_not_zero() -> None:
    """No claim was rendered, so no invalid claim was rendered.

    Whether the system *should* have answered is a separate metric (refusal correctness) and is
    deliberately not smuggled into this one.
    """
    assert citation_validity([], RETRIEVED) == 1.0


@pytest.mark.parametrize(
    "bad_ids",
    [
        ["PG-0003"],  # policy id without a chunk suffix
        ["pg-0003::002"],  # wrong case
        ["PG-0003::2"],  # unpadded ordinal
        ["PG-0003::002 "],  # trailing space
        [""],  # empty string
        ["../../etc/passwd"],  # path-ish junk
        ["PG-0003::002; DROP TABLE chunks"],
    ],
)
def test_near_miss_ids_are_all_rejected(bad_ids: list[str]) -> None:
    """Ids are matched exactly. Fuzzy matching here would be a way to smuggle one through."""
    result = strip_uncited([claim("Attempted.", *bad_ids)], RETRIEVED)
    assert result.kept == []
