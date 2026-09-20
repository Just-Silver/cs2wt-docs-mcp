"""Tool handlers: JSON-in-text results over a read-only index."""

from __future__ import annotations

import json

from .sections import extract_section


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def tool_search_docs(manager, query: str, limit: int = 10) -> str:
    hits = manager.search(query, limit)
    return _dumps({"count": len(hits), "results": hits})


def tool_get_page(manager, id_or_title: str, section: str | None = None) -> str:
    page = manager.get(id_or_title)
    if page is None:
        return _dumps({"found": False, "message": f"未找到页面：{id_or_title}"})

    content = page["content"]
    if section:
        extracted = extract_section(content, section)
        if extracted is None:
            return _dumps(
                {
                    "found": False,
                    "message": f"未找到章节：{section}",
                    "pageid": page["pageid"],
                    "title": page["title"],
                }
            )
        content = extracted

    return _dumps(
        {
            "found": True,
            "pageid": page["pageid"],
            "title": page["title"],
            "url": page["url"],
            "revid": page["revid"],
            "timestamp": page["timestamp"],
            "content": content,
        }
    )


def tool_list_pages(manager) -> str:
    pages = [{"pageid": pid, "title": title} for pid, title in manager.list_titles()]
    return _dumps({"count": len(pages), "pages": pages})