"""Download a prebuilt index from GitHub Releases.

The MCP server consumes published data artifacts instead of scraping VDC
itself: it fetches the small ``manifest.json`` to compare ``generated_at``
against the local index and, only when the remote copy is newer, streams
``docs.sqlite`` to a staged ``.tmp`` path.  The caller is responsible for
swapping the staged file into place (closing any open reader first).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPO = "Just-Silver/cs2wt-docs-mcp"
RELEASE_TAG = "data-latest"
HTTP_TIMEOUT = 30.0

_CHUNK_SIZE = 64 * 1024


def asset_url(repo: str, tag: str, name: str) -> str:
    """Build the fixed GitHub Release asset URL."""
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def update_from_release(config, has_index: bool) -> Path | None:
    """Stage a newer index from GitHub Releases, or return ``None``.

    ``config`` is duck-typed and must expose ``data_dir``, ``db``,
    ``release_repo``, ``release_tag`` and ``check_interval``.  The returned
    path (``<db>.tmp``) is only staged; the caller performs the atomic swap.

    When ``has_index`` is true, network/parse errors are non-fatal (a warning
    is printed and ``None`` is returned); otherwise errors propagate.
    """
    data_dir = Path(config.data_dir)
    db = Path(config.db)

    # Throttle: skip entirely when a recent successful check is on record.
    # A missing local index ignores the throttle so the first run always runs.
    if has_index and _within_interval(data_dir, config.check_interval):
        return None

    try:
        remote = _fetch_manifest(config)
        if not isinstance(remote, dict):
            remote = {}
        remote_at = _parse_time(remote.get("generated_at"))
        local_at = _parse_time(_local_generated_at(config))

        if (
            has_index
            and remote_at is not None
            and local_at is not None
            and remote_at <= local_at
        ):
            _write_last_check(data_dir)
            return None

        staged = db.with_name(db.name + ".tmp")
        _download(
            asset_url(config.release_repo, config.release_tag, "docs.sqlite"),
            staged,
        )
        _write_manifest(data_dir, remote)
        _write_last_check(data_dir)
        return staged
    except (OSError, ValueError) as exc:
        # OSError covers urllib errors; ValueError covers json.JSONDecodeError.
        if has_index:
            print(f"cs2wt: update from release failed: {exc}", file=sys.stderr)
            return None
        raise


def _fetch_manifest(config) -> dict:
    url = asset_url(config.release_repo, config.release_tag, "manifest.json")
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
        with open(dest, "wb") as handle:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local_generated_at(config) -> str | None:
    """Local version marker: index ``meta`` first, then local manifest."""
    from_db = _db_generated_at(Path(config.db))
    if from_db:
        return from_db
    manifest = Path(config.data_dir) / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("generated_at")


def _db_generated_at(db: Path) -> str | None:
    if not db.exists():
        return None
    try:
        uri = db.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, OSError, ValueError):
        return None
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'generated_at'"
        ).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _within_interval(data_dir: Path, interval: float) -> bool:
    checked = _read_last_check(data_dir)
    if checked is None:
        return False
    return (datetime.now(timezone.utc) - checked).total_seconds() < interval


def _read_last_check(data_dir: Path) -> datetime | None:
    path = Path(data_dir) / "last_check.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _parse_time(data.get("checked_at"))


def _write_last_check(data_dir: Path) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"checked_at": datetime.now(timezone.utc).isoformat()})
    _atomic_write(data_dir / "last_check.json", payload)


def _write_manifest(data_dir: Path, manifest: dict) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, ensure_ascii=False)
    _atomic_write(data_dir / "manifest.json", payload)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)