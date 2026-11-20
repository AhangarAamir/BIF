"""BIF: legal research agent (Agno) over contract PDFs with verified citations.

    uv run bif serve                      # AgentOS API + web UI
    uv run bif ingest [path] [--force]    # index files under the corpus folder
    uv run bif ask "question"             # one question from the terminal
    uv run bif reembed                    # rebuild vectors after changing the embedding model
    uv run bif status
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="bif", description="Legal research agent over your documents.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the API and web UI")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")

    ingest = sub.add_parser("ingest", help="index files under the corpus folder")
    ingest.add_argument("path", nargs="?", default="")
    ingest.add_argument("--force", action="store_true", help="re-index unchanged files")
    ingest.add_argument("--no-llm", action="store_true", help="skip the per-document profile call")
    ingest.add_argument("--prune", action="store_true", help="drop index rows for deleted files")
    ingest.add_argument("--workers", type=int, help="files processed in parallel (default 1; >1 can hit \"database is locked\")")

    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question", nargs="+")

    reembed_p = sub.add_parser("reembed", help="embed chunks with the configured embedding model")
    reembed_p.add_argument("--workers", type=int, help="embedding batches in parallel (default 1)")
    sub.add_parser("status", help="show index and model status")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        from bif.config import HOST, PORT

        uvicorn.run("bif.server:app", host=args.host or HOST, port=args.port or PORT, reload=args.reload)
        return

    if args.command == "ingest":
        from bif.ingest.pipeline import ingest_path, remove_missing

        def progress(event: dict) -> None:
            if event["type"] == "file":
                print(f"[{event['index']}/{event['total']}] {event['file']}", flush=True)

        report = ingest_path(args.path or None, force=args.force, use_llm=False if args.no_llm else None,
                             on_progress=progress, workers=args.workers)
        removed = report.removed or (remove_missing() if args.prune else [])
        print(
            f"\nadded {len(report.added)} · updated {len(report.updated)} · unchanged {len(report.skipped)}"
            f" · failed {len(report.failed)} · removed {len(removed)} · pages {report.pages} · chunks {report.chunks}"
        )
        for failure in report.failed:
            print(f"  FAILED {failure['file']}: {failure['error']}")
        for warning in report.warnings:
            print(f"  warning: {warning}")
        sys.exit(1 if report.failed else 0)

    if args.command == "ask":
        from bif.agent.agents import build_query_agent

        agent = build_query_agent()
        agent.print_response(" ".join(args.question), stream=False)
        return

    if args.command == "reembed":
        from bif.ingest.pipeline import reembed

        print(reembed(on_progress=lambda e: print(f"embedded {e['done']}/{e['total']}", flush=True), workers=args.workers))
        return

    if args.command == "status":
        from bif import settings
        from bif.config import CORPUS_DIR
        from bif.index import store

        profile = settings.active_profile()
        emb = settings.load().embedding
        print(f"corpus:     {CORPUS_DIR}")
        print(f"chat model: {profile.name} → {profile.model} @ {profile.base_url}")
        print(f"embeddings: {emb.model} @ {emb.base_url} ({'on' if emb.enabled else 'off'})")
        print(f"index:      {store.stats()}")
        return

    parser.print_help()
