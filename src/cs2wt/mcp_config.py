"""Configuration for the MCP server (argv > environment > defaults)."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from .http import DEFAULT_UA
from .store import default_data_dir

DEFAULT_PREFIX = "Counter-Strike 2 Workshop Tools"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerConfig:
    data_dir: Path
    db: Path
    prefix: str
    ua: str
    cookie: str
    delay: float
    refresh: bool

    @classmethod
    def from_sources(
        cls, argv: list[str] | None = None, env: dict | None = None
    ) -> "ServerConfig":
        env = dict(os.environ) if env is None else env
        parser = argparse.ArgumentParser(prog="cs2wt-mcp")
        parser.add_argument("--data-dir")
        parser.add_argument("--db")
        parser.add_argument("--prefix")
        parser.add_argument("--ua")
        parser.add_argument("--cookie")
        parser.add_argument("--delay", type=float)
        parser.add_argument("--no-refresh", action="store_true")
        ns = parser.parse_args(argv)

        data_dir = ns.data_dir or env.get("CS2WT_DATA_DIR") or str(default_data_dir())
        db = ns.db or env.get("CS2WT_DB") or str(Path(data_dir) / "docs.sqlite")
        prefix = ns.prefix or env.get("CS2WT_PREFIX") or DEFAULT_PREFIX
        ua = ns.ua or env.get("CS2WT_UA") or DEFAULT_UA
        cookie = (
            ns.cookie
            or env.get("CS2WT_COOKIE")
            or str(Path(data_dir) / "cookies.txt")
        )
        delay = (
            ns.delay if ns.delay is not None else float(env.get("CS2WT_DELAY", 1.0))
        )
        refresh = not ns.no_refresh and env.get("CS2WT_NO_REFRESH", "").lower() not in _TRUTHY

        return cls(
            data_dir=Path(data_dir),
            db=Path(db),
            prefix=prefix,
            ua=ua,
            cookie=cookie,
            delay=delay,
            refresh=refresh,
        )