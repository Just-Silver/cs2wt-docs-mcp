"""Persistence helpers: raw wikitext files and the crawl manifest."""

from __future__ import annotations

import json
from pathlib import Path


def chunks(items: list, size: int):
    """Yield successive ``size``-length slices of ``items``."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def raw_dir(data_dir) -> Path:
    return Path(data_dir) / "raw"


def raw_path(data_dir, pageid: int) -> Path:
    return raw_dir(data_dir) / f"{pageid}.wiki"


def manifest_path(data_dir) -> Path:
    return Path(data_dir) / "manifest.json"


def load_manifest(data_dir) -> dict:
    path = manifest_path(data_dir)
    if not path.exists():
        return {"pages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_by_pageid(manifest: dict) -> dict[int, dict]:
    return {record["pageid"]: record for record in manifest.get("pages", [])}


def save_manifest(data_dir, manifest: dict) -> None:
    manifest["pages"] = sorted(
        manifest.get("pages", []), key=lambda record: record["title"]
    )
    manifest["page_count"] = len(manifest["pages"])
    manifest_path(data_dir).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )