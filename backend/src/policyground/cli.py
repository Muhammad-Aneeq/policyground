"""The ``pg`` command line — corpus checks, index rebuild, API server, evals.

argparse rather than a CLI framework: the surface is small, and one fewer dependency in a project
whose point is that its guarantees are inspectable is worth a few lines of boilerplate.

Exit codes are meaningful because CI reads them: ``0`` success, ``1`` a check failed, ``2`` a
usage or environment error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from policyground.config import AppMode, get_settings, repo_root
from policyground.corpus.consistency import check_corpus
from policyground.corpus.loader import CorpusError, load_corpus
from policyground.ingest.manifest import build_manifest, write_manifest

JUDGE_CACHE_DIR = repo_root() / "evals" / "judge_cache"

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pg",
        description="PolicyGround — governed finance RAG over a synthetic policy manual.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    corpus = subparsers.add_parser("corpus", help="corpus authoring checks")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)

    check = corpus_sub.add_parser(
        "check",
        help="verify cross-policy consistency, canaries and cross-references",
    )
    check.add_argument(
        "--quiet",
        action="store_true",
        help="print only failures",
    )

    corpus_sub.add_parser("manifest", help="rewrite corpus/MANIFEST.json")
    corpus_sub.add_parser("stats", help="print corpus statistics")

    ingest = subparsers.add_parser("ingest", help="build the retrieval index from corpus/")
    ingest.add_argument(
        "--rebuild",
        action="store_true",
        help="discard any existing index and build from scratch",
    )
    ingest.add_argument(
        "--mode",
        choices=[m.value for m in AppMode],
        default=None,
        help="override APP_MODE for this run",
    )

    evaluate = subparsers.add_parser(
        "eval", help="run the groundedness suite and record the result for the admin trend"
    )
    evaluate.add_argument("--split", choices=["calibration", "gate", "all"], default="gate")
    evaluate.add_argument(
        "--write-cache",
        action="store_true",
        help="allow the judge to populate its cache (otherwise a miss is fatal)",
    )

    serve = subparsers.add_parser("serve", help="run the FastAPI application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    return parser


# --------------------------------------------------------------- commands --


def cmd_corpus_check(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        docs = load_corpus(settings.policies_dir)
    except CorpusError as exc:
        print(f"corpus error: {exc}", file=sys.stderr)
        return EXIT_CHECK_FAILED

    report = check_corpus(
        docs,
        constants_path=settings.constants_path,
        canaries_path=settings.canaries_path,
    )

    if report.ok:
        if not args.quiet:
            print(f"{report.render()} ({len(docs)} policies)")
        return EXIT_OK

    print(report.render(), file=sys.stderr)
    return EXIT_CHECK_FAILED


def cmd_corpus_manifest(_: argparse.Namespace) -> int:
    settings = get_settings()
    docs = load_corpus(settings.policies_dir)
    payload = build_manifest(docs)
    write_manifest(settings.manifest_path, payload)
    print(
        f"wrote {settings.manifest_path.relative_to(settings.manifest_path.parents[1])} "
        f"({payload['policy_count']} policies, corpus {payload['corpus_sha256'][:12]}...)"
    )
    return EXIT_OK


def cmd_corpus_stats(_: argparse.Namespace) -> int:
    settings = get_settings()
    docs = load_corpus(settings.policies_dir)

    by_label: dict[str, int] = {}
    for doc in docs:
        by_label[doc.label.value] = by_label.get(doc.label.value, 0) + 1

    sections = sum(len(doc.sections) for doc in docs)
    words = sum(len(doc.body.split()) for doc in docs)

    print(f"policies : {len(docs)}")
    for label, count in sorted(by_label.items()):
        print(f"  {label:<11}: {count}")
    print(f"sections : {sections}")
    print(f"words    : {words:,}")
    print(f"avg secs : {sections / len(docs):.1f} per policy")
    return EXIT_OK


def cmd_ingest(args: argparse.Namespace) -> int:
    from policyground.ingest.pipeline import run_ingest

    settings = get_settings()
    mode = AppMode(args.mode) if args.mode else settings.app_mode
    result = run_ingest(settings, mode=mode, rebuild=args.rebuild)
    print(result.render())
    return EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    """Run the suite, apply the gate, and record a row for the admin trend chart.

    The eval writes to ``eval_runs`` rather than the API computing groundedness at request time:
    spec 08 §8 reserves the judge for eval only, and scoring every live query would put a model
    call on the serving path.
    """
    # `evals/` is a repository artifact, not part of the installed distribution — it holds the
    # question bank, the judge cache and the gate, none of which belong in a wheel. pytest finds it
    # via rootdir; the CLI has to say so explicitly.
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)

    from evals.harness import build_graph, git_commit, load_cases, run_bank
    from evals.judge import Judge, JudgeConfig
    from evals.metrics import check_gate, compute_metrics

    from policyground.corpus.consistency import load_canaries
    from policyground.db import repo
    from policyground.db.session import get_engine, init_db, session_scope

    settings = get_settings()
    cases = load_cases()
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]

    graph = build_graph(settings)
    judge = Judge(JudgeConfig.from_env(), JUDGE_CACHE_DIR, cache_only=not args.write_cache)
    outcomes = run_bank(graph, cases, load_canaries(settings.canaries_path), judge=judge)

    metrics = compute_metrics(outcomes)
    gate = check_gate(metrics)

    init_db(get_engine())
    with session_scope() as session:
        repo.record_eval_run(
            session,
            commit=git_commit(),
            groundedness=metrics.groundedness or 0.0,
            citation_validity=metrics.citation_validity,
            refusal_accuracy=metrics.refusal_accuracy,
            false_refusal_rate=metrics.false_refusal_rate,
            label_leaks=metrics.label_leaks,
            cases=len(cases),
            passed=gate.passed,
            offline=judge.config.is_offline,
            judge=f"{judge.config.provider}:{judge.config.model}",
            embedder=graph.embedder_name,
            notes=f"split={args.split}; threshold={graph.threshold}",
        )

    print(metrics.render())
    print()
    print(gate.render())
    return EXIT_OK if gate.passed else EXIT_CHECK_FAILED


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "policyground.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "corpus":
        handlers = {
            "check": cmd_corpus_check,
            "manifest": cmd_corpus_manifest,
            "stats": cmd_corpus_stats,
        }
        return handlers[args.corpus_command](args)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "serve":
        return cmd_serve(args)

    parser.print_help(sys.stderr)  # pragma: no cover - argparse enforces a command
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
