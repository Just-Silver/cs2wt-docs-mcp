# HTML 抓取通道 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把抓取层从违反 robots.txt 的 MediaWiki Action API 换成合规的 `/wiki/<标题>` HTML 通道，并把主键由 `pageid` 改为 `title`。

**Architecture:** 新增零依赖 `htmlparse.py`（`HTMLParser` 解析元数据/链接/正文转 Markdown）；`wiki.py` 的 `WikiClient` 换成 `HtmlClient`（链接 BFS 枚举 + 单页抓取）；`http.py` 增加 `assert_allowed_url` 硬守卫；`store/index/fetch/sync/cli` 全部改用 `title` 键与 `raw/<slug>.html`；MCP 工具同步去掉 `pageid` 字段；CI 用定时 workflow 全量抓取并把产物发布到 Release。

**Tech Stack:** Python ≥3.10 标准库（`html.parser`、`urllib`、`sqlite3`、`json`、`re`）；SQLite FTS5；GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-20-html-scraping-design.md`

## Global Constraints

- 语言：用户可见文档（README / spec / plan）与 commit 信息用**简体中文**；代码注释与 docstring 沿用现有代码库的**英文**风格（`http.py`、`index.py` 等均为英文）。
- 运行环境：Python ≥3.10；**不新增任何第三方依赖**（`pyproject.toml` 无改动）。
- robots 契约：只允许 `GET https://developer.valvesoftware.com/wiki/...`，query/fragment 必须为空，path 不含 `/w/`、不含 `Special:`；唯一例外是 Anubis 握手路径 `/.within.website/`（传输层内部，非抓取请求）。
- 主键：`title`（彻底移除 `pageid`）。
- raw 文件：`data/raw/<slug>.html`，`slug = urllib.parse.quote(title, safe="")`。
- 测试**全离线**（注入 fake session / fake client，绝不联网）。
- 测试命令（本机 `tests` 会被 site-packages 抢占，必须用 discover 形式）：
  `python -m unittest discover -s tests -p "test_xxx.py" -v`；全量 `python -m unittest discover -s tests -v`。

## 本计划的非目标（明确延后）

- **§8.3 条件请求（If-None-Match / If-Modified-Since / 304）**：规格明确允许「不支持则回退普通 GET」。Anubis 下的 304 语义未实测（规格 §15 自列为风险），本计划不实现该优化，改在 README 记为后续。行为与普通 GET 一致，仅多传字节。
- **§10.7 MCP 只从 Release 取数**：按用户裁定另立计划；本计划只做 MCP 的 `pageid→title` 字段适配（强制，否则 KeyError）。
- **§10.6 的 `if: failure()` 整轮兜底重跑**：属可选项，本计划用 `nick-fields/retry` 包裹抓取步骤即可，不实现防死循环的兜底 job。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/cs2wt/http.py` | HTTP 传输 + robots 守卫 | 修改 |
| `src/cs2wt/htmlparse.py` | HTML → 元数据 / 链接 / Markdown（零依赖） | **新建** |
| `src/cs2wt/wiki.py` | `HtmlClient`：链接 BFS 枚举 + 单页抓取 | 重写 |
| `src/cs2wt/store.py` | raw 文件路径（`.html`）与 manifest 键 | 修改 |
| `src/cs2wt/index.py` | FTS5 索引，`title` 主键 | 修改 |
| `src/cs2wt/fetch.py` | 全量抓取（BFS + 落盘 + manifest） | 重写 |
| `src/cs2wt/sync.py` | 增量同步（revid 比对 + 404 删除） | 重写 |
| `src/cs2wt/cli.py` | 去掉 `--api`，`list` 输出 title | 修改 |
| `src/cs2wt/mcp_config.py` | 去掉 `api` 配置项 | 修改 |
| `src/cs2wt/mcp_manager.py` | 改用 `HtmlClient`，`list_titles` 返回 title | 修改 |
| `src/cs2wt/mcp_tools.py` | 去掉返回中的 `pageid` | 修改 |
| `src/cs2wt/mcp_server.py` | 工具 docstring 去掉 pageid | 修改 |
| `src/cs2wt/convert.py` | wikitext 转换（被 htmlparse 取代） | **删除** |
| `.github/workflows/update-docs.yml` | 定时全量抓取 + 发布 Release | **新建** |
| `README.md` | 说明 HTML 通道、迁移、CI | 修改 |
| `tests/test_http_guard.py` | 守卫单测 | **新建** |
| `tests/test_htmlparse.py` | 解析单测 | **新建** |
| `tests/test_store.py` | 存储单测 | **新建** |
| `tests/test_index.py` | 索引 title 键单测 | **新建** |
| `tests/test_wiki.py` | `HtmlClient` 单测 | **新建** |
| `tests/test_fetch.py` | 抓取单测 | **新建** |
| `tests/test_cli.py` | CLI 离线单测 | **新建** |
| `tests/test_sync.py` | 同步单测 | 重写 |
| `tests/test_mcp_manager.py` / `tests/test_mcp_tools.py` | MCP 适配 | 修改 |

---

## Task 1: HTTP 合规守卫 `assert_allowed_url`

**Files:**
- Modify: `src/cs2wt/http.py`
- Test: `tests/test_http_guard.py`

**Interfaces:**
- Produces: `assert_allowed_url(url: str) -> None`（违规抛 `ValueError`）；模块常量 `ALLOWED_HOST`、`ANUBIS_PATH_PREFIX`。

- [ ] **Step 1: 写失败测试** `tests/test_http_guard.py`

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.http import assert_allowed_url

OK = [
    "https://developer.valvesoftware.com/wiki/Assault",
    "https://developer.valvesoftware.com/wiki/Path_corner",
    "https://developer.valvesoftware.com/.within.website/x/cmd/anubis/api/pass-challenge?id=1",
]
BAD = [
    "http://developer.valvesoftware.com/wiki/Assault",       # 非 https
    "https://example.com/wiki/Assault",                      # 非目标 host
    "https://developer.valvesoftware.com/w/api.php",         # Disallow
    "https://developer.valvesoftware.com/w/Special:Export",  # Disallow
    "https://developer.valvesoftware.com/wiki/Special:Export/Foo",
    "https://developer.valvesoftware.com/wiki/Assault?title=Special:X",
    "https://developer.valvesoftware.com/wiki/Assault?action=history",
    "https://developer.valvesoftware.com/wiki/Assault#top",  # fragment
    "https://developer.valvesoftware.com/index.php",         # 非 /wiki/
]


class GuardTest(unittest.TestCase):
    def test_allowed(self):
        for url in OK:
            assert_allowed_url(url)  # 不应抛错

    def test_disallowed(self):
        for url in BAD:
            with self.assertRaises(ValueError):
                assert_allowed_url(url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_http_guard.py" -v`
