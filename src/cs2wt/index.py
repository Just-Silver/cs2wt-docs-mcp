"""SQLite FTS5 full-text index for the documentation.

Everything lives in a single portable ``.sqlite`` file so it can be shipped
with the docs.  The page ``title`` is the logical key; the FTS ``rowid`` is
reused across updates, which makes per-page update/delete trivial (the basis
for incremental sync).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .htmlparse import html_to_markdown, page_url
from .store import raw_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    title,
    content,
    revid     UNINDEXED,
    timestamp UNINDEXED,
    url       UNINDEXED,
    tokenize = 'unicode61'
);
"""


def _fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 AND query."""
    tokens = re.findall(r"\w+", query, re.UNICODE)
    if not tokens:
        return '""'
    return " ".join(f'"{t}"' for t in tokens)


class DocIndex:
    def __init__(
        self,
        path: str | Path,
        *,
        wal: bool = False,
        check_same_thread: bool = True,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        if wal:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)

    # -- writes ------------------------------------------------------------

    def upsert(self, *, title, content, revid, timestamp, url) -> None:
        row = self.conn.execute(
            "SELECT rowid FROM docs WHERE title = ?", (title,)
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO docs(title, content, revid, timestamp, url) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, content, revid, timestamp, url),
            )
        else:
            rowid = row[0]
            self.conn.execute("DELETE FROM docs WHERE rowid = ?", (rowid,))
            self.conn.execute(
                "INSERT INTO docs(rowid, title, content, revid, timestamp, url) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rowid, title, content, revid, timestamp, url),
            )

    def delete(self, title: str) -> None:
        self.conn.execute("DELETE FROM docs WHERE title = ?", (title,))

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    # -- reads -------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT title, url, "
            "snippet(docs, 1, '[', ']', '…', 12) AS snippet, "
            "bm25(docs) AS score "
            "FROM docs WHERE docs MATCH ? ORDER BY score LIMIT ?",
            (_fts_query(query), limit),
        ).fetchall()
        return [
            {"title": r[0], "url": r[1], "snippet": r[2], "score": r[3]}
            for r in rows
        ]

    def get(self, key) -> dict | None:
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            where, params = "rowid = ?", (int(key),)
        else:
            where, params = "title = ?", (key,)
        row = self.conn.execute(
            "SELECT title, revid, timestamp, url, content FROM docs WHERE " + where,
            params,
        ).fetchone()
        if not row:
            return None
        keys = ("title", "revid", "timestamp", "url", "content")
        return dict(zip(keys, row))

    def get_by_title(self, title: str) -> dict | None:
        return self.get(title)

    def list_titles(self) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute("SELECT title FROM docs ORDER BY title")
        ]

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM docs").fetchone()[0]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def build_index(data_dir: str | Path, db_path: str | Path) -> DocIndex:
    """Build (or rebuild) an index from a crawl directory."""
    data_dir = Path(data_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))

    index = DocIndex(db_path)
    for record in manifest["pages"]:
        raw = raw_path(data_dir, record["title"]).read_text(encoding="utf-8")
        index.upsert(
            title=record["title"],
            content=html_to_markdown(raw),
            revid=record["revid"],
            timestamp=record["timestamp"],
            url=page_url(record["title"]),
        )
    index.set_meta("generated_at", manifest["generated_at"])
    index.set_meta("prefix", manifest["prefix"])
    index.set_meta("source", manifest["source"])
    index.set_meta("page_count", str(manifest["page_count"]))
    index.commit()
    return index