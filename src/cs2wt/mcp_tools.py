"""Tool handlers: JSON-in-text results over a read-only index."""

from __future__ import annotations

import json

from .sections import extract_section


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _state(manager) -> str:
    return getattr(manager, "state", "READY")


def _error(manager):
    return getattr(manager, "error", None)


def _initializing() -> str:
    return _dumps({"status": "initializing", "message": "索引初始化中，请稍后重试"})


def tool_search_docs(manager, query: str, limit: int = 10) -> str:
    if _state(manager) == "INITIALIZING":
        return _initializing()
    hits = manager.search(query, limit)
    payload = {"count": len(hits), "results": hits}
    if _state(manager) == "ERROR" and not hits:
        payload["status"] = "error"
        payload["message"] = f"索引刷新失败：{_error(manager)}"
    elif _state(manager) == "REFRESHING":
        payload["refreshing"] = True
    return _dumps(payload)


def tool_get_page(manager, id_or_title: str, section: str | None = None) -> str:
    if _state(manager) == "INITIALIZING":
        return _initializing()
    page = manager.get(id_or_title)
    if page is None:
        if _state(manager) == "ERROR":
            return _dumps(
                {
                    "found": False,
                    "status": "error",
                    "message": f"索引刷新失败：{_error(manager)}",
                }
            )
        return _dumps({"found": False, "message": f"未找到页面：{id_or_title}"})

    content = page["content"]
    if section:
        extracted = extract_section(content, section)
        if extracted is None:
            return _dumps(
                {
                    "found": False,
                    "message": f"未找到章节：{section}",
                    "title": page["title"],
                }
            )
        content = extracted

    payload = {
        "found": True,
        "title": page["title"],
        "url": page["url"],
        "revid": page["revid"],
        "timestamp": page["timestamp"],
        "content": content,
    }
    if _state(manager) == "REFRESHING":
        payload["refreshing"] = True
    return _dumps(payload)


def tool_list_pages(manager) -> str:
    if _state(manager) == "INITIALIZING":
        return _initializing()
    pages = [{"title": title} for title in manager.list_titles()]
    payload = {"count": len(pages), "pages": pages}
    if _state(manager) == "ERROR" and len(pages) == 0:
        payload["status"] = "error"
        payload["message"] = f"索引刷新失败：{_error(manager)}"
    elif _state(manager) == "REFRESHING":
        payload["refreshing"] = True
    return _dumps(payload)