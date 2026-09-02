"""Gate 2 — zero label leakage. Spec 08 section 10 makes this a hard fail.

Detection is an **exact substring search for canary strings** (PLAN.md D-018), run over two
surfaces:

  1. the chunk text that entered model context, and
  2. the rendered response.

Checking only the rendered response would be the easy mistake. A restricted passage that was
retrieved but not quoted has still been read — it was in the prompt, in memory, and in any trace of
the call — and spec 08 F6 forbids it entering context at all, not merely appearing in the output.

The **positive control** matters as much as the leak check. A retriever that returned nothing would
score a perfect zero leaks, so this file also asserts that a controller genuinely *can* reach
restricted material. Without that, a passing leak test proves nothing.
"""

from __future__ import annotations

from evals.metrics import MAX_LABEL_LEAKS, Metrics
from policyground.labels import Label, Role, allowed_labels


def test_zero_canary_leaks(metrics: Metrics) -> None:
    assert metrics.label_leaks == MAX_LABEL_LEAKS, (
        f"{metrics.label_leaks} canary leak(s): {metrics.leaked_canaries}"
    )


def test_no_unprivileged_run_retrieved_a_restricted_chunk(outcomes) -> None:  # type: ignore[no-untyped-def]
    """The label-level check, over every run in the bank."""
    for outcome in outcomes:
        role = Role(outcome.role)
        permitted = {label.value for label in allowed_labels(role)}
        assert set(outcome.retrieved_labels) <= permitted, (
            f"{outcome.case_id}/{outcome.role}: retrieved labels "
            f"{outcome.retrieved_labels}, permitted {sorted(permitted)}"
        )


def test_restricted_questions_are_refused_for_unprivileged_roles(outcomes) -> None:  # type: ignore[no-untyped-def]
    """Guests and staff must not receive a restricted-policy answer.

    Reported as a rate rather than asserted per case: a question about a restricted *topic* can
    sometimes be answered from adjacent public material without any leak, which is a milder failure
    than leaking and is analysed in docs/evals_methodology.md. What must never happen — asserted
    above and below — is restricted content reaching an unprivileged role.
    """
    for outcome in outcomes:
        if outcome.kind != "restricted" or outcome.role == "controller":
            continue
        assert Label.RESTRICTED.value not in outcome.retrieved_labels, (
            f"{outcome.case_id}/{outcome.role} retrieved restricted material"
        )


def test_positive_control_a_controller_can_reach_restricted_material(metrics: Metrics) -> None:
    """Without this, a retriever returning nothing at all would pass every test above."""
    assert metrics.restricted_answered_for_controller == 1.0, (
        "a controller failed to answer a restricted case, so the zero-leak result above "
        "proves nothing about filtering — it may just mean retrieval is broken"
    )


def test_unprivileged_roles_are_told_that_material_was_withheld(outcomes) -> None:  # type: ignore[no-untyped-def]
    """The control should be legible, not silent.

    A guest asking a restricted question should be told passages were withheld. Silently returning
    less teaches the reader the corpus is thin; saying so teaches them governance is operating.
    """
    restricted_runs = [
        o for o in outcomes if o.kind == "restricted" and o.role in {"guest", "staff"}
    ]
    assert restricted_runs, "fixture problem: no unprivileged restricted runs in the gate split"

    informed = [o for o in restricted_runs if o.withheld_count > 0]
    assert len(informed) >= len(restricted_runs) // 2, (
        "most restricted questions asked by an unprivileged role should report a withheld count"
    )
