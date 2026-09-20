"""Persistence helpers: raw HTML files and the crawl manifest."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path


def chunks(items: list, size: int):
    """Yield successive ``size``-length slices of ``items``."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def raw_dir(data_dir) -> Path:
    return Path(data_dir) / "raw"


def slug(title: str) -> str:
    """Filesystem-safe, reversible filename for a page title."""
    return urllib.parse.quote(title, safe="")


def raw_path(data_dir, title: str) -> Path:
    return raw_dir(data_dir) / f"{slug(title)}.html"


def manifest_path(data_dir) -> Path:
    return Path(data_dir) / "manifest.json"


def load_manifest(data_dir) -> dict:
    path = manifest_path(data_dir)
    if not path.exists():
        return {"pages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_by_title(manifest: dict) -> dict[str, dict]:
    return {record["title"]: record for record in manifest.get("pages", [])}


def save_manifest(data_dir, manifest: dict) -> None:
    manifest["pages"] = sorted(
        manifest.get("pages", []), key=lambda record: record["title"]
    )
    manifest["page_count"] = len(manifest["pages"])
    manifest_path(data_dir).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )