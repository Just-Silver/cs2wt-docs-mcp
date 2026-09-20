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


_DROP_TAGS = {"script", "style"}
_DROP_IDS = {"toc"}
_DROP_CLASSES = {
    "mw-editsection", "navbox", "metadata", "mw-empty-elt", "noprint", "reference",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_VOID = {
    "br", "img", "hr", "meta", "link", "input", "wbr", "area", "base",
    "col", "embed", "param", "track",
}
_CODE_BLOCKS = {"pre", "syntaxhighlight", "source"}


def _absolute(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    return href


def _balanced(html: str, open_index: int) -> str:
    match = re.match(r"<\s*([a-zA-Z0-9]+)", html[open_index:])
    if not match:
        return html[open_index:]
    tag = match.group(1).lower()
    pattern = re.compile(rf"</?{tag}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for token in pattern.finditer(html, open_index):
        text = token.group(0)
        if text.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[open_index:token.end()]
        else:
            depth += 1
    return html[open_index:]


def _extract_container(html: str) -> str:
    for marker in ('id="mw-content-text"', "class='mw-parser-output'", 'class="mw-parser-output"'):
        index = html.find(marker)
        if index != -1:
            return _balanced(html, html.rfind("<", 0, index))
    body = html.find("<body")
    if body != -1:
        return _balanced(html, body)
    return html


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buf: list[str] = []
        self.drop_depth = 0
        self.lists: list[list] = []
        self.links: list[str] = []
        self.pre = 0
        self.code = 0

    # -- helpers -----------------------------------------------------------
    def _tail(self) -> str:
        return self.buf[-1][-1] if self.buf and self.buf[-1] else ""

    def _write(self, text: str) -> None:
        if text:
            self.buf.append(text)

    def _blank(self) -> None:
        if self.buf:
            self.buf.append("\n\n")

    def _line(self) -> None:
        if self.buf and self._tail() != "\n":
            self.buf.append("\n")

    # -- callbacks ---------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = {key: (value or "") for key, value in attrs}
        if self.drop_depth:
            if tag not in _VOID:
                self.drop_depth += 1
            return
        if tag in _DROP_TAGS or tag == "table":
            self.drop_depth = 1
            return
        if attrs.get("id") in _DROP_IDS:
            self.drop_depth = 1
            return
        if set(attrs.get("class", "").split()) & _DROP_CLASSES:
            self.drop_depth = 1
            return

        if tag in _HEADINGS:
            self._blank()
            self._write("#" * int(tag[1]) + " ")
        elif tag == "p":
            self._blank()
        elif tag == "br":
            self._write("\n")
        elif tag in ("ul", "ol"):
            self._blank()
            self.lists.append([tag == "ol", 0])
        elif tag == "li":
            self._line()
            if self.lists:
                self.lists[-1][1] += 1
                ordered = self.lists[-1][0]
                indent = "  " * (len(self.lists) - 1)
                marker = f"{self.lists[-1][1]}. " if ordered else "- "
                self._write(indent + marker)
        elif tag in _CODE_BLOCKS:
            self._blank()
            self._write("```\n")
            self.pre += 1
        elif tag == "code":
            if not self.pre:
                self._write("`")
                self.code += 1
        elif tag in ("b", "strong"):
            self._write("**")
        elif tag in ("i", "em"):
            self._write("*")
        elif tag == "a":
            href = attrs.get("href", "")
            self.links.append(href)
            if href:
                self._write("[")

    def handle_endtag(self, tag):
        if self.drop_depth:
            self.drop_depth -= 1
            return
        if tag in _HEADINGS or tag == "p":
            self._write("\n")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._write("\n")
        elif tag == "li":
            self._write("\n")
        elif tag in _CODE_BLOCKS:
            self._write("\n```\n")
            self.pre = max(0, self.pre - 1)
        elif tag == "code":
            if self.code:
                self._write("`")
                self.code -= 1
        elif tag in ("b", "strong"):
            self._write("**")
        elif tag in ("i", "em"):
            self._write("*")
        elif tag == "a":
            href = self.links.pop() if self.links else ""
            if href:
                url = _absolute(href)
                self._write(f"]({url})" if url else "]")

    def handle_data(self, data):
        if not self.drop_depth:
            self._write(data)


def html_to_markdown(html: str) -> str:
    """Convert rendered MediaWiki HTML to readable Markdown."""
    parser = _MarkdownParser()
    parser.feed(_extract_container(html))
    parser.close()
    text = "".join(parser.buf)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()