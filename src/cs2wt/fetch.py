"""Crawl the documentation tree as raw HTML.

Raw HTML is the source of truth: it is stored untouched so the Markdown /
index layers can always be rebuilt, and so incremental syncs can diff by
revision id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import store
from .wiki import HtmlClient


def crawl(
    client: HtmlClient,
    *,
    prefix: str,
    out_dir: str | Path,
) -> dict:
    """Fetch every reachable page under ``prefix`` and write raw HTML + manifest."""
    out_dir = Path(out_dir)
    store.raw_dir(out_dir).mkdir(parents=True, exist_ok=True)
    prior = store.manifest_by_title(store.load_manifest(out_dir))
    seeds = list(prior)

    records: list[dict] = []
    seen: set[str] = set()
    failed: list[str] = []
    for page in client.iter_pages(prefix, seeds=seeds, failed=failed):
        store.raw_path(out_dir, page.title).write_text(page.html, encoding="utf-8")
        records.append(
            {
                "title": page.title,
                "revid": page.revid,
                "timestamp": page.timestamp,
                "file": f"raw/{store.slug(page.title)}.html",
            }
        )
        seen.add(page.title)
        print(f"  fetched {page.title} (rev {page.revid})")

    # Keep the previous manifest record for pages that still failed after the
    # client's per-page retries, so a transient failure never drops a page.
    for title in dict.fromkeys(failed):
        if title not in seen and title in prior:
            records.append(prior[title])

    if failed:
        print(f"  failed {len(failed)} page(s) after retries: {', '.join(failed)}")

    manifest = {
        "source": client.base_url,
        "prefix": prefix,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": records,
    }
    store.save_manifest(out_dir, manifest)
    return manifest