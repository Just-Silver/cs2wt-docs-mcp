"""Index lifecycle for the MCP server.

The reader is shared across handler threads; the background refresher uses
its own connection.  WAL keeps the two from blocking each other.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .fetch import crawl
from .http import AnubisSession
from .index import DocIndex, build_index
from .mcp_config import ServerConfig
from .sync import sync
from .wiki import WikiClient

INITIALIZING = "INITIALIZING"
REFRESHING = "REFRESHING"
READY = "READY"
ERROR = "ERROR"


def _indexed_count(db: Path) -> int:
    if not Path(db).exists():
        return 0
    try:
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT count(*) FROM docs").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _new_client(config: ServerConfig) -> WikiClient:
    session = AnubisSession(
        user_agent=config.ua, cookie_path=config.cookie, delay=config.delay
    )
    return WikiClient(session, api_url=config.api)


def default_refresh(config: ServerConfig, has_index: bool) -> None:
    """Full crawl when there is no index, incremental sync otherwise."""
    client = _new_client(config)
    if has_index:
        sync(
            client,
            prefix=config.prefix,
            data_dir=config.data_dir,
            db_path=config.db,
        )
        return
    crawl(client, prefix=config.prefix, out_dir=config.data_dir)
    index = build_index(config.data_dir, config.db)
    index.close()


class IndexManager:
    def __init__(self, config: ServerConfig, *, refresher=None) -> None:
        self.config = config
        self._refresher = refresher or default_refresh
        self._lock = threading.Lock()
        self._state = READY
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self._reader: DocIndex | None = None
        self._closed = False
        if Path(config.db).exists():
            self._reader = DocIndex(config.db, wal=True, check_same_thread=False)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if not self.config.refresh:
            return
        has_index = _indexed_count(self.config.db) > 0
        self._state = REFRESHING if has_index else INITIALIZING
        self._thread = threading.Thread(target=self._refresh, daemon=True)
        self._thread.start()

    def _refresh(self) -> None:
        try:
            has_index = _indexed_count(self.config.db) > 0
            self._refresher(self.config, has_index)
            self._state = READY
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            self._error = f"{type(exc).__name__}: {exc}"
            self._state = ERROR
        finally:
            self._reopen_reader()

    def _reopen_reader(self) -> None:
        with self._lock:
            if self._closed or not Path(self.config.db).exists():
                return
            try:
                new_reader = DocIndex(
                    self.config.db, wal=True, check_same_thread=False
                )
            except (sqlite3.Error, OSError):
                return  # keep the previous reader rather than a dead one
            if self._reader is not None:
                self._reader.close()
            self._reader = new_reader

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._reader is not None:
                self._reader.close()
                self._reader = None

    # -- status ------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    def info(self) -> dict:
        count = 0
        with self._lock:
            if self._reader is not None:
                count = self._reader.count()
        return {
            "state": self._state,
            "error": self._error,
            "count": count,
            "prefix": self.config.prefix,
        }

    # -- reads -------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[dict]:
        with self._lock:
            if self._reader is None:
                return []
            return self._reader.search(query, limit)

    def get(self, key: str) -> dict | None:
        with self._lock:
            if self._reader is None:
                return None
            if key.isdigit():
                return self._reader.get(int(key))
            return self._reader.get_by_title(key)

    def list_titles(self) -> list[tuple[int, str]]:
        with self._lock:
            if self._reader is None:
                return []
            return self._reader.list_titles()