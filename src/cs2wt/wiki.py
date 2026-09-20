"""HTML client for Valve Developer Community.

Only ``/wiki/<title>`` is requested (robots.txt compliant); the Anubis PoW
handshake is handled by :class:`~cs2wt.http.AnubisSession`.  Enumeration is a
link BFS because the site has no sitemap.
"""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass

from .htmlparse import BASE_URL, extract_links, extract_meta, page_url
from .http import AnubisSession


@dataclass(frozen=True)
class PageContent:
    title: str
    revid: int | None
    timestamp: str
    html: str


class HtmlClient:
    def __init__(self, session: AnubisSession, base_url: str = BASE_URL) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")

    def page_url(self, title: str) -> str:
        return page_url(title, self.base_url)

    def fetch_page(self, title: str) -> PageContent | None:
        """Fetch and parse one page; return ``None`` if it does not exist."""
        url = self.page_url(title)
        try:
            html = self.session.get(url).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        meta = extract_meta(html)
        return PageContent(
            title=meta["title"] or title,
            revid=meta["revid"],
            timestamp=meta["timestamp"],
            html=html,
        )

    def iter_pages(self, prefix: str, seeds=(), known=None):
        """BFS over ``/wiki/`` links, yielding pages whose title has ``prefix``.

        ``seeds`` (e.g. titles from an existing manifest) are visited first so a
        migration cannot drop already-known pages.  ``known`` is an optional
        title->PageContent cache that is read and populated, so callers can
        avoid re-fetching pages they already have.
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
                page = self.fetch_page(title)
                if page is None:
                    continue
                known[title] = page
            yield page
            for link in extract_links(page.html):
                if link.startswith(prefix) and link not in visited:
                    queue.append(link)