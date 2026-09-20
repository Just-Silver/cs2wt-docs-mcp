"""Command line interface for cs2wt-docs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .fetch import crawl
from .http import DEFAULT_UA, AnubisSession
from .index import DocIndex, build_index
from .sync import sync
from .wiki import HtmlClient

DEFAULT_PREFIX = "Counter-Strike 2 Workshop Tools"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cs2wt",
        description="Offline indexer for the Counter-Strike 2 Workshop Tools docs",
    )
    parser.add_argument("--data-dir", default="data", help="where raw docs are stored")
    parser.add_argument("--db", default=None, help="index path (default: <data-dir>/docs.sqlite)")
    parser.add_argument("--cookie", default="cookies.txt", help="Anubis cookie jar path")
    parser.add_argument("--ua", default=DEFAULT_UA, help="User-Agent (must stay stable)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")

    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download docs and write raw wikitext")
    fetch.add_argument("--prefix", default=DEFAULT_PREFIX, help="page title prefix to crawl")

    sync_parser = sub.add_parser("sync", help="incrementally update the local mirror")
    sync_parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="page title prefix to sync")
    sync_parser.add_argument("--dry-run", action="store_true", help="report changes only")

    sub.add_parser("build", help="build the FTS5 index from downloaded data")

    search = sub.add_parser("search", help="full-text search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    get = sub.add_parser("get", help="show a page by id or title")
    get.add_argument("key")

    sub.add_parser("list", help="list indexed pages")
    sub.add_parser("status", help="show index status")
    return parser


def _new_client(args) -> HtmlClient:
    session = AnubisSession(
        user_agent=args.ua, cookie_path=args.cookie, delay=args.delay
    )
    return HtmlClient(session)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = args.db or str(Path(args.data_dir) / "docs.sqlite")

    if args.command == "fetch":
        manifest = crawl(_new_client(args), prefix=args.prefix, out_dir=args.data_dir)
        print(f"done: {manifest['page_count']} pages -> {args.data_dir}")
        return 0

    if args.command == "sync":
        report = sync(
            _new_client(args),
            prefix=args.prefix,
            data_dir=args.data_dir,
            db_path=db,
            dry_run=args.dry_run,
        )
        print(report.summary())
        if args.dry_run:
            print("(dry run: nothing written)")
        return 0

    if args.command == "build":
        index = build_index(args.data_dir, db)
        print(f"indexed {index.count()} pages -> {db}")
        index.close()
        return 0

    if args.command == "search":
        index = DocIndex(db)
        hits = index.search(args.query, args.limit)
        if not hits:
            print("no results")
        for hit in hits:
            snippet = " ".join(hit["snippet"].split())
            print(f"\n{hit['title']}\n  {hit['url']}\n  {snippet}")
        index.close()
        return 0

    if args.command == "get":
        index = DocIndex(db)
        page = index.get(args.key)
        if page is None:
            print(f"not found: {args.key}", file=sys.stderr)
            index.close()
            return 1
        print(f"# {page['title']}")
        print(f"{page['url']}  (rev {page['revid']}, {page['timestamp']})\n")
        print(page["content"])
        index.close()
        return 0

    if args.command == "list":
        index = DocIndex(db)
        for title in index.list_titles():
            print(title)
        index.close()
        return 0

    if args.command == "status":
        index = DocIndex(db)
        for key in ("prefix", "source", "generated_at", "page_count"):
            print(f"{key}: {index.get_meta(key)}")
        print(f"indexed: {index.count()}")
        index.close()
        return 0

    return 2