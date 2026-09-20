"""HTML client for Valve Developer Community.

Only ``/wiki/<title>`` and the clean ``/wiki/Special:PrefixIndex/<prefix>``
path are requested (robots.txt compliant); the Anubis PoW handshake is handled
by :class:`~cs2wt.http.AnubisSession`.  Enumeration uses ``Special:PrefixIndex``
because the site has no sitemap.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
from dataclasses import dataclass

from .htmlparse import BASE_URL, extract_links, extract_meta, is_redirect, page_url
from .http import AnubisSession

FETCH_RETRIES = 3  # per-page attempts, including the first
FETCH_RETRY_DELAY = 2.0  # seconds between attempts


@dataclass(frozen=True)
class PageContent:
    title: str
    revid: int | None
    timestamp: str
    html: str
    is_redirect: bool = False


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

    def _get_html(self, url: str) -> str | None:
        """GET and decode ``url`` with the same transient retries as fetch_page.

        Returns ``None`` on HTTP 404; re-raises the last error if every attempt
        fails.
        """
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self.session.get(url).decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                error = exc
            except Exception as exc:  # noqa: BLE001 - retry transient failures
                error = exc
            if attempt + 1 < self.retries:
                time.sleep(self.retry_delay)
        assert error is not None
        raise error

    def fetch_page(self, title: str) -> PageContent | None:
        """Fetch and parse one page; return ``None`` if it does not exist.

        Transient failures (non-404 HTTP errors, network errors) are retried up
        to ``self.retries`` times with ``self.retry_delay`` seconds between
        attempts; the last error is re-raised if every attempt fails.
        """
        url = self.page_url(title)
        html = self._get_html(url)
        if html is None:
            return None
        meta = extract_meta(html)
        return PageContent(
            title=title,
            revid=meta["revid"],
            timestamp=meta["timestamp"],
            html=html,
            is_redirect=is_redirect(html),
        )

    def list_titles(self, prefix: str) -> list[str]:
        """Return every page title under ``prefix`` via ``Special:PrefixIndex``.

        The returned titles preserve the order in which the index links them
        and are de-duplicated.  Only titles that still start with ``prefix``
        (as spelled by the caller) are kept.
        """
        url = (
            f"{self.base_url}/wiki/Special:PrefixIndex/"
            + urllib.parse.quote(prefix.replace(" ", "_"), safe="/")
        )
        html = self._get_html(url)
        if html is None:
            # Never return an empty list on failure: callers would treat it as
            # "no pages exist" and delete every local page.
            raise RuntimeError(f"PrefixIndex request failed: {url}")
        titles: list[str] = []
        seen: set[str] = set()
        for title in extract_links(html):
            if title.startswith(prefix) and title not in seen:
                seen.add(title)
                titles.append(title)
        return titles

    def iter_pages(self, prefix: str, seeds=(), known=None, failed=None):
        """Yield pages under ``prefix`` enumerated from ``Special:PrefixIndex``.

        ``seeds`` (e.g. titles from an existing manifest) are visited first so a
        migration cannot drop already-known pages.  ``known`` is an optional
        title->PageContent cache that is read and populated, so callers can
        avoid re-fetching pages they already have.  ``failed`` is an optional
        list that collects titles whose fetch raised; a transient failure is
        skipped so it cannot abort the whole traversal.  Missing (404) and
        redirect pages are skipped.
        """
        known = {} if known is None else known
        candidates: list[str] = []
        seen: set[str] = set()
        for title in [*seeds, *self.list_titles(prefix)]:
            if title not in seen:
                seen.add(title)
                candidates.append(title)
        for title in candidates:
            page = known.get(title)
            if page is None:
                try:
                    page = self.fetch_page(title)
                except Exception:  # noqa: BLE001 - tolerate per-page failures
                    if failed is not None:
                        failed.append(title)
                    continue
                if page is None or page.is_redirect:
                    continue
                known[title] = page
            if page.is_redirect:
                continue
            yield page