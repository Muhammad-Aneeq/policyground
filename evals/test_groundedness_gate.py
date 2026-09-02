"""Gate 4 — groundedness, and the regression check against the committed baseline.

Spec 08 §10 asks for a groundedness suite with a gate; spec 08 §14 says to treat the judge as
**secondary** to the deterministic checks. Both are honoured: the deterministic gates fail
independently of this file, and nothing here can rescue them.

**In this build the groundedness figure comes from the offline deterministic proxy**
(BLOCKERS.md B1) — no live judge has scored these runs. That is *asserted below* rather than left in
a footnote, so a future change that quietly switched to a live judge would fail this file and force
the methodology page and README to be updated in the same commit, instead of the number silently
changing meaning while the prose still says "offline proxy".
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from evals.judge import (
    OFFLINE_PROVIDER,
    Judge,
    JudgeCacheMiss,
    JudgeConfig,
    build_payload,
    cache_key,
)
from evals.metrics import GROUNDEDNESS_TOLERANCE, Metrics, check_gate


def test_the_full_gate_passes(metrics: Metrics, baseline: dict[str, float] | None) -> None:
    """Every bar at once, so CI has one authoritative verdict beside the per-control files."""
    result = check_gate(metrics, baseline)
    assert result.passed, result.render()


def test_groundedness_has_not_regressed(
    metrics: Metrics, baseline: dict[str, float] | None
) -> None:
    if baseline is None or metrics.groundedness is None:
        pytest.skip("no baseline, or nothing judged")

    previous = baseline.get("groundedness")
    if previous is None:
        pytest.skip("baseline carries no groundedness figure")

    assert metrics.groundedness >= previous - GROUNDEDNESS_TOLERANCE, (
        f"groundedness {metrics.groundedness:.4f} vs baseline {previous:.4f} "
        f"(tolerance {GROUNDEDNESS_TOLERANCE})"
    )


def test_something_was_actually_judged(metrics: Metrics) -> None:
    """A groundedness score computed over zero judged runs is not a score."""
    assert metrics.judged_runs > 0, "no run produced claims, so nothing was judged"


def test_every_judged_run_records_its_provenance(outcomes) -> None:  # type: ignore[no-untyped-def]
    """No number without a stamp saying what produced it."""
    for outcome in outcomes:
        if outcome.groundedness is not None:
            assert outcome.judge_provider, (
                f"{outcome.case_id}/{outcome.role}: groundedness with no judge provenance"
            )


def test_this_build_uses_the_offline_proxy_and_says_so(outcomes) -> None:  # type: ignore[no-untyped-def]
    """Guards the honesty claim itself — see the module docstring."""
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("OFFLINE") not in {"1", "true", "TRUE"}:
        pytest.skip("a live judge is configured; the offline claim does not apply")

    judged = [outcome for outcome in outcomes if outcome.groundedness is not None]
    assert judged, "nothing judged"
    assert all(outcome.judge_provider == OFFLINE_PROVIDER for outcome in judged), (
        "some judgements did not come from the offline proxy, but docs/evals_methodology.md says "
        "they all do"
    )


def test_a_cache_miss_is_fatal_rather_than_a_neutral_default(tmp_path: Path) -> None:
    """The property that makes offline CI mean anything.

    A neutral score on a miss would let the suite pass while measuring nothing — a green gate that
    guarantees nothing, which is worse than no gate.
    """
    judge = Judge(JudgeConfig(), tmp_path, cache_only=True)

    with pytest.raises(JudgeCacheMiss, match="no default was invented"):
        judge.judge(
            "not-cached",
            "a question",
            [{"id": "X::001", "text": "some passage"}],
            [{"text": "a claim", "citation_ids": ["X::001"]}],
        )


def test_the_judge_cannot_be_shown_the_expected_answer() -> None:
    """Blindness enforced by a function signature, not by a comment.

    ``build_payload`` has no parameter for ground truth, so a future edit cannot pass one in by
    mistake — there is nowhere to put it.
    """
    assert set(inspect.signature(build_payload).parameters) == {"question", "passages", "claims"}


def test_re_pinning_the_judge_is_a_cache_miss() -> None:
    """Not a silent reinterpretation of old scores under new instructions."""
    payload = build_payload(
        "q", [{"id": "X::001", "text": "t"}], [{"text": "c", "citation_ids": ["X::001"]}]
    )
    keys = {
        cache_key(JudgeConfig(), "case", payload),
        cache_key(JudgeConfig.pinned_openai(), "case", payload),
        cache_key(JudgeConfig(rubric_version="99"), "case", payload),
    }
    assert len(keys) == 3


def test_the_cache_key_is_content_addressed() -> None:
    """Identical claims always score identically; different claims never share a key."""
    passages = [{"id": "X::001", "text": "t"}]

    def key_for(text: str) -> str:
        return cache_key(
            JudgeConfig(),
            "case",
            build_payload("q", passages, [{"text": text, "citation_ids": ["X::001"]}]),
        )

    assert key_for("a") == key_for("a")
    assert key_for("a") != key_for("b")


def test_a_refusal_is_not_judged_as_a_zero() -> None:
    """``None``, not 0.0.

    Folding a zero into the mean would punish the system for refusing — the behaviour this project
    exists to encourage. Refusal correctness is measured separately.
    """
    judge = Judge(JudgeConfig(), Path("/nonexistent"), cache_only=True)
    assert judge.judge("case", "q", [{"id": "X::001", "text": "t"}], []) is None
