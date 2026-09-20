"""Incremental sync between the local mirror and the wiki.

Change detection is a full ``revid`` comparison driven by a single
``generator=allpages`` + ``prop=revisions`` pass: no timestamp cursor to
maintain, and added / removed / moved pages are all discovered naturally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .convert import wikitext_to_markdown
from .index import DocIndex, page_url

BATCH_SIZE = 20


@dataclass
class SyncReport:
    added: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added  "
            f"~{len(self.updated)} updated  "
            f"-{len(self.removed)} removed  "
            f"={len(self.unchanged)} unchanged"
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
    local = store.manifest_by_pageid(manifest)

    remote = {p["pageid"]: p for p in client.iter_pages_with_revisions(prefix)}

    report = SyncReport()
    report.added = [pid for pid in remote if pid not in local]
    report.removed = [pid for pid in local if pid not in remote]
    for pid, remote_page in remote.items():
        record = local.get(pid)
        if record is None:
            continue
        if remote_page["revid"] != record["revid"] or remote_page["title"] != record["title"]:
            report.updated.append(pid)
        else:
            report.unchanged.append(pid)

    if dry_run:
        return report

    to_fetch = sorted(report.added + report.updated)
    titles = [remote[pid]["title"] for pid in to_fetch]
    records = store.manifest_by_pageid(manifest)

    store.raw_dir(data_dir).mkdir(parents=True, exist_ok=True)

    index = DocIndex(db_path)
    try:
        for batch in store.chunks(titles, BATCH_SIZE):
            for page in client.fetch_pages(batch):
                store.raw_path(data_dir, page.pageid).write_text(
                    page.content, encoding="utf-8"
                )
                records[page.pageid] = {
                    "pageid": page.pageid,
                    "title": page.title,
                    "revid": page.revid,
                    "timestamp": page.timestamp,
                    "file": f"raw/{page.pageid}.wiki",
                }
                index.upsert(
                    pageid=page.pageid,
                    title=page.title,
                    content=wikitext_to_markdown(page.content),
                    revid=page.revid,
                    timestamp=page.timestamp,
                    url=page_url(page.title),
                )

        for pid in report.removed:
            records.pop(pid, None)
            index.delete(pid)

        source = getattr(client, "api_url", "") or manifest.get("source", "")
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