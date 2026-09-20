"""Crawl a documentation tree from the wiki and persist raw wikitext.

Raw wikitext is the source of truth: it is stored untouched so the markdown /
index layers can always be rebuilt, and so incremental syncs can diff by
revision id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import store
from .wiki import WikiClient

BATCH_SIZE = 20  # anonymous API limit is 50 titles/request; stay conservative


def crawl(
    client: WikiClient,
    *,
    prefix: str,
    out_dir: str | Path,
) -> dict:
    """Fetch every page under ``prefix`` and write raw wikitext + a manifest."""
    out_dir = Path(out_dir)
    store.raw_dir(out_dir).mkdir(parents=True, exist_ok=True)

    discovered = list(client.iter_all_pages(prefix))
    records: list[dict] = []

    for batch in store.chunks([p["title"] for p in discovered], BATCH_SIZE):
        for page in client.fetch_pages(batch):
            store.raw_path(out_dir, page.pageid).write_text(
                page.content, encoding="utf-8"
            )
            records.append(
                {
                    "pageid": page.pageid,
                    "title": page.title,
                    "revid": page.revid,
                    "timestamp": page.timestamp,
                    "file": f"raw/{page.pageid}.wiki",
                }
            )
            print(f"  fetched {page.title} (rev {page.revid})")

    manifest = {
        "source": client.api_url,
        "prefix": prefix,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": records,
    }
    store.save_manifest(out_dir, manifest)
    return manifest