"""Shared eval fixtures.

The bank is run **once per session** and every gate file reads from that one run. Each gate is a
separate file so a red CI run names the broken control — "label leakage failed" rather than "evals
failed" — but they must all be judging the same execution, or the metrics would not be comparable
with each other or with the committed baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.harness import BASELINE_PATH, JUDGE_CACHE, Case, build_graph, load_cases, run_bank
from evals.judge import Judge, JudgeConfig
from evals.metrics import Metrics, compute_metrics
from policyground.config import Settings, get_settings
from policyground.corpus.consistency import load_canaries


@pytest.fixture(scope="session")
def eval_settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def canaries(eval_settings: Settings) -> dict[str, str]:
    return load_canaries(eval_settings.canaries_path)


@pytest.fixture(scope="session")
def gate_cases() -> list[Case]:
    """The gate split only.

    The calibration split is deliberately excluded: the sufficiency threshold was tuned on it, so
    gating on it would be measuring the thermometer against itself (PLAN.md **D-019**).
    """
    return [case for case in load_cases() if case.split == "gate"]


@pytest.fixture(scope="session")
def outcomes(eval_settings: Settings, gate_cases: list[Case], canaries: dict[str, str]):  # type: ignore[no-untyped-def]
    """One run of the gate split through the real graph, shared by every gate file.

    The judge runs **cache-only**: a miss is a hard failure rather than a network call or a neutral
    default. A neutral default would let the suite pass while measuring nothing.
    """
    graph = build_graph(eval_settings)
    judge = Judge(JudgeConfig.from_env(), JUDGE_CACHE, cache_only=True)
    return run_bank(graph, gate_cases, canaries, judge=judge)


@pytest.fixture(scope="session")
def metrics(outcomes) -> Metrics:  # type: ignore[no-untyped-def]
    return compute_metrics(outcomes)


@pytest.fixture(scope="session")
def baseline() -> dict[str, float] | None:
    if not BASELINE_PATH.exists():
        return None
    payload = json.loads(Path(BASELINE_PATH).read_text(encoding="utf-8"))
    return payload.get("metrics")
