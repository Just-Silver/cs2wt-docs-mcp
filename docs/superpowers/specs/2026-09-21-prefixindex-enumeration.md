# 枚举改为 PrefixIndex + 主键改为 URL 标题

## 1. 背景（实测证据）

原设计的枚举是「链接 BFS + `link.startswith(prefix)` 过滤」，有两个硬伤：

1. **孤儿页永远抓不到**：没有任何可到达页链接它。对照旧 API `list=allpages` 的 41 条，
   新 HTML 抓取只得到 30 条，实测漏掉 6 篇真实文章（均返回 200）：
   `.../Animgraph`、`.../Issues`、`.../Reference`、`.../Source Filmmaker`、
   `.../Unofficial Tools`、`.../Level Design/Adding Water`。
2. **跨父级 / 无前缀链接被丢弃**：根页真实链接里有 `Source Filmmaker/Docs`、
   `Map (level design)`、`Models`、`Particle System Overview`、`SDK Docs` 等不带前缀的链接。

另外，`fetch_page` 用页面 `<h1>` 的**显示标题**当主键，导致：

- 同一 URL 树里多个标题显示成同一个 h1（`.../Scripting API` 重定向页与 `.../Scripting/API`
  正文页 h1 都是 "Scripting API"）→ manifest 出现重复记录；
- 显示标题变化会让键漂移。

## 2. 决策（用户已定）

- **枚举改用 `/wiki/Special:PrefixIndex/<前缀>`**：一次请求拿到该前缀下全部页面，
  等价于旧的 `list=allpages`，彻底消除漏页。
- **主键改用 URL 标题**（如 `Counter-Strike 2 Workshop Tools/Scripting/API`）：
  唯一、稳定、与页面地址一致。
- **重定向页跳过不产出**（其正文在 canonical 目标页）。

## 3. 合规

robots.txt（实测）仅禁：`/w/api.php*`、`/w/Special:*`、`/*?*title=Special:*`、
`/*?*action=history`。`/wiki/Special:PrefixIndex/<prefix>` 是**干净路径、未被禁**。

`http.assert_allowed_url` 放宽为：**仅额外放行** `/wiki/Special:PrefixIndex/` 前缀；
其余 `Special:`、任何 query/fragment、`/w/`、`/w/api.php` 仍禁。

## 4. 重定向识别

重定向页（HTTP 200 的渲染页）含 `<span class="mw-redirectedfrom">(Redirected from …)</span>`
且带 `<link rel="canonical" href="<目标 URL>">`。据此判定：HTML 含 `mw-redirectedfrom`
即为重定向。实测：`.../Scripting API`、`.../Source Filmmaker` 是重定向；
`.../Scripting/API` 不是。

## 5. 设计

### 5.1 `htmlparse.py`

- 新增 `is_redirect(html) -> bool`：`"mw-redirectedfrom" in html`。

### 5.2 `http.py`

- `assert_allowed_url`：在 `Special:` 拦截之前，放行
  `parts.path.startswith("/wiki/Special:PrefixIndex/")`。

### 5.3 `wiki.py`

- `PageContent` 新增字段 `is_redirect: bool = False`。
- `fetch_page(title)`：
  - `PageContent.title = title`（**请求的 URL 标题**，不再用 h1）；
  - `is_redirect = htmlparse.is_redirect(html)`；
  - `revid` / `timestamp` 仍来自 `extract_meta`；404 → `None`。
- 新增 `list_titles(prefix) -> list[str]`：GET PrefixIndex 页，
  `extract_links` 后按 `startswith(prefix)` 过滤（去重、保持顺序）。
- 重写 `iter_pages(prefix, seeds=(), known=None, failed=None)`：
  - 不再做链接 BFS；改为遍历 `list_titles(prefix)`；
  - `seeds` 仍先访问（用于兼容旧 manifest / 迁移），随后是枚举结果；
  - 对每个标题：命中 `known` 缓存则复用；否则 `fetch_page`；
    异常 → 记 `failed`；`None`（404）或 `is_redirect` → 跳过；否则 `yield`。

### 5.4 `fetch.py`

- `crawl` 逻辑基本不变（仍走 `iter_pages`）；`seen` 去重保留（防御）。
- 记录里的 `title` 现在是 URL 标题。

### 5.5 `sync.py`

- 删除「`page.title != title` 视为移动」的分支（主键已稳定为 URL 标题）。
- 已有页循环：`None`（404）**或 `page.is_redirect`** → 记为 removed；否则比 revid。
- 新页发现：改用 `iter_pages`（内部即 PrefixIndex 枚举），`page.title not in local` → added。
- 其余（写 raw、upsert、自愈、meta）不变。

### 5.6 影响面

- MCP 的 `get_page` / `search` 返回的 `title` 变为 URL 标题；`url` 仍由 `page_url(title)` 生成，
  与标题一致。
- 索引 `title` 为主键，语义不变，但取值变为 URL 标题。

## 6. 已知限制

- PrefixIndex 超过单页上限（约 1000 条）时会分页，其「下一页」链接带 `?from=` query，
  被守卫禁止。当前语料 41 条，远未触及；若将来逼近上限，需另行设计（如按首字母分段）。

## 7. 测试（离线）

- `htmlparse`：`is_redirect` 正/负例。
- `http_guard`：`/wiki/Special:PrefixIndex/X` 放行；`/wiki/Special:AllPages`、
  `/w/Special:`、带 query 仍抛。
- `wiki`：`fetch_page` 返回请求标题（非 h1）；`is_redirect` 透传；
  `list_titles` 从假 PrefixIndex 页提取并按前缀过滤；
  `iter_pages` 跳过重定向与 404、记 failed。
- `fetch`：crawl 用假 client 的 `iter_pages`（标题为 URL 标题）写 manifest。
- `sync`：重定向页判为 removed；新页 added；revid 变化 updated；自愈不变。
- `cli` / `index` / MCP：改用 URL 标题的断言更新。

## 8. 后续

- 修好后重跑 CI，重新生成 `data-latest`，并用 MCP 端到端冒烟确认页数从 30 → 37 篇正文。