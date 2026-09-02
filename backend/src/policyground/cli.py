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

from policyground.config import AppMode, get_settings
from policyground.corpus.consistency import check_corpus
from policyground.corpus.loader import CorpusError, load_corpus
from policyground.ingest.manifest import build_manifest, write_manifest

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
    if args.command == "serve":
        return cmd_serve(args)

    parser.print_help(sys.stderr)  # pragma: no cover - argparse enforces a command
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
