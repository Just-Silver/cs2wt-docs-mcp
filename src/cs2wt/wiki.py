"""HTML client for Valve Developer Community.

Only ``/wiki/<title>`` is requested (robots.txt compliant); the Anubis PoW
handshake is handled by :class:`~cs2wt.http.AnubisSession`.  Enumeration is a
link BFS because the site has no sitemap.
"""

from __future__ import annotations

import time
import urllib.error
from dataclasses import dataclass

from .htmlparse import BASE_URL, extract_links, extract_meta, page_url
from .http import AnubisSession

FETCH_RETRIES = 3  # per-page attempts, including the first
FETCH_RETRY_DELAY = 2.0  # seconds between attempts


@dataclass(frozen=True)
class PageContent:
    title: str
    revid: int | None
    timestamp: str
    html: str


class HtmlClient:
    def __init__(
        self,
        session: AnubisSession,
        base_url: str = BASE_URL,
        *,
        retries: int = FETCH_RETRIES,
        retry_delay: float = FETCH_RETRY_DELAY,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.retries = max(1, retries)
        self.retry_delay = retry_delay

    def page_url(self, title: str) -> str:
        return page_url(title, self.base_url)

    def fetch_page(self, title: str) -> PageContent | None:
        """Fetch and parse one page; return ``None`` if it does not exist.

        Transient failures (non-404 HTTP errors, network errors) are retried up
        to ``self.retries`` times with ``self.retry_delay`` seconds between
        attempts; the last error is re-raised if every attempt fails.
        """
        url = self.page_url(title)
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                html = self.session.get(url).decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                error = exc
            except Exception as exc:  # noqa: BLE001 - retry transient failures
                error = exc
            if attempt + 1 < self.retries:
                time.sleep(self.retry_delay)
        else:
            assert error is not None
            raise error
        meta = extract_meta(html)
        return PageContent(
            title=meta["title"] or title,
            revid=meta["revid"],
            timestamp=meta["timestamp"],
            html=html,
        )

    def iter_pages(self, prefix: str, seeds=(), known=None, failed=None):
        """BFS over ``/wiki/`` links, yielding pages whose title has ``prefix``.

        ``seeds`` (e.g. titles from an existing manifest) are visited first so a
        migration cannot drop already-known pages.  ``known`` is an optional
        title->PageContent cache that is read and populated, so callers can
        avoid re-fetching pages they already have.  ``failed`` is an optional
        list that collects titles whose fetch raised; a transient failure is
        skipped so it cannot abort the whole traversal.
        """
        known = {} if known is None else known
        queue = [prefix, *seeds]
        visited: set[str] = set()
        while queue:
            title = queue.pop(0)
            if title in visited:
                continue
            visited.add(title)
            page = known.get(title)
            if page is None:
                try:
                    page = self.fetch_page(title)
                except Exception:  # noqa: BLE001 - tolerate per-page failures
                    if failed is not None:
                        failed.append(title)
                    continue
                if page is None:
                    continue
                known[title] = page
            yield page
            for link in extract_links(page.html):
                if link.startswith(prefix) and link not in visited:
                    queue.append(link)