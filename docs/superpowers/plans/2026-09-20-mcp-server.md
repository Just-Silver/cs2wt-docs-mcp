# MCP 服务端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 cs2wt-docs-mcp 增加 MCP 服务端，把现有离线 FTS5 索引通过 stdio 暴露给 AI 助手。

**Architecture:** 新增 `mcp_config` / `mcp_manager` / `mcp_tools` / `mcp_server` 四个模块；服务端用官方 `mcp` SDK v2 的 `MCPServer` + `@mcp.tool()`；启动后由后台线程执行一次刷新（无索引全量、有索引增量），不阻塞就绪；复用现有 `DocIndex` / `sync` / `crawl` / `build_index`。

**Tech Stack:** Python ≥3.10、官方 `mcp` SDK v2、SQLite FTS5、标准库 `unittest`。

**Spec:** `docs/superpowers/specs/2026-09-20-mcp-server-design.md`

## Global Constraints

- Python ≥ 3.10。
- MCP 依赖固定为 `mcp>=2,<3`（v2 为当前稳定线；`pip install mcp` 即 2.x）。
- 现有 CLI（`cs2wt`）行为与"零第三方依赖"保持不变；新依赖只服务 MCP。
- 仅 stdio 传输。
- 交流与 commit 信息使用中文。
- 测试用标准库 `unittest`，全部离线（不联网）。

---

### Task 1: 添加 mcp 依赖

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: 可 `import mcp`（SDK v2）的环境。

- [ ] **Step 1: 修改 `pyproject.toml` 的 `dependencies`**

```toml
dependencies = ["mcp>=2,<3"]
```

- [ ] **Step 2: 安装**

Run: `pip install -e .`
Expected: 成功安装 mcp 2.x

- [ ] **Step 3: 验证**

Run: `python -c "from mcp.server import MCPServer; print('mcp ok')"`
Expected: 输出 `mcp ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "构建：引入官方 mcp SDK v2 依赖"
```

---

### Task 2: section 提取

**Files:**
- Create: `src/cs2wt/sections.py`
- Test: `tests/test_sections.py`

**Interfaces:**
- Produces: `extract_section(markdown: str, section: str) -> str | None`

- [ ] **Step 1: 写失败测试 `tests/test_sections.py`**

```python
import unittest

from cs2wt.sections import extract_section

MD = """# Title

intro

## Alpha

alpha body

### Alpha Sub

sub body

## Beta

beta body
"""


class ExtractSectionTest(unittest.TestCase):
    def test_exact_heading_includes_subsections(self):
        out = extract_section(MD, "Alpha")
        self.assertIsNotNone(out)
        self.assertIn("alpha body", out)
        self.assertIn("### Alpha Sub", out)
        self.assertNotIn("beta body", out)

    def test_case_and_whitespace_insensitive(self):
        self.assertIsNotNone(extract_section(MD, "  beta "))

    def test_substring_match_fallback(self):
        self.assertIsNotNone(extract_section(MD, "Alph"))

    def test_missing_returns_none(self):
        self.assertIsNone(extract_section(MD, "Gamma"))

    def test_same_level_boundary(self):
        out = extract_section(MD, "Beta")
        self.assertIsNotNone(out)
        self.assertNotIn("alpha body", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_sections -v`
Expected: FAIL（`ModuleNotFoundError: cs2wt.sections`）

- [ ] **Step 3: 实现 `src/cs2wt/sections.py`**

```python
"""Extract a single section from converted Markdown."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def _headings(markdown: str) -> list[tuple[int, int, str]]:
    return [
        (m.start(), len(m.group(1)), m.group(2))
        for m in _HEADING.finditer(markdown)
    ]


def extract_section(markdown: str, section: str) -> str | None:
    """Return the section (heading + body + subsections), or None."""
    headings = _headings(markdown)
    if not headings:
        return None

    target = section.strip().lower()
    match: tuple[int, int] | None = None

    for start, level, text in headings:
        if text.strip().lower() == target:
            match = (start, level)
            break

    if match is None and target:
        for start, level, text in headings:
            if target in text.lower():
                match = (start, level)
                break

    if match is None:
        return None

    start, level = match
    end = len(markdown)
    for s, lvl, _ in headings:
        if s > start and lvl <= level:
            end = s
            break
    return markdown[start:end].strip()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_sections -v`
Expected: PASS（5 个用例）

- [ ] **Step 5: Commit**

