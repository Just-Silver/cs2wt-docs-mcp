"""Incremental sync between the local mirror and the wiki.

Change detection compares the revision id parsed from each page's HTML.  A
page's own 404 is the only signal for removal; link enumeration is used only to
discover new pages, so an incomplete crawl can never cause a false deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .htmlparse import html_to_markdown, page_url
from .index import DocIndex


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added  "
            f"~{len(self.updated)} updated  "
            f"-{len(self.removed)} removed  "
            f"={len(self.unchanged)} unchanged  "
            f"!{len(self.failed)} failed"
        )


def sync(
    client,
    *,
    prefix: str,
    data_dir: str | Path,
    db_path: str | Path,
    dry_run: bool = False,
) -> SyncReport:
    """Bring the local mirror in line with the wiki under ``prefix``."""
    data_dir = Path(data_dir)
    manifest = store.load_manifest(data_dir)
    local = store.manifest_by_title(manifest)

    report = SyncReport()
    cache: dict = {}

    # 1. Existing pages: fetch each; a 404 removes it, otherwise compare revid.
    for title in local:
        try:
            page = client.fetch_page(title)
        except Exception:  # noqa: BLE001 - keep the record, never delete on error
            report.failed.append(title)
            continue
        if page is None:
            report.removed.append(title)
            continue
        cache[title] = page
        if page.title != title:
            # The page was moved: the old key is stale and the new title is a
            # fresh page (discovered as "added" in the BFS below).
            report.removed.append(title)
        elif page.revid != local[title]["revid"]:
            report.updated.append(title)
        else:
            report.unchanged.append(title)

    # 2. New pages: BFS from the root to discover titles outside the manifest
    #    (reusing the cache so already-fetched pages are not requested twice).
    for page in client.iter_pages(prefix, seeds=list(local), known=cache, failed=report.failed):
        if page.title not in local:
            report.added.append(page.title)

    if dry_run:
        return report

    records = dict(local)
    store.raw_dir(data_dir).mkdir(parents=True, exist_ok=True)
    index = DocIndex(db_path)
    try:
        for title in sorted(set(report.added) | set(report.updated)):
            page = cache.get(title) or client.fetch_page(title)
            if page is None:
                continue
            store.raw_path(data_dir, page.title).write_text(page.html, encoding="utf-8")
            records[page.title] = {
                "title": page.title,
                "revid": page.revid,
                "timestamp": page.timestamp,
                "file": f"raw/{store.slug(page.title)}.html",
            }
            index.upsert(
                title=page.title,
                content=html_to_markdown(page.html),
                revid=page.revid,
                timestamp=page.timestamp,
                url=page_url(page.title, client.base_url),
            )

        for title in report.removed:
            records.pop(title, None)
            index.delete(title)

        # Self-heal: re-index any unchanged page missing from the index (e.g.
        # the index was absent or only partially built).
        indexed = set(index.list_titles())
        for title in report.unchanged:
            if title in indexed:
                continue
            page = cache.get(title)
            if page is None:
                continue
            index.upsert(
                title=title,
                content=html_to_markdown(page.html),
                revid=page.revid,
                timestamp=page.timestamp,
                url=page_url(title, client.base_url),
            )

        source = getattr(client, "base_url", "") or manifest.get("source", "")
        manifest["pages"] = list(records.values())
        manifest["source"] = source
        manifest["prefix"] = prefix
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
        store.save_manifest(data_dir, manifest)

        index.set_meta("prefix", prefix)
        index.set_meta("source", source)
        index.set_meta("generated_at", manifest["generated_at"])
        index.set_meta("page_count", str(manifest["page_count"]))
        index.commit()
    finally:
        index.close()

    return report