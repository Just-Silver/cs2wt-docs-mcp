"""Dependency-free HTML parsing for the VDC mirror.

Only the standard library is used: :mod:`html.parser` for the DOM walk and
:mod:`urllib.parse` for URL handling.  The raw HTML is always kept, so these
functions can be improved and re-run at any time.
"""

from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser

BASE_URL = "https://developer.valvesoftware.com"

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ),
        start=1,
    )
}
_LAST_MODIFIED = re.compile(
    r"This page was last modified on\s+(\d+)\s+([A-Za-z]+)\s+(\d+),\s+at\s+(\d+):(\d+)"
)
_OLDID = re.compile(r"[?&]oldid=(\d+)")


def page_url(title: str, base: str = BASE_URL) -> str:
    return f"{base.rstrip('/')}/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="/")


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.revid: int | None = None
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h1" and attrs.get("id") == "firstHeading":
            self._in_h1 = True
        if tag == "a" and self.revid is None:
            match = _OLDID.search(attrs.get("href") or "")
            if match:
                self.revid = int(match.group(1))

    def handle_endtag(self, tag):
        if tag == "h1" and self._in_h1:
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_h1:
            self.title_parts.append(data)
        self.text_parts.append(data)


def extract_meta(html: str) -> dict:
    """Return ``{"title", "revid", "timestamp"}`` parsed from a rendered page."""
    parser = _MetaParser()
    parser.feed(html)
    parser.close()

    title = " ".join("".join(parser.title_parts).split())
    timestamp = ""
    match = _LAST_MODIFIED.search("".join(parser.text_parts))
    if match:
        day, month, year, hour, minute = match.groups()
        month_num = _MONTHS.get(month, 0)
        if month_num:
            timestamp = (
                f"{int(year):04d}-{month_num:02d}-{int(day):02d}"
                f"T{int(hour):02d}:{int(minute):02d}:00"
            )
    return {"title": title, "revid": parser.revid, "timestamp": timestamp}


_NON_ARTICLE_NS = {
    "special", "file", "image", "category", "template", "help", "talk",
    "user", "mediawiki", "module", "draft", "valve developer community",
}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def extract_links(html: str) -> list[str]:
    """Return normalized, de-duplicated article titles linked from ``html``."""
    parser = _LinkParser()
    parser.feed(html)
    parser.close()

    titles: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        parts = urllib.parse.urlsplit(href)
        if parts.scheme or parts.netloc:  # external / protocol-relative
            continue
        if not parts.path.startswith("/wiki/"):
            continue
        title = urllib.parse.unquote(parts.path[len("/wiki/"):])
        title = title.replace("_", " ").strip()
        if not title or title in seen:
            continue
        namespace = title.split(":", 1)[0].lower()
        if ":" in title and namespace in _NON_ARTICLE_NS:
            continue
        seen.add(title)
        titles.append(title)
    return titles