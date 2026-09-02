"""Gate 3 — refusal correctness, in both directions.

Spec 08 §10: "must refuse the unanswerables; must NOT refuse answerables."

The two directions are asserted **separately and never averaged**. A combined figure would let a
system that refuses everything score 50% while being useless, and one that answers everything score
50% while being dangerous. They fail differently, so they are measured differently.

These are *regression floors*, not aspirations — see the gate constants in ``metrics.py`` and the
failure analysis in ``docs/evals_methodology.md``. The floors sit a small margin below measured
gate-split performance, because a gate pinned to a number the system does not reach is a gate
everyone learns to ignore.
"""

from __future__ import annotations

from evals.metrics import MAX_FALSE_REFUSAL_RATE, MIN_REFUSAL_ON_UNANSWERABLE, Metrics


def test_refuses_the_unanswerable(metrics: Metrics) -> None:
    assert metrics.refusal_on_unanswerable >= MIN_REFUSAL_ON_UNANSWERABLE, (
        f"refused only {metrics.refusal_on_unanswerable:.2%} of unanswerable cases "
        f"(floor {MIN_REFUSAL_ON_UNANSWERABLE:.0%}). Answered: {metrics.missed_refusals}"
    )


def test_does_not_refuse_the_answerable(metrics: Metrics) -> None:
    assert metrics.false_refusal_rate <= MAX_FALSE_REFUSAL_RATE, (
        f"falsely refused {metrics.false_refusal_rate:.2%} of answerable cases "
        f"(ceiling {MAX_FALSE_REFUSAL_RATE:.0%}). Refused: {metrics.false_refusals}"
    )


def test_the_system_is_not_simply_refusing_everything(metrics: Metrics) -> None:
    """The degenerate solution, ruled out explicitly.

    Refusing everything would ace the unanswerable half. This asserts the system actually answers,
    so a high refusal-on-unanswerable figure means discrimination rather than silence.
    """
    assert metrics.answerable_runs > 0
    answered = metrics.answerable_runs * (1.0 - metrics.false_refusal_rate)
    assert answered >= metrics.answerable_runs * 0.5, (
        "fewer than half the answerable cases were answered — the system is refusing too much for "
        "the unanswerable-split figure to mean anything"
    )


def test_the_system_is_not_simply_answering_everything(metrics: Metrics) -> None:
    """The opposite degenerate solution."""
    assert metrics.unanswerable_runs > 0
    assert metrics.refusal_on_unanswerable > 0.5, (
        "the system refused fewer than half the unanswerable cases — it is guessing, which is the "
        "behaviour this whole project exists to prevent"
    )


def test_every_refusal_has_something_to_suggest(outcomes) -> None:  # type: ignore[no-untyped-def]
    """Spec 08 §4 F4: a refusal is "not found" *plus* the closest sections, not a dead end."""
    for outcome in outcomes:
        if not outcome.refused or outcome.refusal_reason == "empty_retrieval":
            continue
        assert outcome.retrieved_ids, (
            f"{outcome.case_id}/{outcome.role}: refused with reason "
            f"{outcome.refusal_reason!r} but retrieved nothing to suggest"
        )


def test_refusals_carry_a_reason(outcomes) -> None:  # type: ignore[no-untyped-def]
    """A corpus gap and a model failing to ground itself are different signals to an admin."""
    valid = {"insufficient_evidence", "no_surviving_claims", "empty_retrieval"}
    for outcome in outcomes:
        if outcome.refused:
            assert outcome.refusal_reason in valid, (
                f"{outcome.case_id}/{outcome.role}: refusal reason {outcome.refusal_reason!r}"
            )


def test_refusals_carry_no_claims(outcomes) -> None:  # type: ignore[no-untyped-def]
    """The structural half of "never styled like a normal answer", checked on real runs."""
    for outcome in outcomes:
        if outcome.refused:
            assert outcome.claims == [], (
                f"{outcome.case_id}/{outcome.role}: refused but carried "
                f"{len(outcome.claims)} claims"
            )
