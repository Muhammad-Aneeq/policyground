"""Run the question bank through the real graph and produce a scored run artifact.

Two decisions shape this module:

**The graph under test is the real one.** No stubs, no shortcuts, no mode where the eval takes a
different path from a user's question. The composer is whatever the environment selects (the offline
extractive stub in this build), which is recorded in the artifact so nobody has to guess what
produced a number.

**Restricted cases are run at every role, not just the privileged one.** A label-leak eval that only
asked a controller would prove nothing; a leak test that only asked a guest could be satisfied by a
retriever returning nothing at all. Running all three gives both the negative control (guest and
staff must refuse) and the positive control (a controller must actually answer), and the second is
what stops a broken retriever from scoring perfectly.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evals.judge import Judge, JudgeConfig
from policyground.answers.schema import Answer, Refusal
from policyground.config import Settings, get_settings
from policyground.corpus.chunker import chunk_corpus
from policyground.corpus.consistency import load_canaries
from policyground.corpus.loader import load_corpus
from policyground.graph.build import PolicyGroundGraph
from policyground.labels import Role
from policyground.retrieval.embeddings import HashEmbedder, build_embedder
from policyground.retrieval.local_retriever import LocalHybridRetriever
from policyground.retrieval.vocabulary import CorpusVocabulary

EVALS_DIR = Path(__file__).parent
CASES_PATH = EVALS_DIR / "cases.jsonl"
INJECTION_PATH = EVALS_DIR / "injection_cases.jsonl"
BASELINE_PATH = EVALS_DIR / "baseline.json"
JUDGE_CACHE = EVALS_DIR / "judge_cache"
ARTIFACTS_DIR = EVALS_DIR.parent / "artifacts"

#: Roles a restricted case is asked at. All three, for the reason in the module docstring.
ALL_ROLES = (Role.GUEST, Role.STAFF, Role.CONTROLLER)

#: The role an answerable or unanswerable case is asked at. `staff` sees public and internal
#: material, which is where all the non-restricted content lives.
DEFAULT_ROLE = Role.STAFF


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    kind: str
    split: str
    question: str
    expected_policy_ids: list[str]
    answerable_for: list[str]
    note: str = ""

    def roles_to_run(self) -> tuple[Role, ...]:
        return ALL_ROLES if self.kind == "restricted" else (DEFAULT_ROLE,)

    def should_answer(self, role: Role) -> bool:
        return role.value in self.answerable_for


@dataclass
class Outcome:
    """One (case, role) run, plus everything the metrics need."""

    case_id: str
    kind: str
    split: str
    role: str
    question: str
    refused: bool
    should_answer: bool
    sufficiency: float
    threshold: float
    withheld_count: int
    retrieved_ids: list[str] = field(default_factory=list)
    retrieved_labels: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)
    cited_policy_ids: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    stripped_claims: int = 0
    unknown_citation_ids: list[str] = field(default_factory=list)
    refusal_reason: str | None = None
    expected_policy_ids: list[str] = field(default_factory=list)
    #: Exact-substring leak detection: any canary appearing in retrieved context or rendered output.
    leaked_canaries: list[str] = field(default_factory=list)
    groundedness: float | None = None
    judge_provider: str | None = None

    @property
    def correct_refusal(self) -> bool:
        return self.refused == (not self.should_answer)

    @property
    def cited_expected_policy(self) -> bool:
        if not self.expected_policy_ids:
            return True
        return bool(set(self.cited_policy_ids) & set(self.expected_policy_ids))


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(Case(**json.loads(line)))
    return cases


def build_graph(settings: Settings, *, threshold: float | None = None) -> PolicyGroundGraph:
    """Build the graph from the corpus in-process.

    From source rather than from ``data/index.json``, so the suite fails when the *corpus* and the
    *code* disagree rather than when someone forgot to re-run ``pg ingest``. A stale committed index
    would otherwise let a corpus edit pass the whole gate.
    """
    docs = load_corpus(settings.policies_dir)
    chunks, _ = chunk_corpus(docs)

    embedder = build_embedder(settings)
    if isinstance(embedder, HashEmbedder):
        embedder = HashEmbedder(dim=settings.embedding_dim)
    vectors = embedder.embed([chunk.indexable_text for chunk in chunks])

    retriever = LocalHybridRetriever(
        chunks=chunks, vectors=vectors, embedder=embedder, rrf_k=settings.rrf_k
    )
    graph = PolicyGroundGraph.from_settings(settings, retriever)
    graph.vocabulary = CorpusVocabulary.from_chunks(chunks)
    if threshold is not None:
        graph.threshold = threshold
    graph.__post_init__()
    return graph


def run_case(
    graph: PolicyGroundGraph,
    case: Case,
    role: Role,
    canaries: dict[str, str],
) -> Outcome:
    state = graph.run_state(case.question, role=role)
    response = graph.to_response(state)

    retrieval = state["retrieval"]
    refused = isinstance(response, Refusal)

    claims = (
        [claim.model_dump(mode="json") for claim in response.claims]
        if isinstance(response, Answer)
        else []
    )
    citations = response.citations if isinstance(response, Answer) else []

    # Leak detection is an exact substring search over BOTH the context that entered the model and
    # the rendered output. Checking only the output would miss a leak that the composer happened not
    # to quote — the passage was still read, which is the thing spec 08 F6 forbids.
    context = " ".join(chunk.text for chunk in retrieval.chunks)
    rendered = (
        " ".join(claim["text"] for claim in claims)
        + " "
        + json.dumps([c.model_dump(mode="json") for c in citations], ensure_ascii=False)
    )
    permitted_policies = {policy_id for policy_id in canaries if _role_may_see_restricted(role)}
    leaked = [
        canary
        for policy_id, canary in canaries.items()
        if policy_id not in permitted_policies and (canary in context or canary in rendered)
    ]

    return Outcome(
        case_id=case.case_id,
        kind=case.kind,
        split=case.split,
        role=role.value,
        question=case.question,
        refused=refused,
        should_answer=case.should_answer(role),
        sufficiency=response.trace.sufficiency,
        threshold=response.trace.threshold,
        withheld_count=response.trace.withheld_count,
        retrieved_ids=retrieval.chunk_ids,
        retrieved_labels=sorted({chunk.label.value for chunk in retrieval.chunks}),
        cited_ids=sorted({cid for claim in claims for cid in claim["citation_ids"]}),
        cited_policy_ids=sorted({citation.policy_id for citation in citations}),
        claims=claims,
        stripped_claims=response.stripped_claims if isinstance(response, Answer) else 0,
        unknown_citation_ids=list(state.get("unknown_citation_ids", [])),
        refusal_reason=response.reason if isinstance(response, Refusal) else None,
        expected_policy_ids=list(case.expected_policy_ids),
        leaked_canaries=leaked,
    )


def _role_may_see_restricted(role: Role) -> bool:
    from policyground.labels import Label, allowed_labels

    return Label.RESTRICTED in allowed_labels(role)


def run_bank(
    graph: PolicyGroundGraph,
    cases: list[Case],
    canaries: dict[str, str],
    *,
    judge: Judge | None = None,
) -> list[Outcome]:
    outcomes: list[Outcome] = []

    for case in cases:
        for role in case.roles_to_run():
            outcome = run_case(graph, case, role, canaries)

            if judge is not None and outcome.claims:
                passages = [
                    {"id": chunk.chunk_id, "text": chunk.text}
                    for chunk in graph.retriever.search(  # type: ignore[union-attr]
                        case.question, role=role, top_k=graph.default_top_k
                    ).chunks
                ]
                judgement = judge.judge(
                    f"{case.case_id}--{role.value}", case.question, passages, outcome.claims
                )
                if judgement is not None:
                    outcome.groundedness = judgement.normalised
                    outcome.judge_provider = judgement.provider

            outcomes.append(outcome)

    return outcomes


def sweep_threshold(
    settings: Settings,
    cases: list[Case],
    canaries: dict[str, str],
    *,
    candidates: list[float] | None = None,
) -> list[dict[str, float]]:
    """Measure both directions of refusal correctness across candidate thresholds.

    This is the calibration procedure (PLAN.md **D-019**), and it is run on the **calibration split
    only**. Publishing the whole curve rather than just the chosen point is deliberate: it shows how
    sharp the trade-off is, which is the thing a reader needs in order to judge whether the chosen
    threshold is a considered decision or a number that happened to work.

    The two directions are reported separately and never averaged. A single figure would let a
    threshold of 1.0 — refuse everything — look excellent on half the bank.
    """
    if candidates is None:
        candidates = [round(0.30 + 0.02 * step, 2) for step in range(21)]

    rows: list[dict[str, float]] = []
    for candidate in candidates:
        graph = build_graph(settings, threshold=candidate)
        outcomes = run_bank(graph, cases, canaries, judge=None)

        from evals.metrics import compute_metrics

        metrics = compute_metrics(outcomes)
        rows.append(
            {
                "threshold": candidate,
                "refusal_on_unanswerable": metrics.refusal_on_unanswerable,
                "false_refusal_rate": metrics.false_refusal_rate,
                # Youden's J: sensitivity + specificity - 1. Maximising it picks the point that
                # best separates the two classes without favouring either, which is what "both
                # directions matter equally" means numerically.
                "youden_j": round(metrics.refusal_on_unanswerable - metrics.false_refusal_rate, 4),
            }
        )

    return rows


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=EVALS_DIR.parent,
        ).stdout.strip()
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PolicyGround eval bank.")
    parser.add_argument("--split", choices=["calibration", "gate", "all"], default="all")
    parser.add_argument(
        "--write-cache",
        action="store_true",
        help="allow the judge to populate its cache (otherwise a miss is fatal)",
    )
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args(argv)

    from evals.metrics import compute_metrics

    settings = get_settings()
    cases = load_cases()
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]

    canaries = load_canaries(settings.canaries_path)
    graph = build_graph(settings, threshold=args.threshold)
    judge = Judge(JudgeConfig.from_env(), JUDGE_CACHE, cache_only=not args.write_cache)

    outcomes = run_bank(graph, cases, canaries, judge=judge)
    metrics = compute_metrics(outcomes)

    payload = {
        "commit": git_commit(),
        "split": args.split,
        "threshold": graph.threshold,
        "embedder": graph.embedder_name,
        "composer": graph.client.name,
        "judge": f"{judge.config.provider}:{judge.config.model}",
        "judge_offline": judge.config.is_offline,
        "judge_cache_hits": judge.hits,
        "judge_cache_misses": judge.misses,
        "cases": len(cases),
        "runs": len(outcomes),
        "metrics": asdict(metrics),
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }

    artifact_path = args.artifact or (ARTIFACTS_DIR / f"run-{args.split}.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )

    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps(
                {
                    "note": (
                        "Committed baseline for the CI regression gate. Produced by the offline "
                        "embedder and composer (BLOCKERS.md B1) — see docs/evals_methodology.md."
                    ),
                    "split": args.split,
                    "threshold": graph.threshold,
                    "embedder": graph.embedder_name,
                    "composer": graph.client.name,
                    "judge": f"{judge.config.provider}:{judge.config.model}",
                    "metrics": asdict(metrics),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print(metrics.render())
    print(f"\nartifact: {artifact_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
