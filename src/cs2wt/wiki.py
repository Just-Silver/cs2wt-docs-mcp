"""Thin MediaWiki Action API client.

Uses ``format=json&formatversion=2`` for clean JSON and transparently follows
API continuation.  Only the handful of endpoints this project needs are
implemented.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass

from .http import AnubisSession

DEFAULT_API = "https://developer.valvesoftware.com/w/api.php"


@dataclass(frozen=True)
class PageContent:
    pageid: int
    title: str
    revid: int
    timestamp: str
    content: str


class WikiClient:
    def __init__(self, session: AnubisSession, api_url: str = DEFAULT_API) -> None:
        self.session = session
        self.api_url = api_url

    # -- low level ---------------------------------------------------------

    def _call(self, params: dict) -> dict:
        query = {"format": "json", "formatversion": 2, **params}
        url = f"{self.api_url}?{urllib.parse.urlencode(query)}"
        data = json.loads(self.session.get(url).decode("utf-8"))
        if "error" in data:
            raise RuntimeError(f"MediaWiki API error: {data['error']}")
        return data

    # -- high level --------------------------------------------------------

    def iter_all_pages(self, prefix: str, namespace: int = 0):
        """Yield ``{"pageid", "title"}`` for every page with ``prefix``."""
        cont: dict = {}
        while True:
            data = self._call(
                {
                    "action": "query",
                    "list": "allpages",
                    "apnamespace": namespace,
                    "apprefix": prefix,
                    "aplimit": "max",
                    **cont,
                }
            )
            yield from data["query"]["allpages"]
            if "continue" in data:
                cont = data["continue"]
            else:
                break

    def iter_pages_with_revisions(self, prefix: str, namespace: int = 0):
        """Yield page metadata + current revision for every page under ``prefix``.

        A single ``generator=allpages`` + ``prop=revisions`` pass, so added,
        removed and moved pages are all discovered in one traversal.
        """
        cont: dict = {}
        while True:
            data = self._call(
                {
                    "action": "query",
                    "generator": "allpages",
                    "gaplimit": "max",
                    "gapnamespace": namespace,
                    "gapprefix": prefix,
                    "prop": "revisions",
                    "rvprop": "ids|timestamp",
                    **cont,
                }
            )
            for page in data.get("query", {}).get("pages", []):
                revision = page["revisions"][0]
                yield {
                    "pageid": page["pageid"],
                    "title": page["title"],
                    "revid": revision["revid"],
                    "timestamp": revision["timestamp"],
                }
            if "continue" in data:
                cont = data["continue"]
            else:
                break

    def fetch_pages(self, titles: list[str]) -> list[PageContent]:
        """Fetch wikitext + revision metadata for a batch of titles."""
        data = self._call(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "titles": "|".join(titles),
            }
        )
        pages: list[PageContent] = []
        for page in data["query"]["pages"]:
            if page.get("missing"):
                continue
            revision = page["revisions"][0]
            pages.append(
                PageContent(
                    pageid=page["pageid"],
                    title=page["title"],
                    revid=revision["revid"],
                    timestamp=revision["timestamp"],
                    content=revision["slots"]["main"]["content"],
                )
            )
        return pages

    def siteinfo(self) -> dict:
        data = self._call({"action": "query", "meta": "siteinfo"})
        return data["query"]["general"]