```bash
git add src/cs2wt/sections.py tests/test_sections.py
git commit -m "功能：新增 Markdown 章节提取 extract_section"
```

---

### Task 3: DocIndex 支持 WAL 与跨线程

**Files:**
- Modify: `src/cs2wt/index.py`（`DocIndex.__init__`）
- Test: `tests/test_index_options.py`

**Interfaces:**
- Consumes: `DocIndex`
- Produces: `DocIndex(path, *, wal=False, check_same_thread=True)`

- [ ] **Step 1: 写失败测试 `tests/test_index_options.py`**

```python
import tempfile
import unittest
from pathlib import Path

from cs2wt.index import DocIndex


class DocIndexOptionsTest(unittest.TestCase):
    def test_wal_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "a.sqlite", wal=True)
            mode = idx.conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
            idx.close()

    def test_wal_default_off(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "b.sqlite")
            mode = idx.conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertNotEqual(mode.lower(), "wal")
            idx.close()

    def test_check_same_thread_false(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "c.sqlite", check_same_thread=False)
            self.assertEqual(idx.count(), 0)
            idx.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_index_options -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'wal'`）

- [ ] **Step 3: 修改 `DocIndex.__init__`（src/cs2wt/index.py）**

```python
    def __init__(
        self,
        path: str | Path,
        *,
        wal: bool = False,
        check_same_thread: bool = True,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        if wal:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_index_options -v`
Expected: PASS

- [ ] **Step 5: 回归现有测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/cs2wt/index.py tests/test_index_options.py
git commit -m "功能：DocIndex 支持 WAL 与跨线程连接选项"
```

---

### Task 4: 服务端配置

**Files:**
- Create: `src/cs2wt/mcp_config.py`
- Test: `tests/test_mcp_config.py`

**Interfaces:**
- Consumes: `DEFAULT_API`（`wiki`）、`DEFAULT_UA`（`http`）
- Produces:
  - `ServerConfig`（frozen dataclass：`data_dir, db, prefix, api, ua, cookie, delay, refresh`）
  - `ServerConfig.from_sources(argv=None, env=None) -> ServerConfig`

- [ ] **Step 1: 写失败测试 `tests/test_mcp_config.py`**

```python
import unittest
from pathlib import Path

from cs2wt.mcp_config import ServerConfig


class ServerConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = ServerConfig.from_sources([], env={})
        self.assertEqual(cfg.data_dir, Path("data"))
        self.assertEqual(cfg.db, Path("data") / "docs.sqlite")
        self.assertEqual(cfg.prefix, "Counter-Strike 2 Workshop Tools")
        self.assertTrue(cfg.refresh)

    def test_env_overrides_defaults(self):
        cfg = ServerConfig.from_sources(
            [], env={"CS2WT_DATA_DIR": "D", "CS2WT_DELAY": "2.5"}
        )
        self.assertEqual(cfg.data_dir, Path("D"))
        self.assertEqual(cfg.db, Path("D") / "docs.sqlite")
        self.assertEqual(cfg.delay, 2.5)

    def test_argv_overrides_env(self):
        cfg = ServerConfig.from_sources(
            ["--data-dir", "A", "--prefix", "P"], env={"CS2WT_DATA_DIR": "B"}
        )
        self.assertEqual(cfg.data_dir, Path("A"))
        self.assertEqual(cfg.prefix, "P")

    def test_no_refresh_flag_and_env(self):
        self.assertFalse(ServerConfig.from_sources(["--no-refresh"], env={}).refresh)
        self.assertFalse(
            ServerConfig.from_sources([], env={"CS2WT_NO_REFRESH": "1"}).refresh
        )

    def test_explicit_db(self):
        cfg = ServerConfig.from_sources(["--db", "x.sqlite"], env={})
        self.assertEqual(cfg.db, Path("x.sqlite"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_mcp_config -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `src/cs2wt/mcp_config.py`**

```python
"""Configuration for the MCP server (argv > environment > defaults)."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from .http import DEFAULT_UA
from .wiki import DEFAULT_API

DEFAULT_PREFIX = "Counter-Strike 2 Workshop Tools"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerConfig:
    data_dir: Path
    db: Path
    prefix: str
    api: str
    ua: str
    cookie: str
    delay: float
    refresh: bool

    @classmethod
    def from_sources(
        cls, argv: list[str] | None = None, env: dict | None = None
    ) -> "ServerConfig":
        env = dict(os.environ) if env is None else env
        parser = argparse.ArgumentParser(prog="cs2wt-mcp")
        parser.add_argument("--data-dir")
        parser.add_argument("--db")
        parser.add_argument("--prefix")
        parser.add_argument("--api")
        parser.add_argument("--ua")
        parser.add_argument("--cookie")
        parser.add_argument("--delay", type=float)
        parser.add_argument("--no-refresh", action="store_true")
        ns = parser.parse_args(argv)

        data_dir = ns.data_dir or env.get("CS2WT_DATA_DIR") or "data"
        db = ns.db or env.get("CS2WT_DB") or str(Path(data_dir) / "docs.sqlite")
        prefix = ns.prefix or env.get("CS2WT_PREFIX") or DEFAULT_PREFIX
        api = ns.api or env.get("CS2WT_API") or DEFAULT_API
        ua = ns.ua or env.get("CS2WT_UA") or DEFAULT_UA
        cookie = ns.cookie or env.get("CS2WT_COOKIE") or "cookies.txt"
        delay = (
            ns.delay if ns.delay is not None else float(env.get("CS2WT_DELAY", 1.0))
        )
        refresh = not ns.no_refresh and env.get("CS2WT_NO_REFRESH", "").lower() not in _TRUTHY

        return cls(
            data_dir=Path(data_dir),
            db=Path(db),
            prefix=prefix,
            api=api,
            ua=ua,
            cookie=cookie,
            delay=delay,
            refresh=refresh,
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_mcp_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cs2wt/mcp_config.py tests/test_mcp_config.py
git commit -m "功能：MCP 服务端配置解析（参数 / 环境变量 / 默认）"
```

---

### Task 5: IndexManager

**Files:**
- Create: `src/cs2wt/mcp_manager.py`
- Test: `tests/test_mcp_manager.py`

**Interfaces:**
- Consumes: `ServerConfig`、`DocIndex`、`sync`、`crawl`、`build_index`、`AnubisSession`、`WikiClient`
- Produces:
  - `IndexManager(config, *, refresher=None)`
  - 方法：`start()`、`join(timeout)`、`state`、`error`、`search(query, limit=10)`、`get(key)`、`list_titles()`、`info()`、`close()`
  - 状态常量：`INITIALIZING` / `REFRESHING` / `READY` / `ERROR`
  - `default_refresh(config, has_index: bool) -> None`
  - `refresher` 签名：`Callable[[ServerConfig, bool], None]`

- [ ] **Step 1: 写失败测试 `tests/test_mcp_manager.py`**

```python
import tempfile
import threading
import unittest
from pathlib import Path

from cs2wt.mcp_config import ServerConfig
from cs2wt.mcp_manager import IndexManager


def make_config(tmp: str, refresh: bool) -> ServerConfig:
    return ServerConfig(
        data_dir=Path(tmp),
        db=Path(tmp) / "docs.sqlite",
        prefix="P",
        api="http://example/api.php",
        ua="UA",
        cookie=str(Path(tmp) / "cookies.txt"),
        delay=0.0,
        refresh=refresh,
    )


class IndexManagerTest(unittest.TestCase):
    def test_no_refresh_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d, refresh=False))
            mgr.start()
            self.assertEqual(mgr.state, "READY")
            self.assertEqual(mgr.search("x"), [])
            mgr.close()

    def test_refresh_success_sets_ready(self):
        with tempfile.TemporaryDirectory() as d:
            done = threading.Event()

            def fake_refresh(config, has_index):
                done.set()

            mgr = IndexManager(make_config(d, refresh=True), refresher=fake_refresh)
            mgr.start()
            self.assertTrue(done.wait(5))
            mgr.join(5)
            self.assertEqual(mgr.state, "READY")
            mgr.close()

    def test_refresh_failure_sets_error(self):
        with tempfile.TemporaryDirectory() as d:
            def boom(config, has_index):
                raise RuntimeError("network down")

            mgr = IndexManager(make_config(d, refresh=True), refresher=boom)
            mgr.start()
            mgr.join(5)
            self.assertEqual(mgr.state, "ERROR")
            self.assertIn("network down", mgr.error)
            mgr.close()

    def test_info_shape(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d, refresh=False))
            mgr.start()
            info = mgr.info()
            self.assertIn("state", info)
            self.assertIn("count", info)
            mgr.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_mcp_manager -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `src/cs2wt/mcp_manager.py`**

```python
"""Index lifecycle for the MCP server.

The reader is shared across handler threads; the background refresher uses
its own connection.  WAL keeps the two from blocking each other.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .fetch import crawl
from .http import AnubisSession
from .index import DocIndex, build_index
from .mcp_config import ServerConfig
from .sync import sync
from .wiki import WikiClient

INITIALIZING = "INITIALIZING"
REFRESHING = "REFRESHING"
READY = "READY"
ERROR = "ERROR"


def _indexed_count(db: Path) -> int:
    if not Path(db).exists():
        return 0
    try:
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT count(*) FROM docs").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _new_client(config: ServerConfig) -> WikiClient:
    session = AnubisSession(
        user_agent=config.ua, cookie_path=config.cookie, delay=config.delay
    )
    return WikiClient(session, api_url=config.api)


def default_refresh(config: ServerConfig, has_index: bool) -> None:
    """Full crawl when there is no index, incremental sync otherwise."""
    client = _new_client(config)
    if has_index:
        sync(
            client,
            prefix=config.prefix,
            data_dir=config.data_dir,
            db_path=config.db,
        )
        return
    crawl(client, prefix=config.prefix, out_dir=config.data_dir)
    index = build_index(config.data_dir, config.db)
    index.close()


class IndexManager:
    def __init__(self, config: ServerConfig, *, refresher=None) -> None:
        self.config = config
        self._refresher = refresher or default_refresh
        self._lock = threading.Lock()
        self._state = READY
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self._reader: DocIndex | None = None
        if Path(config.db).exists():
            self._reader = DocIndex(config.db, wal=True, check_same_thread=False)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if not self.config.refresh:
            return
        has_index = _indexed_count(self.config.db) > 0
        self._state = REFRESHING if has_index else INITIALIZING
        self._thread = threading.Thread(target=self._refresh, daemon=True)
        self._thread.start()

    def _refresh(self) -> None:
        try:
            has_index = _indexed_count(self.config.db) > 0
            self._refresher(self.config, has_index)
            self._state = READY
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            self._error = f"{type(exc).__name__}: {exc}"
            self._state = ERROR
        finally:
            self._reopen_reader()

    def _reopen_reader(self) -> None:
        with self._lock:
            if not Path(self.config.db).exists():
                return
            if self._reader is not None:
                self._reader.close()
            self._reader = DocIndex(
                self.config.db, wal=True, check_same_thread=False
            )

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def close(self) -> None:
        with self._lock:
            if self._reader is not None:
                self._reader.close()
                self._reader = None

    # -- status ------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    def info(self) -> dict:
        count = 0
        with self._lock:
            if self._reader is not None:
                count = self._reader.count()
        return {
            "state": self._state,
            "error": self._error,
            "count": count,
            "prefix": self.config.prefix,
        }

    # -- reads -------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[dict]:
        with self._lock:
            if self._reader is None:
                return []
            return self._reader.search(query, limit)

    def get(self, key: str) -> dict | None:
        with self._lock:
            if self._reader is None:
                return None
            if key.isdigit():
                return self._reader.get(int(key))
            return self._reader.get_by_title(key)

    def list_titles(self) -> list[tuple[int, str]]:
        with self._lock:
            if self._reader is None:
                return []
            return self._reader.list_titles()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_mcp_manager -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cs2wt/mcp_manager.py tests/test_mcp_manager.py
git commit -m "功能：IndexManager 索引生命周期与后台刷新"
```

---

### Task 6: 工具函数

**Files:**
- Create: `src/cs2wt/mcp_tools.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `extract_section`
- Produces:
  - `tool_search_docs(manager, query, limit=10) -> str`
  - `tool_get_page(manager, id_or_title, section=None) -> str`
  - `tool_list_pages(manager) -> str`
  - 每个返回 JSON 字符串。

- [ ] **Step 1: 写失败测试 `tests/test_mcp_tools.py`**

```python
import json
import unittest

from cs2wt.mcp_tools import tool_get_page, tool_list_pages, tool_search_docs


class FakeManager:
    def __init__(self):
        self.pages = {
            "Doc": {
                "pageid": 1,
                "title": "Doc",
                "url": "u",
                "revid": 2,
                "timestamp": "t",
                "content": "# Top\n\nintro\n\n## Alpha\n\nalpha body\n",
            }
        }

    def search(self, query, limit=10):
        return [{"pageid": 1, "title": "Doc", "url": "u", "snippet": "s", "score": 1.0}]

    def get(self, key):
        return self.pages.get(key)

    def list_titles(self):
        return [(1, "Doc")]


class ToolsTest(unittest.TestCase):
    def test_search(self):
        data = json.loads(tool_search_docs(FakeManager(), "x"))
        self.assertEqual(data["count"], 1)

    def test_get_full_page(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc"))
        self.assertTrue(data["found"])
        self.assertIn("alpha body", data["content"])

    def test_get_section(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc", section="Alpha"))
        self.assertTrue(data["found"])
        self.assertIn("alpha body", data["content"])
        self.assertNotIn("intro", data["content"])

    def test_get_missing_page(self):
        data = json.loads(tool_get_page(FakeManager(), "Nope"))
        self.assertFalse(data["found"])

    def test_get_missing_section(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc", section="Nope"))
        self.assertFalse(data["found"])

    def test_list(self):
        data = json.loads(tool_list_pages(FakeManager()))
        self.assertEqual(data["count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_mcp_tools -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `src/cs2wt/mcp_tools.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_mcp_tools -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cs2wt/mcp_tools.py tests/test_mcp_tools.py
git commit -m "功能：MCP 工具函数（search / get / list）"
```

---

### Task 7: MCP server 装配

**Files:**
- Create: `src/cs2wt/mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ServerConfig`、`IndexManager`、工具函数、`mcp.server.MCPServer`、`mcp.Client`
- Produces:
  - `INSTRUCTIONS: str`
  - `build_server(manager: IndexManager) -> MCPServer`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 写失败测试 `tests/test_mcp_server.py`（内存 Client，不联网）**

```python
import tempfile
import unittest
from pathlib import Path

import anyio
from mcp import Client

from cs2wt.mcp_config import ServerConfig
from cs2wt.mcp_manager import IndexManager
from cs2wt.mcp_server import build_server


def make_config(tmp: str) -> ServerConfig:
    return ServerConfig(
        data_dir=Path(tmp),
        db=Path(tmp) / "docs.sqlite",
        prefix="P",
        api="http://example/api.php",
        ua="UA",
        cookie=str(Path(tmp) / "cookies.txt"),
        delay=0.0,
        refresh=False,
    )


class ServerTest(unittest.TestCase):
    def test_tools_registered(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d))
            mgr.start()
            server = build_server(mgr)

            async def go():
                async with Client(server) as client:
                    listed = await client.list_tools()
                    return {t.name for t in listed.tools}

            names = anyio.run(go)
            self.assertEqual(names, {"search_docs", "get_page", "list_pages"})
            mgr.close()

    def test_call_list_pages_empty_index(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d))
            mgr.start()
            server = build_server(mgr)

            async def go():
                async with Client(server) as client:
                    return await client.call_tool("list_pages", {})

            result = anyio.run(go)
            self.assertIn('"count": 0', result.content[0].text)
            mgr.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_mcp_server -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `src/cs2wt/mcp_server.py`**

```python
"""MCP server exposing the offline documentation index over stdio."""

from __future__ import annotations

from mcp.server import MCPServer

from .mcp_config import ServerConfig
from .mcp_manager import IndexManager
from .mcp_tools import tool_get_page, tool_list_pages, tool_search_docs

INSTRUCTIONS = (
    "本服务提供 Counter-Strike 2 Workshop Tools 官方文档（Valve Developer Community）"
    "的离线全文检索。先用 search_docs 按关键词定位页面，再用 get_page 精读；"
    "已知确切页面标题或 pageid 时可直接 get_page。数据在服务启动时于后台自动更新，"
    "无需手动触发。仅回答与该工具集文档相关的问题。"
)


def build_server(manager: IndexManager) -> MCPServer:
    mcp = MCPServer("cs2wt-docs", instructions=INSTRUCTIONS)

    @mcp.tool()
    def search_docs(query: str, limit: int = 10) -> str:
        """按关键词检索 Counter-Strike 2 Workshop Tools 官方文档的离线全文索引。

        何时使用：需要查找 CS2 Workshop Tools 文档中的术语、命令、概念、实体时；
        回答任何涉及该工具集用法的技术问题前，应先用本工具定位来源页面。
        何时不使用：已知道确切页面标题或 pageid 时，直接调用 get_page 更高效；
        与 CS2 Workshop Tools 文档无关的问题不要使用。
        返回：JSON，含 count 与 results（每项含 pageid、title、url、snippet、score；
        score 为 bm25，越小越相关）。
        """
        return tool_search_docs(manager, query, limit)

    @mcp.tool()
    def get_page(id_or_title: str, section: str | None = None) -> str:
        """读取某个文档页面的正文，可按章节只取一部分。

        何时使用：已知页面标题或 pageid，需要阅读其内容；或只想读取某章节以控制返回体积。
        何时不使用：只知道模糊关键词时，先用 search_docs 定位。
        参数：id_or_title 为纯数字时按 pageid 查询，否则按页面标题查询；
        section 为可选的章节标题（不区分大小写，支持部分匹配）。
        返回：JSON，含 found、pageid、title、url、revid、timestamp、content；
        未找到页面或章节时 found 为 false。
        """
        return tool_get_page(manager, id_or_title, section)

    @mcp.tool()
    def list_pages() -> str:
        """列出当前索引收录的全部文档页面。

        何时使用：需要了解文档覆盖范围、列举全部页面，或确认某主题是否被收录。
        何时不使用：已有明确查询词时，用 search_docs 更合适。
        返回：JSON，含 count 与 pages（每项含 pageid、title）。
        """
        return tool_list_pages(manager)

    return mcp


def main(argv: list[str] | None = None) -> int:
    config = ServerConfig.from_sources(argv)
    manager = IndexManager(config)
    manager.start()
    try:
        build_server(manager).run()
    finally:
        manager.close()
    return 0
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m unittest tests.test_mcp_server -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cs2wt/mcp_server.py tests/test_mcp_server.py
git commit -m "功能：MCP 服务端装配（MCPServer + 工具 + 触发条件描述）"
```

---

### Task 8: 入口与文档

**Files:**
- Modify: `pyproject.toml`（`[project.scripts]`）
- Modify: `README.md`

**Interfaces:**
- Produces: `cs2wt-mcp` 可执行入口；README 的 MCP 用法章节。

- [ ] **Step 1: 在 `pyproject.toml` 的 `[project.scripts]` 增加入口**

```toml
cs2wt-mcp = "cs2wt.mcp_server:main"
```

- [ ] **Step 2: 重新安装并验证入口**

Run: `pip install -e .`
Run: `python -c "import importlib.metadata as m; print([e.name for e in m.entry_points(group='console_scripts') if e.name=='cs2wt-mcp'])"`
Expected: 输出 `['cs2wt-mcp']`

- [ ] **Step 3: README 增加"MCP 服务端"章节**

在 README 的 CLI 用法之后追加：

````markdown
## MCP 服务端

除 CLI 外，本项目提供一个 MCP 服务端，把离线索引通过 stdio 暴露给 AI 助手。

```bash
pip install -e .
cs2wt-mcp            # 以 stdio 启动
```

环境变量（均有默认值）：`CS2WT_DATA_DIR`、`CS2WT_DB`、`CS2WT_PREFIX`、
`CS2WT_API`、`CS2WT_UA`、`CS2WT_COOKIE`、`CS2WT_DELAY`、`CS2WT_NO_REFRESH`。

启动后服务端立即就绪，并在后台执行一次刷新：本地无索引时自动全量抓取并建索引，
已有索引时做增量同步。设置 `CS2WT_NO_REFRESH=1`（或 `--no-refresh`）可跳过刷新。

暴露的工具：

- `search_docs(query, limit)`：全文检索，返回命中页面与片段。
- `get_page(id_or_title, section)`：读取页面正文，可按章节截取。
- `list_pages()`：列出全部收录页面。
````

- [ ] **Step 4: 全量测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md
git commit -m "文档：新增 cs2wt-mcp 入口与 MCP 用法说明"
```

---

## Spec 覆盖对照

| Spec 章节 | 实现任务 |
|---|---|
| §4 架构 / 模块与入口 | Task 4-8 |
| §5 启动与刷新状态机 | Task 5 |
| §6 工具定义与触发条件 | Task 6、Task 7 |
| §7 Section 提取 | Task 2 |
| §8 并发与 WAL | Task 3、Task 5 |
| §9 配置 | Task 4 |
| §10 错误处理 | Task 5（状态机）、Task 6（未找到分支） |
| §11 测试 | 每个任务的测试步骤 |
| §12 依赖与打包 | Task 1、Task 8 |
| §13 非目标 | 未引入相关功能 |