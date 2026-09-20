# 实现计划：PrefixIndex 枚举 + URL 标题主键

对应规格：`docs/superpowers/specs/2026-09-21-prefixindex-enumeration.md`

## 约定

- 全程 TDD；测试全离线（HTTP 用假 session / 假 client 注入）。
- 代码注释 / docstring 用英文；用户可见文档与 commit 用中文。
- 全量测试：`python -m unittest discover -s tests -v`（基线 94 tests OK）。

---

## Task 1 — `htmlparse.is_redirect`

**产出**：改 `src/cs2wt/htmlparse.py`、`tests/test_htmlparse.py`

- 新增 `is_redirect(html: str) -> bool`：`return "mw-redirectedfrom" in html`。
- 测试：含 `mw-redirectedfrom` → True；普通页 → False。

**验收**：`python -m unittest discover -s tests -p "test_htmlparse.py" -v`

---

## Task 2 — 守卫放行 PrefixIndex

**产出**：改 `src/cs2wt/http.py`、`tests/test_http_guard.py`

- `assert_allowed_url`：在 `Special:` 拦截前放行 `parts.path.startswith("/wiki/Special:PrefixIndex/")`。
- 测试：`/wiki/Special:PrefixIndex/Counter-Strike_2_Workshop_Tools` 通过；
  `/wiki/Special:AllPages`、`/wiki/Special:Random`、`/w/Special:X`、
  `/wiki/Special:PrefixIndex/X?from=Y`（带 query）一律抛。

**验收**：`python -m unittest discover -s tests -p "test_http_guard.py" -v`

---

## Task 3 — `wiki.py`：枚举与主键（核心）

**产出**：改 `src/cs2wt/wiki.py`、`tests/test_wiki.py`

- `PageContent` 加 `is_redirect: bool = False`。
- `fetch_page(title)`：
  - `PageContent(title=title, revid=..., timestamp=..., html=html, is_redirect=is_redirect(html))`；
    不再用 `extract_meta` 的 h1 当标题。
  - 404 → `None`；瞬态失败重试逻辑不变。
- 新增 `list_titles(prefix) -> list[str]`：
  - GET `f"{base_url}/wiki/Special:PrefixIndex/" + quote(prefix.replace(" ", "_"), safe="/")`；
  - `extract_links(html)` 后保留 `startswith(prefix)` 的标题（顺序去重）。
- 重写 `iter_pages(prefix, seeds=(), known=None, failed=None)`：
  - `known = {} if known is None else known`；
  - 候选顺序：`[*seeds, *list_titles(prefix)]`，按标题去重（保持首次出现顺序）；
  - 每个标题：命中 `known` 则 `page = known[title]`；否则 `fetch_page`（异常 → `failed.append` 并跳过）；
  - `page is None` 或 `page.is_redirect` → 跳过；否则 `known[title] = page` 并 `yield page`。

**测试**（用假 session 返回构造好的 HTML；沿用现有 fake 写法）

- `fetch_page` 返回的 `title` 等于请求标题（即使 h1 不同）。
- `fetch_page` 对含 `mw-redirectedfrom` 的页返回 `is_redirect=True`。
- `list_titles`：假 PrefixIndex 页含若干前缀内/前缀外链接 → 只返回前缀内、去重、保序。
- `iter_pages`：跳过 404 与重定向；把抛异常的标题记入 `failed`；`seeds` 先于枚举；
  `known` 缓存命中不重复 fetch。

**验收**：`python -m unittest discover -s tests -p "test_wiki.py" -v`

---

## Task 4 — `fetch.py`

**产出**：改 `src/cs2wt/fetch.py`（如需）、`tests/test_fetch.py`

- `crawl` 逻辑保持；确认用 URL 标题写 manifest；保留 `seen` 去重。
- 测试：假 client 的 `iter_pages` 产出 URL 标题；manifest `title` 为 URL 标题；
  重复标题只记一条；失败页保留旧记录的逻辑不变。

**验收**：`python -m unittest discover -s tests -p "test_fetch.py" -v`

---

## Task 5 — `sync.py`

**产出**：改 `src/cs2wt/sync.py`、`tests/test_sync.py`

- 删除 `page.title != title` 的移动分支。
- 已有页：`page is None`（404）或 `page.is_redirect` → `report.removed`；否则比 revid。
- 新页：`iter_pages(prefix, seeds=list(local), known=cache, failed=report.failed)`；
  `page.title not in local` → `report.added`。
- 其余（写 raw、`index.upsert`、删除、自愈、meta）不变。
- 测试：重定向判 removed；404 判 removed；revid 变化 updated；新增 added；
  瞬态失败保留记录并计入 failed；自愈补 upsert 仍工作。

**验收**：`python -m unittest discover -s tests -p "test_sync.py" -v`

---

## Task 6 — 其余测试与文档

**产出**：`tests/test_cli.py`、`tests/test_index*.py`、`tests/test_mcp_*.py`（按需）、`README.md`、`AGENTS.md`

- 受主键语义影响的断言改为 URL 标题。
- README：说明枚举走 PrefixIndex、主键为 URL 标题、重定向跳过。
- AGENTS.md：更新「抓取只走 HTML 通道」一条，补 PrefixIndex 与合规边界。

**验收**：`python -m unittest discover -s tests -v` 全绿。

---

## Task 7 — 端到端

- 推送 `main`，`workflow_dispatch` 触发 CI，确认 `data-latest` 的 manifest 为 37 篇正文
  （无重定向、无重复）。
- 用 MCP 端到端冒烟（临时数据目录）确认 `count` 与检索正常。

## 依赖顺序

T1、T2 可并行；T3 依赖 T1；T4、T5 依赖 T3；T6 依赖 T4/T5；T7 最后。