"""Convert MediaWiki wikitext to readable Markdown.

A deliberately small, dependency-free converter -- enough to make the docs
searchable and human-readable.  It is *not* a full wikitext parser; the raw
wikitext is always kept so this can be improved and re-run at any time.
"""

from __future__ import annotations

import re

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CODE_BLOCK = re.compile(
    r"<(?:syntaxhighlight|source|pre)(?:\s[^>]*)?>(.*?)</(?:syntaxhighlight|source|pre)>",
    re.DOTALL | re.IGNORECASE,
)
_TABLE = re.compile(r"\{\|.*?\|\}", re.DOTALL)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_FILE_LINK = re.compile(r"\[\[(?:File|Image|Category):[^\]]*\]\]", re.IGNORECASE)
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_EXT_LINK = re.compile(r"\[(https?://\S+)\s+([^\]]+)\]")
_EXT_LINK_BARE = re.compile(r"\[(https?://\S+)\]")
_HEADING = re.compile(r"^(={1,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_LIST = re.compile(r"^([*#]+)\s*", re.MULTILINE)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BOLD = re.compile(r"'''(.*?)'''", re.DOTALL)
_ITALIC = re.compile(r"''(.*?)''", re.DOTALL)
_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_templates(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _TEMPLATE.sub("", text)
    return text


def _list_item(match: re.Match) -> str:
    marks = match.group(1)
    indent = "  " * (len(marks) - 1)
    bullet = "1." if marks[-1] == "#" else "-"
    return f"{indent}{bullet} "


def wikitext_to_markdown(text: str) -> str:
    """Best-effort wikitext -> Markdown conversion."""
    text = _COMMENT.sub("", text)
    text = _CODE_BLOCK.sub(
        lambda m: "\n```\n" + m.group(1).strip() + "\n```\n", text
    )
    text = _TABLE.sub("", text)
    text = _strip_templates(text)
    text = _FILE_LINK.sub("", text)
    text = _WIKI_LINK.sub(
        lambda m: m.group(2) or m.group(1).replace("_", " "), text
    )
    text = _EXT_LINK.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", text)
    text = _EXT_LINK_BARE.sub(lambda m: m.group(1), text)
    text = _BOLD.sub(r"**\1**", text)
    text = _ITALIC.sub(r"*\1*", text)
    text = _HEADING.sub(
        lambda m: "#" * len(m.group(1)) + " " + m.group(2), text
    )
    text = _LIST.sub(_list_item, text)
    text = _HTML_TAG.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()