Expected: FAIL（`ImportError: cannot import name 'assert_allowed_url'`）

- [ ] **Step 3: 实现守卫并接入 `_open`**（`src/cs2wt/http.py`）

在 `PASS_PATH` 附近新增：

```python
ALLOWED_HOST = "developer.valvesoftware.com"
ANUBIS_PATH_PREFIX = "/.within.website/"


def assert_allowed_url(url: str) -> None:
    """Enforce the robots.txt contract: only GET /wiki/<title> on the VDC host.

    The Anubis PoW handshake path is transport infrastructure, not a crawl
    request, so it is exempt.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != ALLOWED_HOST:
        raise ValueError(f"disallowed host/scheme: {url!r}")
    if parts.path.startswith(ANUBIS_PATH_PREFIX):
        return
    if parts.query or parts.fragment:
        raise ValueError(f"disallowed query/fragment: {url!r}")
    if not parts.path.startswith("/wiki/"):
        raise ValueError(f"disallowed path: {url!r}")
    if "/w/" in parts.path or "Special:" in parts.path:
        raise ValueError(f"disallowed path: {url!r}")
```

把 `_open` 改为在发请求前校验：

```python
    def _open(self, url: str) -> tuple[bytes, str]:
        assert_allowed_url(url)
        self._throttle()
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read(), response.geturl()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_http_guard.py" -v`
Expected: PASS（2 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/http.py tests/test_http_guard.py
git commit -m "功能：HTTP 层新增 robots 合规守卫 assert_allowed_url"
```

---

## Task 2: `htmlparse.extract_meta`

**Files:**
- Create: `src/cs2wt/htmlparse.py`
- Test: `tests/test_htmlparse.py`

**Interfaces:**
- Produces: `extract_meta(html: str) -> dict`，返回 `{"title": str, "revid": int | None, "timestamp": str}`；模块常量 `BASE_URL`、`page_url(title, base=BASE_URL) -> str`。

- [ ] **Step 1: 写失败测试** `tests/test_htmlparse.py`

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.htmlparse import extract_meta, page_url

FULL = """
<html><body>
<h1 id="firstHeading" class="firstHeading" lang="en">Assault</h1>
<div id="mw-content-text"><p>body</p></div>
<a href="/w/index.php?title=Assault&amp;oldid=218612">Permanent link</a>
<li>This page was last modified on 5 September 2018, at 02:16.</li>
</body></html>
"""


class ExtractMetaTest(unittest.TestCase):
    def test_full(self):
        meta = extract_meta(FULL)
        self.assertEqual(meta["title"], "Assault")
        self.assertEqual(meta["revid"], 218612)
        self.assertEqual(meta["timestamp"], "2018-09-05T02:16:00")

    def test_missing_revid_and_timestamp(self):
        meta = extract_meta("<h1 id='firstHeading'>Foo</h1>")
        self.assertEqual(meta["title"], "Foo")
        self.assertIsNone(meta["revid"])
        self.assertEqual(meta["timestamp"], "")

    def test_entities_decoded(self):
        meta = extract_meta("<h1 id='firstHeading'>A &amp; B</h1>")
        self.assertEqual(meta["title"], "A & B")

    def test_page_url(self):
        self.assertEqual(
            page_url("Path corner"),
            "https://developer.valvesoftware.com/wiki/Path_corner",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: FAIL（`ModuleNotFoundError: cs2wt.htmlparse`）

- [ ] **Step 3: 创建 `src/cs2wt/htmlparse.py`**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: PASS（4 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/htmlparse.py tests/test_htmlparse.py
git commit -m "功能：新增 HTML 元数据提取 extract_meta 与 page_url"
```

---

## Task 3: `htmlparse.extract_links`

**Files:**
- Modify: `src/cs2wt/htmlparse.py`
- Test: `tests/test_htmlparse.py`

**Interfaces:**
- Produces: `extract_links(html: str) -> list[str]`（归一化、去重、保序的文章标题）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_htmlparse.py`）

```python
from cs2wt.htmlparse import extract_links

LINKS = """
<div id="mw-content-text">
<a href="/wiki/Path_corner">Path corner</a>
<a href="/wiki/Path_corner">dup</a>
<a href="/wiki/Ai_goal_assault#top">fragment</a>
<a href="/wiki/Special:Search">special</a>
<a href="/wiki/File:Logo.png">file</a>
<a href="/wiki/Template:Note">template</a>
<a href="/w/index.php?title=X">api path</a>
<a href="https://example.com/wiki/External">external</a>
<a href="//example.com/wiki/Proto">protocol-relative</a>
</div>
"""


