"""Configuration for the MCP server (argv > environment > defaults)."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from . import release
from .store import default_data_dir

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerConfig:
    data_dir: Path
    db: Path
    release_repo: str
    release_tag: str
    check_interval: int
    refresh: bool

    @classmethod
    def from_sources(
        cls, argv: list[str] | None = None, env: dict | None = None
    ) -> "ServerConfig":
        env = dict(os.environ) if env is None else env
        parser = argparse.ArgumentParser(prog="cs2wt-mcp")
        parser.add_argument("--data-dir")
        parser.add_argument("--db")
        parser.add_argument("--release-repo")
        parser.add_argument("--release-tag")
        parser.add_argument("--check-interval", type=int)
        parser.add_argument("--no-refresh", action="store_true")
        ns = parser.parse_args(argv)

        data_dir = ns.data_dir or env.get("CS2WT_DATA_DIR") or str(default_data_dir())
        db = ns.db or env.get("CS2WT_DB") or str(Path(data_dir) / "docs.sqlite")
        release_repo = (
            ns.release_repo
            or env.get("CS2WT_RELEASE_REPO")
            or release.DEFAULT_REPO
        )
        release_tag = (
            ns.release_tag or env.get("CS2WT_RELEASE_TAG") or release.RELEASE_TAG
        )
        check_interval = (
            ns.check_interval
            if ns.check_interval is not None
            else int(env.get("CS2WT_CHECK_INTERVAL", 86400))
        )
        refresh = not ns.no_refresh and env.get("CS2WT_NO_REFRESH", "").lower() not in _TRUTHY

        return cls(
            data_dir=Path(data_dir),
            db=Path(db),
            release_repo=release_repo,
            release_tag=release_tag,
            check_interval=check_interval,
            refresh=refresh,
        )