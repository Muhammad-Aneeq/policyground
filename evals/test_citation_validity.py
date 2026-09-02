"""Gate 1 — citation validity must be exactly 100%.

Spec 08 section 10: "Citation-validity 100 % structural (uncited stripped)."

This is an *absolute* bar, not a regression floor. It is a property of the code rather than of
retrieval quality: the strip runs after compose and removes anything unsupported, so a value below
1.0 does not mean retrieval got worse, it means the control stopped working.
"""

from __future__ import annotations

from evals.metrics import MIN_CITATION_VALIDITY, Metrics


def test_citation_validity_is_exactly_one(metrics: Metrics) -> None:
    assert metrics.citation_validity == MIN_CITATION_VALIDITY, (
        f"{metrics.unsupported_claims} of {metrics.rendered_claims} rendered claims had no "
        f"resolvable citation. Something reached a reader uncited."
    )


def test_every_rendered_claim_cites_a_retrieved_passage(outcomes) -> None:  # type: ignore[no-untyped-def]
    """The per-claim version, so a failure names the claim rather than a percentage."""
    for outcome in outcomes:
        retrieved = set(outcome.retrieved_ids)
        for claim in outcome.claims:
            assert claim["citation_ids"], (
                f"{outcome.case_id}/{outcome.role}: rendered a claim with no citations: "
                f"{claim['text'][:80]!r}"
            )
            assert any(cid in retrieved for cid in claim["citation_ids"]), (
                f"{outcome.case_id}/{outcome.role}: claim cites {claim['citation_ids']}, "
                f"none of which were retrieved"
            )


def test_no_fabricated_citation_id_survives(outcomes) -> None:  # type: ignore[no-untyped-def]
    """A fabricated id may be *drafted* — that is the model's business — but must never render."""
    for outcome in outcomes:
        rendered = {cid for claim in outcome.claims for cid in claim["citation_ids"]}
        assert rendered <= set(outcome.retrieved_ids), (
            f"{outcome.case_id}/{outcome.role}: rendered citation ids not in the retrieved set: "
            f"{sorted(rendered - set(outcome.retrieved_ids))}"
        )


def test_answers_have_at_least_one_claim(outcomes) -> None:  # type: ignore[no-untyped-def]
    """An empty answer is a refusal that has not admitted it yet."""
    for outcome in outcomes:
        if not outcome.refused:
            assert outcome.claims, f"{outcome.case_id}/{outcome.role}: answered with zero claims"


def test_the_expected_policy_is_cited_when_we_answer(metrics: Metrics) -> None:
    """Citing *something* is not enough — it should be the policy that actually covers the question.

    Without this, a system that answered every question from PG-0001 would score 100% on citation
    validity while being useless.
    """
    assert metrics.expected_policy_cited >= 0.90, (
        f"only {metrics.expected_policy_cited:.2%} of answered cases cited an expected policy"
    )
