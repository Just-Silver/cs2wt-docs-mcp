"""SQLite FTS5 full-text index for the documentation.

Everything lives in a single portable ``.sqlite`` file so it can be shipped
with the docs.  ``pageid`` is used as the FTS ``rowid``, which makes per-page
update/delete trivial (the basis for incremental sync).
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
from pathlib import Path

from .convert import wikitext_to_markdown

WIKI_BASE = "https://developer.valvesoftware.com/wiki/"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    title,
    content,
    pageid    UNINDEXED,
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


def page_url(title: str) -> str:
    return WIKI_BASE + urllib.parse.quote(title.replace(" ", "_"), safe="/")


class DocIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(_SCHEMA)

    # -- writes ------------------------------------------------------------

    def upsert(
        self,
        *,
        pageid: int,
        title: str,
        content: str,
        revid: int,
        timestamp: str,
        url: str,
    ) -> None:
        self.conn.execute("DELETE FROM docs WHERE rowid = ?", (pageid,))
        self.conn.execute(
            "INSERT INTO docs(rowid, title, content, pageid, revid, timestamp, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pageid, title, content, pageid, revid, timestamp, url),
        )

    def delete(self, pageid: int) -> None:
        self.conn.execute("DELETE FROM docs WHERE rowid = ?", (pageid,))

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
            "SELECT pageid, title, url, "
            "snippet(docs, 1, '[', ']', '…', 12) AS snippet, "
            "bm25(docs) AS score "
            "FROM docs WHERE docs MATCH ? ORDER BY score LIMIT ?",
            (_fts_query(query), limit),
        ).fetchall()
        return [
            {"pageid": r[0], "title": r[1], "url": r[2], "snippet": r[3], "score": r[4]}
            for r in rows
        ]

    def get(self, pageid: int) -> dict | None:
        row = self.conn.execute(
            "SELECT pageid, title, revid, timestamp, url, content "
            "FROM docs WHERE rowid = ?",
            (pageid,),
        ).fetchone()
        if not row:
            return None
        keys = ("pageid", "title", "revid", "timestamp", "url", "content")
        return dict(zip(keys, row))

    def get_by_title(self, title: str) -> dict | None:
        row = self.conn.execute(
            "SELECT rowid FROM docs WHERE title = ?", (title,)
        ).fetchone()
        return self.get(row[0]) if row else None

    def list_titles(self) -> list[tuple[int, str]]:
        return self.conn.execute(
            "SELECT pageid, title FROM docs ORDER BY title"
        ).fetchall()

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
        raw = (data_dir / record["file"]).read_text(encoding="utf-8")
        index.upsert(
            pageid=record["pageid"],
            title=record["title"],
            content=wikitext_to_markdown(raw),
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