class ExtractLinksTest(unittest.TestCase):
    def test_filters_and_normalizes(self):
        self.assertEqual(
            extract_links(LINKS),
            ["Path corner", "Ai goal assault"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: FAIL（`ImportError: cannot import name 'extract_links'`）

- [ ] **Step 3: 实现**（追加到 `src/cs2wt/htmlparse.py`）

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: PASS（5 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/htmlparse.py tests/test_htmlparse.py
git commit -m "功能：新增 HTML 链接提取 extract_links"
```

---

## Task 4: `htmlparse.html_to_markdown`

**Files:**
- Modify: `src/cs2wt/htmlparse.py`
- Test: `tests/test_htmlparse.py`

**Interfaces:**
- Produces: `html_to_markdown(html: str) -> str`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_htmlparse.py`）

```python
from cs2wt.htmlparse import html_to_markdown

PAGE = """
<html><body>
<div id="toc"><p>toc junk</p></div>
<div id="mw-content-text" class="mw-body-content">
  <h2><span class="mw-headline">Alpha</span></h2>
  <p>Hello <b>bold</b> and <i>italic</i> with <code>x</code>.</p>
  <ul><li>one</li><li>two</li></ul>
  <pre>code line</pre>
  <a href="/wiki/Path_corner">Path corner</a>
  <a href="https://example.com">Ext</a>
  <span class="mw-editsection">edit</span>
  <table><tr><td>drop me</td></tr></table>
  <script>var x = 1;</script>
</div>
</body></html>
"""


class HtmlToMarkdownTest(unittest.TestCase):
    def test_conversion(self):
        md = html_to_markdown(PAGE)
        self.assertIn("## Alpha", md)
        self.assertIn("Hello **bold** and *italic* with `x`.", md)
        self.assertIn("- one", md)
        self.assertIn("- two", md)
        self.assertIn("```", md)
        self.assertIn("code line", md)
        self.assertIn("[Path corner](https://developer.valvesoftware.com/wiki/Path_corner)", md)
        self.assertIn("[Ext](https://example.com)", md)
        # dropped elements
        self.assertNotIn("toc junk", md)
        self.assertNotIn("edit", md)
        self.assertNotIn("drop me", md)
        self.assertNotIn("var x", md)

    def test_falls_back_to_body(self):
        md = html_to_markdown("<html><body><p>plain</p></body></html>")
        self.assertEqual(md, "plain")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: FAIL（`ImportError: cannot import name 'html_to_markdown'`）

- [ ] **Step 3: 实现**（追加到 `src/cs2wt/htmlparse.py`）

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_htmlparse.py" -v`
Expected: PASS（7 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/htmlparse.py tests/test_htmlparse.py
git commit -m "功能：新增 HTML 转 Markdown html_to_markdown"
```

---

## Task 5: `store.py` 改用 `title` 键与 `.html` 路径

**Files:**
- Modify: `src/cs2wt/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `slug(title: str) -> str`；`raw_path(data_dir, title: str) -> Path`；`manifest_by_title(manifest: dict) -> dict[str, dict]`。
- Removes: `manifest_by_pageid`。

- [ ] **Step 1: 写失败测试** `tests/test_store.py`

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt import store


class StoreTest(unittest.TestCase):
    def test_slug_is_filesystem_safe(self):
        self.assertEqual(store.slug("Path corner"), "Path%20corner")
        self.assertEqual(store.slug("A/B:C"), "A%2FB%3AC")

    def test_raw_path_uses_html(self):
        path = store.raw_path("data", "Path corner")
        self.assertEqual(path.name, "Path%20corner.html")
        self.assertEqual(path.parent.name, "raw")

    def test_manifest_by_title(self):
        manifest = {"pages": [{"title": "A", "revid": 1}, {"title": "B", "revid": 2}]}
        self.assertEqual(store.manifest_by_title(manifest)["B"]["revid"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_store.py" -v`
Expected: FAIL（`AttributeError: module 'cs2wt.store' has no attribute 'slug'`）

- [ ] **Step 3: 实现**（`src/cs2wt/store.py`）

顶部补 `import urllib.parse`，替换 `raw_path` 与 `manifest_by_pageid`：

```python
def slug(title: str) -> str:
    """Filesystem-safe, reversible filename for a page title."""
    return urllib.parse.quote(title, safe="")


def raw_path(data_dir, title: str) -> Path:
    return raw_dir(data_dir) / f"{slug(title)}.html"


def manifest_by_title(manifest: dict) -> dict[str, dict]:
    return {record["title"]: record for record in manifest.get("pages", [])}
```

模块 docstring 由 "raw wikitext files" 改为 "raw HTML files"。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_store.py" -v`
Expected: PASS（3 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/store.py tests/test_store.py
git commit -m "重构：raw 文件改用 title 的 slug 与 .html 后缀"
```

---

## Task 6: `index.py` 改用 `title` 主键

**Files:**
- Modify: `src/cs2wt/index.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `htmlparse.html_to_markdown`、`htmlparse.page_url`。
- Produces: `DocIndex.upsert(*, title, content, revid, timestamp, url)`；`DocIndex.delete(title)`；`DocIndex.search(query, limit=10) -> list[{title,url,snippet,score}]`；`DocIndex.get(key: str | int) -> dict | None`（数字按 rowid，否则 title）；`DocIndex.get_by_title(title)`；`DocIndex.list_titles() -> list[str]`；`build_index(data_dir, db_path)`。

- [ ] **Step 1: 写失败测试** `tests/test_index.py`

```python
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.index import DocIndex, page_url


class DocIndexTitleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.idx = DocIndex(Path(self._tmp.name) / "docs.sqlite")

    def tearDown(self):
        self.idx.close()
        self._tmp.cleanup()

    def _put(self, title, revid, content):
        self.idx.upsert(
            title=title, content=content, revid=revid,
            timestamp="t", url=page_url(title),
        )

    def test_upsert_and_search_has_no_pageid(self):
        self._put("Alpha", 1, "hello world")
        hits = self.idx.search("hello")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "Alpha")
        self.assertNotIn("pageid", hits[0])

    def test_rowid_is_stable_across_updates(self):
        self._put("Alpha", 1, "one")
        first = self.idx.get("Alpha")
        self._put("Alpha", 2, "two")
        second = self.idx.get("Alpha")
        self.assertEqual(second["revid"], 2)
        self.assertIn("two", second["content"])
        self.assertEqual(self.idx.count(), 1)

    def test_get_by_rowid_and_title(self):
        self._put("Alpha", 1, "one")
        self.assertEqual(self.idx.get("Alpha")["title"], "Alpha")
        # 首条插入的 rowid 为 1，纯数字走 rowid 查询
        self.assertEqual(self.idx.get(1)["title"], "Alpha")
        self.assertIsNone(self.idx.get(999))

    def test_delete_by_title(self):
        self._put("Alpha", 1, "one")
        self.idx.delete("Alpha")
        self.assertEqual(self.idx.count(), 0)

    def test_list_titles_returns_strings(self):
        self._put("B", 1, "b")
        self._put("A", 1, "a")
        self.assertEqual(self.idx.list_titles(), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_index.py" -v`
Expected: FAIL（`TypeError: upsert() got an unexpected keyword argument 'title'` / schema 仍含 pageid）

- [ ] **Step 3: 实现**（`src/cs2wt/index.py`）

改动要点（完整替换对应片段）：

```python
from .htmlparse import html_to_markdown, page_url

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    title,
    content,
    revid     UNINDEXED,
    timestamp UNINDEXED,
    url       UNINDEXED,
    tokenize = 'unicode61'
);
"""
```

删除旧的 `WIKI_BASE` / `page_url` 定义（改由 `htmlparse` 提供）。

```python
    def upsert(self, *, title, content, revid, timestamp, url) -> None:
        row = self.conn.execute("SELECT rowid FROM docs WHERE title = ?", (title,)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO docs(title, content, revid, timestamp, url) VALUES (?, ?, ?, ?, ?)",
                (title, content, revid, timestamp, url),
            )
        else:
            rowid = row[0]
            self.conn.execute("DELETE FROM docs WHERE rowid = ?", (rowid,))
            self.conn.execute(
                "INSERT INTO docs(rowid, title, content, revid, timestamp, url) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rowid, title, content, revid, timestamp, url),
            )

    def delete(self, title: str) -> None:
        self.conn.execute("DELETE FROM docs WHERE title = ?", (title,))
```

```python
    def search(self, query: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT title, url, "
            "snippet(docs, 1, '[', ']', '…', 12) AS snippet, "
            "bm25(docs) AS score "
            "FROM docs WHERE docs MATCH ? ORDER BY score LIMIT ?",
            (_fts_query(query), limit),
        ).fetchall()
        return [
            {"title": r[0], "url": r[1], "snippet": r[2], "score": r[3]}
            for r in rows
        ]

    def get(self, key) -> dict | None:
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            where, params = "rowid = ?", (int(key),)
        else:
            where, params = "title = ?", (key,)
        row = self.conn.execute(
            "SELECT title, revid, timestamp, url, content FROM docs WHERE " + where,
            params,
        ).fetchone()
        if not row:
            return None
        keys = ("title", "revid", "timestamp", "url", "content")
        return dict(zip(keys, row))

    def get_by_title(self, title: str) -> dict | None:
        return self.get(title)

    def list_titles(self) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute("SELECT title FROM docs ORDER BY title")
        ]
```

`build_index` 的 upsert 调用去掉 `pageid=`，`content` 改 `html_to_markdown(raw)`（`raw` 现在是 HTML）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_index.py" -v`
Expected: PASS（5 tests OK）

> 说明：旧 `data/docs.sqlite` schema 不兼容，`CREATE TABLE IF NOT EXISTS` 不会重建——按规格 §9 删除后重建。

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/index.py tests/test_index.py
git commit -m "重构：FTS5 索引主键由 pageid 改为 title"
```

---

## Task 7: `HtmlClient`（重写 `wiki.py`）

**Files:**
- Modify: `src/cs2wt/wiki.py`
- Test: `tests/test_wiki.py`

**Interfaces:**
- Consumes: `htmlparse.extract_meta/extract_links/page_url`、`http.AnubisSession`。
- Produces:
  - `PageContent`（frozen dataclass）：`title: str`、`revid: int | None`、`timestamp: str`、`html: str`。
  - `HtmlClient(session, base_url=BASE_URL)`；`.base_url`；`.page_url(title)`；`.fetch_page(title) -> PageContent | None`（404 → `None`）；`.iter_pages(prefix, seeds=(), known=None) -> Iterator[PageContent]`。
- Removes: `WikiClient`、`DEFAULT_API`、`PageContent.content`。

- [ ] **Step 1: 写失败测试** `tests/test_wiki.py`

```python
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.wiki import HtmlClient

BASE = "https://developer.valvesoftware.com"


def page_html(title, links=(), revid=1):
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return (
        f'<h1 id="firstHeading">{title}</h1>'
        f'<div id="mw-content-text"><p>{title} body</p>{anchors}</div>'
        f'<a href="/w/index.php?title={title}&oldid={revid}">link</a>'
    ).encode("utf-8")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return self.pages[url]


class HtmlClientTest(unittest.TestCase):
    def test_fetch_page_parses_meta(self):
        client = HtmlClient(FakeSession({f"{BASE}/wiki/A": page_html("A", revid=7)}))
        page = client.fetch_page("A")
        self.assertEqual(page.title, "A")
        self.assertEqual(page.revid, 7)
        self.assertIn("A body", page.html)

    def test_fetch_page_404_returns_none(self):
        client = HtmlClient(FakeSession({}))
        self.assertIsNone(client.fetch_page("Missing"))

    def test_iter_pages_bfs_filters_prefix_and_dedups(self):
        pages = {
            f"{BASE}/wiki/Root": page_html("Root", links=["Root/Child_One", "Root/Child_Two", "Outside"]),
            f"{BASE}/wiki/Root/Child_One": page_html("Root/Child One", links=["Root/Leaf"]),
            f"{BASE}/wiki/Root/Child_Two": page_html("Root/Child Two", links=["Root/Child_One"]),
            f"{BASE}/wiki/Root/Leaf": page_html("Root/Leaf"),
            f"{BASE}/wiki/Outside": page_html("Outside"),
        }
        client = HtmlClient(FakeSession(pages))
        titles = [page.title for page in client.iter_pages("Root")]
        self.assertEqual(titles, ["Root", "Root/Child One", "Root/Child Two", "Root/Leaf"])

    def test_iter_pages_reuses_known_cache(self):
        session = FakeSession({f"{BASE}/wiki/Root": page_html("Root")})
        client = HtmlClient(session)
        known = {}
        list(client.iter_pages("Root", known=known))
        self.assertIn("Root", known)
        # 第二次复用缓存，不再发请求
        before = len(session.requested)
        list(client.iter_pages("Root", known=known))
        self.assertEqual(len(session.requested), before)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_wiki.py" -v`
Expected: FAIL（`ImportError: cannot import name 'HtmlClient'`）

- [ ] **Step 3: 实现**（整体替换 `src/cs2wt/wiki.py`）

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_wiki.py" -v`
Expected: PASS（4 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/wiki.py tests/test_wiki.py
git commit -m "重构：WikiClient 换成合规的 HtmlClient（链接 BFS + 单页抓取）"
```

---

## Task 8: `fetch.py` 走 HTML 通道

**Files:**
- Modify: `src/cs2wt/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `HtmlClient.iter_pages`、`store.*`。
- Produces: `crawl(client: HtmlClient, *, prefix: str, out_dir) -> dict`；manifest 记录形如 `{"title", "revid", "timestamp", "file"}`。

- [ ] **Step 1: 写失败测试** `tests/test_fetch.py`

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.fetch import crawl
from cs2wt.wiki import PageContent


class FakeClient:
    base_url = "https://developer.valvesoftware.com"

    def __init__(self, pages):
        self._pages = pages

    def iter_pages(self, prefix, seeds=(), known=None):
        for title in [prefix, *seeds]:
            page = self._pages.get(title)
            if page is not None:
                yield page


def page(title, revid):
    return PageContent(title=title, revid=revid, timestamp="t", html=f"<h1>{title}</h1>")


class FetchTest(unittest.TestCase):
    def test_crawl_writes_html_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient({"Root": page("Root", 1), "A": page("A", 2)})
            manifest = crawl(client, prefix="Root", out_dir=d)

            self.assertEqual((Path(d) / "raw" / "Root.html").read_text(encoding="utf-8"), "<h1>Root</h1>")
            self.assertEqual((Path(d) / "raw" / "A.html").exists(), True)
            titles = [record["title"] for record in manifest["pages"]]
            self.assertEqual(titles, ["Root", "A"])
            self.assertEqual(manifest["pages"][1]["file"], "raw/A.html")
            self.assertEqual(manifest["source"], client.base_url)
            on_disk = json.loads((Path(d) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["page_count"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_fetch.py" -v`
Expected: FAIL（`TypeError`：旧 `crawl` 需要 `WikiClient`）

- [ ] **Step 3: 实现**（整体替换 `src/cs2wt/fetch.py`）

```python
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
    seeds = [record["title"] for record in store.load_manifest(out_dir).get("pages", [])]

    records: list[dict] = []
    for page in client.iter_pages(prefix, seeds=seeds):
        store.raw_path(out_dir, page.title).write_text(page.html, encoding="utf-8")
        records.append(
            {
                "title": page.title,
                "revid": page.revid,
                "timestamp": page.timestamp,
                "file": f"raw/{store.slug(page.title)}.html",
            }
        )
        print(f"  fetched {page.title} (rev {page.revid})")

    manifest = {
        "source": client.base_url,
        "prefix": prefix,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": records,
    }
    store.save_manifest(out_dir, manifest)
    return manifest
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_fetch.py" -v`
Expected: PASS（1 test OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/fetch.py tests/test_fetch.py
git commit -m "重构：fetch 改用 HtmlClient 抓取并落盘原始 HTML"
```

---

## Task 9: `sync.py` 走 HTML 通道

**Files:**
- Modify: `src/cs2wt/sync.py`
- Test: `tests/test_sync.py`（重写）

**Interfaces:**
- Consumes: `HtmlClient.fetch_page/iter_pages`、`store.*`、`index.DocIndex`、`htmlparse.html_to_markdown/page_url`。
- Produces: `SyncReport`（`added/updated/removed/unchanged` 均为 `list[str]`，元素是 title）；`sync(client, *, prefix, data_dir, db_path, dry_run=False) -> SyncReport`。

- [ ] **Step 1: 重写测试** `tests/test_sync.py`

```python
"""Offline unit tests for incremental sync (fake HTML client, no network)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.index import DocIndex
from cs2wt.sync import sync
from cs2wt.wiki import PageContent


def page(title, revid, links=()):
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return PageContent(
        title=title,
        revid=revid,
        timestamp="2026-01-01T00:00:00Z",
        html=f'<div id="mw-content-text"><p>{title} body</p>{anchors}</div>',
    )


class FakeClient:
    base_url = "https://developer.valvesoftware.com"

    def __init__(self, pages, missing=()):
        self.pages = {p.title: p for p in pages}
        self.missing = set(missing)
        self.fetched = []

    def fetch_page(self, title):
        self.fetched.append(title)
        if title in self.missing:
            return None
        return self.pages.get(title)

    def iter_pages(self, prefix, seeds=(), known=None):
        known = {} if known is None else known
        titles = [prefix] + [t for t in self.pages if t.startswith(prefix) and t != prefix]
        for title in titles:
            page_obj = known.get(title) or self.fetch_page(title)
            if page_obj is None:
                continue
            known[title] = page_obj
            yield page_obj


class SyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir()
        self.db = self.data / "docs.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self):
        return json.loads((self.data / "manifest.json").read_text(encoding="utf-8"))

    def _count(self):
        index = DocIndex(self.db)
        try:
            return index.count()
        finally:
            index.close()

    def test_first_sync_adds_everything(self):
        client = FakeClient([page("Root", 1, ["Root/A", "Root/B"]), page("Root/A", 10), page("Root/B", 20)])
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.added), ["Root", "Root/A", "Root/B"])
        self.assertEqual(report.updated, [])
        self.assertEqual(report.removed, [])
        self.assertEqual(self._count(), 3)
        self.assertTrue((self.data / "raw" / "Root%2FA.html").exists())

    def test_no_change_is_a_noop(self):
        pages = [page("Root", 1, ["Root/A"]), page("Root/A", 10)]
        sync(FakeClient(pages), prefix="Root", data_dir=self.data, db_path=self.db)
        client = FakeClient(pages)
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.unchanged), ["Root", "Root/A"])
        self.assertEqual(report.added + report.updated + report.removed, [])

    def test_revid_change_updates_page(self):
        sync(FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        report = sync(FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 11)]),
                      prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(report.updated, ["Root/A"])
        index = DocIndex(self.db)
        self.assertIn("Root/A body", index.get("Root/A")["content"])
        index.close()

    def test_removed_page_drops_from_index_but_keeps_raw(self):
        sync(FakeClient([page("Root", 1, ["Root/A", "Root/B"]), page("Root/A", 10), page("Root/B", 20)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        report = sync(
            FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)], missing={"Root/B"}),
            prefix="Root", data_dir=self.data, db_path=self.db,
        )

        self.assertEqual(report.removed, ["Root/B"])
        self.assertEqual(self._count(), 2)
        self.assertTrue((self.data / "raw" / "Root%2FB.html").exists())

    def test_dry_run_fetches_but_writes_nothing(self):
        client = FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)])
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db, dry_run=True)

        self.assertEqual(sorted(report.added), ["Root", "Root/A"])
        self.assertFalse((self.data / "manifest.json").exists())
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_sync.py" -v`
Expected: FAIL（旧 sync 依赖 `iter_pages_with_revisions` / `pageid`）

- [ ] **Step 3: 实现**（整体替换 `src/cs2wt/sync.py`）

```python
"""Incremental sync between the local mirror and the wiki.

Change detection compares the revision id parsed from each page's HTML.  A
page's own 404 is the only signal for removal; link enumeration is used only to
discover new pages, so an incomplete crawl can never cause a false deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .htmlparse import html_to_markdown, page_url
from .index import DocIndex


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added  "
            f"~{len(self.updated)} updated  "
            f"-{len(self.removed)} removed  "
            f"={len(self.unchanged)} unchanged"
        )


def sync(
    client,
    *,
    prefix: str,
    data_dir: str | Path,
    db_path: str | Path,
    dry_run: bool = False,
) -> SyncReport:
    """Bring the local mirror in line with the wiki under ``prefix``."""
    data_dir = Path(data_dir)
    manifest = store.load_manifest(data_dir)
    local = store.manifest_by_title(manifest)

    report = SyncReport()
    cache: dict = {}

    # 1. 已有页：逐页抓取，404 判定删除，否则按 revid 比对。
    for title in local:
        page = client.fetch_page(title)
        if page is None:
            report.removed.append(title)
            continue
        cache[title] = page
        if page.revid != local[title]["revid"]:
            report.updated.append(title)
        else:
            report.unchanged.append(title)

    # 2. 新页：从根页面 BFS 发现 manifest 之外的 title（复用 cache，避免重复抓取）。
    for page in client.iter_pages(prefix, seeds=list(local), known=cache):
        if page.title not in local:
            report.added.append(page.title)

    if dry_run:
        return report

    records = dict(local)
    store.raw_dir(data_dir).mkdir(parents=True, exist_ok=True)
    index = DocIndex(db_path)
    try:
        for title in sorted(set(report.added) | set(report.updated)):
            page = cache.get(title) or client.fetch_page(title)
            if page is None:
                continue
            store.raw_path(data_dir, page.title).write_text(page.html, encoding="utf-8")
            records[page.title] = {
                "title": page.title,
                "revid": page.revid,
                "timestamp": page.timestamp,
                "file": f"raw/{store.slug(page.title)}.html",
            }
            index.upsert(
                title=page.title,
                content=html_to_markdown(page.html),
                revid=page.revid,
                timestamp=page.timestamp,
                url=page_url(page.title),
            )

        for title in report.removed:
            records.pop(title, None)
            index.delete(title)

        source = getattr(client, "base_url", "") or manifest.get("source", "")
        manifest["pages"] = list(records.values())
        manifest["source"] = source
        manifest["prefix"] = prefix
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
        store.save_manifest(data_dir, manifest)

        index.set_meta("prefix", prefix)
        index.set_meta("source", source)
        index.set_meta("generated_at", manifest["generated_at"])
        index.set_meta("page_count", str(manifest["page_count"]))
        index.commit()
    finally:
        index.close()

    return report
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_sync.py" -v`
Expected: PASS（5 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/sync.py tests/test_sync.py
git commit -m "重构：sync 改用 HtmlClient 与 title 键，删除仅由自身 404 判定"
```

---

## Task 10: CLI 去掉 `--api`、`list` 输出 title

**Files:**
- Modify: `src/cs2wt/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `wiki.HtmlClient`、`index.DocIndex`。
- Produces: `main(argv=None) -> int`；`_new_client(args) -> HtmlClient`；`_build_parser()`（无 `--api`）。

- [ ] **Step 1: 写失败测试** `tests/test_cli.py`

```python
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.cli import _build_parser, main
from cs2wt.index import DocIndex


class CliTest(unittest.TestCase):
    def test_no_api_option(self):
        with self.assertRaises(SystemExit):
            _build_parser().parse_args(["--api", "x", "status"])

    def test_list_prints_titles(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "docs.sqlite"
            index = DocIndex(db)
            index.upsert(title="Alpha", content="a", revid=1, timestamp="t", url="u")
            index.commit()
            index.close()

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "list"])
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue().strip(), "Alpha")

    def test_get_by_title(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "docs.sqlite"
            index = DocIndex(db)
            index.upsert(title="Alpha", content="hello body", revid=1, timestamp="t", url="u")
            index.commit()
            index.close()

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "get", "Alpha"])
            self.assertEqual(code, 0)
            self.assertIn("hello body", out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`
Expected: FAIL（`--api` 仍被接受；`list` 打印 `1\tAlpha`）

- [ ] **Step 3: 实现**（`src/cs2wt/cli.py`）

- 导入改为：`from .wiki import HtmlClient`（删掉 `DEFAULT_API, WikiClient`）。
- 删除 `parser.add_argument("--api", ...)`。
- `_new_client`：

```python
def _new_client(args) -> HtmlClient:
    session = AnubisSession(
        user_agent=args.ua, cookie_path=args.cookie, delay=args.delay
    )
    return HtmlClient(session)
```

- `get` 分支：`page = index.get(args.key)`（`DocIndex.get` 已支持数字/标题）。
- `list` 分支：

```python
    if args.command == "list":
        index = DocIndex(db)
        for title in index.list_titles():
            print(title)
        index.close()
        return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`
Expected: PASS（3 tests OK）

- [ ] **Step 5: 提交**

```bash
git add src/cs2wt/cli.py tests/test_cli.py
git commit -m "重构：CLI 去掉 --api，list/get 适配 title 键"
```

---

## Task 11: MCP 字段适配 + 删除 `convert.py`

**Files:**
- Delete: `src/cs2wt/convert.py`
- Modify: `src/cs2wt/mcp_config.py`、`src/cs2wt/mcp_manager.py`、`src/cs2wt/mcp_tools.py`、`src/cs2wt/mcp_server.py`
- Test: `tests/test_mcp_config.py`、`tests/test_mcp_manager.py`、`tests/test_mcp_tools.py`

**Interfaces:**
- `ServerConfig` 去掉 `api` 字段；`--api` / `CS2WT_API` 不再识别。
- `IndexManager.list_titles() -> list[str]`；`IndexManager.get(key)` 透传 `DocIndex.get`。
- `tool_search_docs` / `tool_get_page` / `tool_list_pages` 返回不再含 `pageid`。

- [ ] **Step 1: 更新测试**

`tests/test_mcp_config.py`：现有用例未涉及 `api`，**无需改动**（可选：新增一条断言 `--api` 不再被识别，抛出 `SystemExit`）。

`tests/test_mcp_manager.py`：`make_config` 去掉 `api="..."`；`seed_index` 改为 title 键：

```python
def seed_index(cfg: ServerConfig) -> None:
    index = DocIndex(cfg.db)
    index.upsert(title="Page", content="hello world", revid=1, timestamp="t", url="u")
    index.commit()
    index.close()
```

`tests/test_mcp_tools.py`：`FakeManager.pages["Doc"]` 去掉 `"pageid": 1`；`search` 返回项去掉 `pageid`；`list_titles` 返回 `["Doc"]`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_mcp_*.py" -v`
Expected: FAIL（`TypeError: ServerConfig() got an unexpected keyword argument 'api'`；`KeyError: 'pageid'`）

- [ ] **Step 3: 实现**

`src/cs2wt/mcp_config.py`：
- 删除 `from .wiki import DEFAULT_API`；删除 `ServerConfig.api` 字段与构造参数；删除 `parser.add_argument("--api")`；删除 `api = ...` 一行与返回中的 `api=api`。

`src/cs2wt/mcp_manager.py`：
- 导入改为 `from .wiki import HtmlClient`。
- `_new_client`：

```python
def _new_client(config: ServerConfig) -> HtmlClient:
    session = AnubisSession(
        user_agent=config.ua, cookie_path=config.cookie, delay=config.delay
    )
    return HtmlClient(session)
```

- `list_titles` 返回类型与实现：

```python
    def list_titles(self) -> list[str]:
        with self._lock:
            if self._reader is None:
                return []
            return self._reader.list_titles()
```

- `get` 简化为 `return self._reader.get(key)`（`DocIndex.get` 已处理数字/标题）。

`src/cs2wt/mcp_tools.py`：
- `tool_get_page` 未找到章节分支去掉 `"pageid": page["pageid"]`；正常分支去掉 `"pageid": page["pageid"]`。
- `tool_list_pages`：

```python
    pages = [{"title": title} for title in manager.list_titles()]
```

`src/cs2wt/mcp_server.py`：把三处 docstring 中的 “pageid” 措辞改为“标题（或数字 rowid）”，并去掉返回字段清单里的 `pageid`。

删除文件：

```bash
git rm src/cs2wt/convert.py
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_mcp_*.py" -v`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS（含新测试，约 40+ 项），无 `pageid` 残留。

- [ ] **Step 6: 提交**

```bash
git add -A src/cs2wt tests
git commit -m "重构：MCP 工具与配置适配 title 键，删除 wikitext 转换模块"
```

---

## Task 12: GitHub Actions 定时抓取工作流

**Files:**
- Create: `.github/workflows/update-docs.yml`

**Interfaces:**
- 无代码接口；产物为 Release `data-latest` 的 `docs.sqlite` + `manifest.json`。

- [ ] **Step 1: 创建工作流**（内容按规格 §10.5）

```yaml
name: 更新文档索引

on:
  schedule:
    - cron: '17 3 1 * *'   # 每月 1 日 03:17 UTC
  workflow_dispatch:

concurrency:
  group: update-docs
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e .

      - name: 全量抓取并建索引（失败自动重试）
        uses: nick-fields/retry@v3
        with:
          timeout_minutes: 20
          max_attempts: 3
          retry_wait_seconds: 30
          command: |
            cs2wt fetch --cookie "$RUNNER_TEMP/cookies.txt"
            cs2wt build

      - name: 发布产物
        run: |
          gh release view data-latest >/dev/null 2>&1 \
            || gh release create data-latest --title "文档索引（滚动）" --notes "由 CI 自动更新"
          gh release upload data-latest data/docs.sqlite data/manifest.json --clobber
```

- [ ] **Step 2: 校验 YAML 语法**

Run: `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/update-docs.yml').read_text(encoding='utf-8')); print('ok')"`
Expected: `ok`。若环境无 `pyyaml`，跳过并在报告注明「仅人工复核」（工作流无法离线执行，最终验证依赖合入 `main` 后 `workflow_dispatch` 手动触发）。

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/update-docs.yml
git commit -m "构建：新增定时全量抓取与 Release 产物发布工作流"
```

---

## Task 13: README 与迁移说明

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README**

必须包含：
1. 抓取通道改为 `/wiki/<标题>` HTML，并**明确 robots.txt 合规**（引用 §3 契约与守卫）。
2. 主键由 `pageid` 改为 `title`；MCP 返回字段同步变化。
3. **迁移步骤**（规格 §9）：

   ```
   # 保留 data/manifest.json（fetch 会读取其 title 作为 BFS 种子）
   删除 data/docs.sqlite        # 旧 schema 不兼容
   删除 data/raw/*.wiki         # 改用 raw/*.html
   cs2wt fetch                  # HTML 全量抓取
   cs2wt build                  # 重建 FTS5 索引
   ```

4. CI：每月一次定时全量抓取并发布 Release `data-latest`；公共仓库 60 天无活动会被禁用 `schedule`，用 `workflow_dispatch` 手动兜底（规格 §10.2）。
5. 后续项：条件请求（304）优化、MCP 改为只从 Release 取数（规格 §10.7）。

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "文档：说明 HTML 抓取通道、title 键迁移与 CI 更新"
```

---

## Spec 覆盖对照

| 规格章节 | 任务 |
|---|---|
| §3 robots 契约 / `assert_allowed_url` | Task 1 |
| §6.1 `extract_meta` | Task 2 |
| §6.2 `extract_links` | Task 3 |
| §6.3 `html_to_markdown` | Task 4 |
| §7.3 raw `.html` / slug | Task 5 |
| §7.1/§7.4 title 主键与 FTS schema | Task 6 |
| §4.2/§5 `HtmlClient` 枚举与抓取 | Task 7 |
| §4.2/§5 `fetch` | Task 8 |
| §8 增量同步 / §11 错误处理 | Task 9 |
| §12 CLI | Task 10 |
| §7.5 MCP 字段 / §4.1 删除 convert.py | Task 11 |
| §10.2–§10.5 CI | Task 12 |
| §9 迁移 / §10.2 说明 | Task 13 |
| §13 测试 | 各任务的 Test 步骤 |
| §14 零依赖 | Global Constraints（无 pyproject 改动） |
| §16 验收 | 全量回归（Task 11 Step 5） |
| §8.3 条件请求 | **非目标**（规格允许回退，记入 README 后续） |
| §10.7 MCP 从 Release 取数 | **非目标**（另立计划） |
| §10.6 整轮兜底重跑 | **非目标**（`retry` action 已覆盖） |