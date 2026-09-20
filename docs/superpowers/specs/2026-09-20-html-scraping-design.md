# HTML 抓取通道设计（robots.txt 合规）

- 日期：2026-09-20
- 状态：待实现
- 关联：`src/cs2wt/{http,wiki,fetch,sync,store,convert,index,cli}.py`；同目录 MCP 服务端设计
  （`2026-09-20-mcp-server-design.md`，其 `pageid` 字段受本设计影响）

## 1. 背景

### 1.1 项目现状

本项目是一套离线索引工具链（`cs2wt` CLI + 规划中的 MCP 服务端）：抓取 Valve Developer
Community（VDC）上 `Counter-Strike 2 Workshop Tools` 及其子页的文档，转换为 Markdown，
写入单文件 SQLite FTS5 索引，支持全量抓取（`fetch`）与增量同步（`sync`）。

当前抓取层 `src/cs2wt/wiki.py` 使用 **MediaWiki Action API**：

```
DEFAULT_API = "https://developer.valvesoftware.com/w/api.php"
```

并用 `list=allpages` 枚举、`generator=allpages&prop=revisions` 变更检测、
`prop=revisions&rvprop=…|content` 批量取内容（20 页/请求）。

### 1.2 问题：当前抓取违反 VDC 的 robots.txt

VDC 的 `https://developer.valvesoftware.com/robots.txt` 全文：

```
User-agent: *
Disallow: /w/api.php*
Disallow: /w/Special:*
Disallow: /*?*title=Special:*
Disallow: /*?*action=history
User-agent: AhrefsBot
Crawl-Delay: 60
```

`DEFAULT_API` 的路径 `/w/api.php` **正好命中第一条 `Disallow`**。README 声称"遵守
robots.txt"，与实现不符。

补充事实（已实测）：

- 站点由 **Anubis**（SHA-256 工作量证明反爬代理）保护，`/wiki/` 页面与 API 一样会被挑战，
  `AnubisSession` 已能自动求解并持久化 cookie，本设计**沿用**。
- 站点**没有** `sitemap.xml`（`/sitemap.xml` 返回 404），也没有可用的 `sitemap_index.xml`。
- GitHub 上现有的 VDC 相关项目（`TF2-Addons/tf2-cvar-scraper`、`crowbardoctor/Valve_developer_Wiki_Offline`
  等）都走 `/wiki/` HTML，均不违反 robots.txt。

### 1.3 为什么选择 HTML 通道

- 只请求 `/wiki/<标题>`（ArticlePath）即可**完全不匹配任何 Disallow 规则**（见 §3）。
- 与现有 VDC 项目的通行做法一致，合规上最稳妥。
- 备选方案 `Special:Export`（`/wiki/Special:Export/<title>`）虽然按字面也不在禁止列表，
  但它仍是一个 `Special:` 页面，与"保证不违反"的诉求相冲突，**本设计不采用**。

### 1.4 已实测的 HTML 结构

以真实快照（`crowbardoctor` 仓库中的 `Assault` 页面，26 KB）为例，MediaWiki 渲染页
提供了稳定、可解析的结构：

```html
<h1 id="firstHeading" class="firstHeading" lang="en">Assault</h1>   <!-- 标题 -->
<div id="bodyContent" class="mw-body-content">
  <div id="mw-content-text" class="mw-body-content mw-content-ltr">…</div>  <!-- 正文 -->
</div>
<span class="mw-headline">…</span>                                  <!-- 小节标题 -->
<div id="toc">…</div>                                               <!-- 目录 -->

<a href="/w/index.php?title=Assault&amp;oldid=218612">Permanent link</a>  <!-- revid -->
<li>This page was last modified on 5 September 2018, at 02:16.</li>      <!-- 时间戳 -->
```

同页含 **35 个 `/wiki/…` 内部链接**（如 `/wiki/Path_corner`、`/wiki/Ai_goal_assault`），
可作为枚举来源。

**HTML 拿不到 `pageid`**（无 `curid`），这是本设计最主要的破坏性影响（见 §7）。

## 2. 目标与非目标

### 目标

1. 抓取层只访问 robots.txt 允许的路径，并由**代码硬约束**保证（§3），而非仅靠约定。
2. 保持现有对外能力：检索、读取、列表、全量抓取、增量同步。
3. 保持"raw 是 source of truth、索引可随时重建"的设计原则。

### 非目标（YAGNI）

- 不使用 `api.php`、不使用任何 `Special:` 页面、不使用任何 query 参数。
- 不抓取图片/附件/多媒体。
- 不改动 MCP 工具语义（唯一例外：标识符由 `pageid` 改为 `title`，见 §7.5）。
- 不做 wikitext 保真（HTML 已是渲染结果，模板已展开，属已知取舍）。

## 3. robots.txt 合规契约（核心）

**唯一允许的请求形态**：

| 约束 | 值 |
|---|---|
| scheme + host | `https://developer.valvesoftware.com` |
| path | 必须以 `/wiki/` 开头 |
| query / fragment | 必须为空 |
| path 内容 | 不得包含 `/w/`，不得包含 `Special:` |
| method | 仅 `GET` |

**实现**：在 HTTP 层新增守卫 `assert_allowed_url(url)`，在**每次请求前**校验，违规抛
`ValueError`（或专用异常），使违规请求在发出前即被拦截。

**合规证明**：四条 `Disallow` 规则均为路径/查询匹配：

- `/w/api.php*`：要求路径以 `/w/` 开头 → `/wiki/…` 不匹配。
- `/w/Special:*`：要求路径以 `/w/` 开头 → 不匹配。
- `/*?*title=Special:*`：要求存在 query 且含 `title=Special:` → 契约禁止 query → 不匹配。
- `/*?*action=history`：要求存在 query 且含 `action=history` → 契约禁止 query → 不匹配。

因此 `/wiki/<标题>` 形态**不匹配任何一条**。守卫把该结论固化为运行时不变式，并有单测（§12）。

## 4. 架构

### 4.1 模块调整

| 模块 | 变化 |
|---|---|
| `http.py` | 新增 `assert_allowed_url()`；其余不变（Anubis PoW、限速、cookie、稳定 UA） |
| `wiki.py` | `WikiClient`（Action API）替换为 `HtmlClient`：`iter_pages()`（链接枚举）、`fetch_page(title)`（抓取并解析单页） |
| `htmlparse.py`（新增） | `extract_meta()`、`extract_links()`、`html_to_markdown()` |
| `convert.py` | **删除**；其 wikitext→Markdown 职责由 `htmlparse.html_to_markdown()` 取代，调用点（`index.py`、`sync.py`）改为 `from .htmlparse import html_to_markdown` |
| `store.py` | 键由 `pageid` 改为 `title`；raw 文件后缀由 `.wiki` 改为 `.html` |
| `fetch.py` | 改用 `HtmlClient` 枚举 + 抓取 |
| `sync.py` | 改用 `HtmlClient` 枚举 + `revid` 比对 |
| `index.py` | FTS 表去掉 `pageid`，改为 `title` 键 |
| `cli.py` | 去掉 `--api`；`list` 输出去掉 pageid |

引用 `pageid` 的现有文件（均需改动）：`wiki.py`(4)、`index.py`(16)、`sync.py`(8)、
`store.py`(4)、`fetch.py`(3)、`cli.py`(2)，以及测试 `tests/test_sync.py`(4)。

### 4.2 数据流

```
HtmlClient.iter_pages()
  └─ 枚举：从根页面 BFS /wiki/ 链接，按前缀过滤（种子见 §5）
HtmlClient.fetch_page(title)
  ├─ GET https://developer.valvesoftware.com/wiki/<title>
  ├─ htmlparse.extract_meta()   → title / revid / timestamp
  ├─ raw/<slug>.html 落盘        （source of truth）
  └─ htmlparse.html_to_markdown() → DocIndex.upsert(title=…, …)
```

## 5. 枚举（替代 `list=allpages` / `generator=allpages`）

因站点无 sitemap，采用**链接爬取**：

1. 种子集合：
   - 根页面 `Counter-Strike 2 Workshop Tools`；
   - 若本地已有 `manifest.json`，并入其全部 `title`（保证迁移时不漏已有页）。
2. BFS：对队列中每个 title，抓取其 `/wiki/` 页面，抽取所有 `/wiki/…` 链接（见 §6.2），
   归一化为 title，保留 `title.startswith(prefix)` 者，未访问过的入队。
3. 已访问集合去重；每个 title 只抓一次。

**约束**：只解析 `<a href="/wiki/…">`；对链接**只取其 path、丢弃 query/fragment**，
再重新构造干净的 `/wiki/<title>` URL 去请求（绝不请求原始带 query 的 href）。

**已知局限**：只能发现"被链接可达"的页面。本文档树为父子结构（根页面链接各主题页，
主题页链接子页），风险低。若未来出现无入链的孤儿页，再单独处理（非目标）。

## 6. HTML 解析（`htmlparse.py`，零依赖）

全部基于标准库 `html.parser.HTMLParser`。

### 6.1 元数据提取 `extract_meta(html) -> {title, revid, timestamp}`

- **title**：`<h1 id="firstHeading">` 的文本（HTML 实体解码后去首尾空白）。
- **revid**：`<a href="/w/index.php?title=…&oldid=NNN">` 中的 `oldid`（**只解析，不请求**）。
- **timestamp**：页脚 `This page was last modified on <D> <Month> <Y>, at <HH>:<MM>.`
  解析为 ISO8601（月份名映射英文→数字）。
- **缺省**：`revid` 缺失 → 视为"已变更"（保守）；`timestamp` 缺失 → 空串。
- **时区说明**：HTML 页脚时间无时区标记（站点本地时间），仅作展示用途；增量同步以 `revid`
  为准，不依赖 timestamp，故不做时区换算。

### 6.2 链接提取 `extract_links(html) -> list[title]`

- 取所有 `<a href>` 中 `path.startswith("/wiki/")` 者。
- 丢弃：含 `Special:`、`/w/`、外部域名、`#`、以及非目标命名空间（`File:`/`Category:`/
  `Template:`/`Help:`/`Valve_Developer_Community:` 等，最终由前缀过滤兜底）。
- 归一化：`unquote(path[len("/wiki/"):]).replace("_", " ")`，去掉 query/fragment。
- 去重。

### 6.3 HTML → Markdown `html_to_markdown(html) -> str`

- **内容范围**：优先 `<div id="mw-content-text">`，否则 `<div class="mw-parser-output">`，
  再否则 `<body>`；用配对计数截取该容器。
- **丢弃**：`script`、`style`、`#toc`、`.mw-editsection`、`sup.reference`、`.navbox`、
  `.metadata`、`.mw-empty-elt`、`.noprint`。
- **转换**：
  - `h1`–`h6` → `#`×n 标题；
  - `p` → 段落（空行分隔）；
  - `ul`/`ol`/`li` → `-` / `1.` 列表（按嵌套缩进）；
  - `pre`、`.mw-highlight`、`.mw-code` → ``` 围栏代码块；
  - `b`/`strong` → `**…**`，`i`/`em` → `*…*`，`code` → `` `…` ``；
  - `a` → `[文本](绝对URL)`（`/wiki/…` 补全为 `https://developer.valvesoftware.com/wiki/…`）；
  - `table`（wikitable）→ 与现状一致：**丢弃**。
- 收尾：实体解码、合并多余空行、去首尾空白。

## 7. 标识符与存储变更（破坏性）

### 7.1 主键：`pageid` → `title`

`title` 是 HTML 中唯一稳定可得的自然键，且已被 `index.get_by_title` 使用。

### 7.2 manifest（`data/manifest.json`）

每条记录由 `{pageid, title, revid, timestamp, file}` 改为：

```json
{ "title": "…", "revid": 123, "timestamp": "2018-09-05T02:16:00", "file": "raw/<slug>.html" }
```

### 7.3 raw 文件

- 路径：`data/raw/<slug>.html`，内容为**原始 HTML**。
- `slug = urllib.parse.quote(title, safe="")`：可逆、文件系统安全（`/`→`%2F`、`:`→`%3A`、
  空格→`%20`），避免 Windows 非法字符。

### 7.4 FTS5 索引（`index.py`）

- `docs` 列由 `title, content, pageid, revid, timestamp, url` 改为
  `title, content, revid, timestamp, url`（`title` 本身即可精确回查，无需额外列）。
- `rowid` 由 SQLite 自增；`upsert` 先按 `title` 查现有 `rowid`，存在则**复用同一 rowid**
  删+插，保证跨同步的 id 稳定。
- `search` 返回 `{title, url, snippet, score}`（去掉 `pageid`）。
- `get(id_or_title)`：纯数字按 `rowid`，否则按 `title`。
- `build_index` 读取 `raw/<slug>.html` → `html_to_markdown` → `upsert`。

> 已验证 FTS5 支持 `WHERE title = ?` 精确回查（现有 `get_by_title` 即依赖此行为）。

### 7.5 对 MCP 规格的影响

`2026-09-20-mcp-server-design.md` 中所有 `pageid` 字段（`search_docs`/`get_page`/`list_pages`
的返回与 `get_page` 的参数语义）需同步改为 `title`。`mcp_manager.py` 若经 `DocIndex` 传递
数字 id，也需一并核对。作为**后续任务**单独处理。

## 8. 增量同步（`sync.py`）

1. 枚举当前 title 集合（§5）：
   - **新增**：wiki 有、manifest 无；
   - **删除**：manifest 有、本次枚举无 → 从索引与 manifest 移除（raw 文件保留归档）。
     仅当该页**明确返回 404** 时判定为删除；其它抓取失败保留原记录并计入失败清单（§10）。
2. **变更检测**：对每个已有页比对 `revid`（从 HTML 的 `oldid` 提取）与 manifest。
3. **优化**：抓取使用条件请求（`If-None-Match` / `If-Modified-Since`），未变返回 `304`，
   降低带宽；若站点/Anubis 不支持 304，则回退普通 GET（行为不变，仅多传字节）。
4. **代价**：与现状相比，枚举不再能"一次拿到全部 revid"，同步变为 O(页数) 次请求
   （多数为廉价的 304）。此回退在文档中明确。

## 9. 迁移

现有 `data/raw/*.wiki` + 含 `pageid` 的 manifest 与 `docs.sqlite` 均无法直接复用（schema 与
文件格式都变了）。数据可再生（当前仅 41 页），迁移策略如下——**保留 manifest 的 title 列表
作为 BFS 种子**，避免因链接爬取遗漏而丢页：

```
# 保留 data/manifest.json（fetch 会读取其 title 作为种子）
删除 data/docs.sqlite        # 旧 schema 不兼容（CREATE TABLE IF NOT EXISTS 不会重建）
删除 data/raw/*.wiki         # 旧格式，改用 raw/*.html
cs2wt fetch                  # 以现有 manifest 的 title 为种子，HTML 全量抓取并覆盖 manifest
cs2wt build                  # 重建 FTS5 索引
```

不实现 wikitext→HTML 的转换（无意义）。

## 10. 错误处理

- 单页失败（网络错误、解析不到内容容器）**不中断整体**：记录并跳过，末尾汇总失败清单。
- **区分 404 与瞬态失败**：`404` 视为页面已删除（可判定 removed）；其它错误保留原记录，
  不得误判为删除。
- Anubis 挑战失败沿用现有异常语义（`AnubisSession` 抛出）。
- 枚举阶段某页抓取失败：不影响其它分支的 BFS（该页后续可被再次尝试或被列入失败清单）。

## 11. CLI 变化

- **移除** `--api`。
- `fetch` / `sync` / `build` / `search` / `get` / `list` / `status` 语义保持。
- `get <title>`：仍支持；数字参数按 `rowid` 解释。
- `list`：输出 `title`（去掉 pageid）。
- `--delay`（默认 1.0）、`--ua`（必须稳定）、`--cookie` 保持。

## 12. 测试（离线，不联网）

1. **合规守卫** `assert_allowed_url`：`/wiki/Foo` 通过；`/w/api.php`、`/w/Special:…`、
   `/wiki/Special:Export/Foo`、含 `?title=Special:`、含 `?action=history`、带任意 query
   一律抛错。
2. **元数据** `extract_meta`：合成 MediaWiki HTML 夹具，验证 title / revid / timestamp 及缺失分支。
3. **链接** `extract_links`：只取 `/wiki/`；忽略 `/w/`、`Special:`、外部、非目标命名空间；去重与归一化。
4. **转换** `html_to_markdown`：标题层级、列表、代码块、链接绝对化、粗斜体、被丢弃元素、实体解码。
5. **存储/索引**：按 title 的 `upsert`（rowid 稳定）、`search`、`get_by_title`、删除。
6. **同步**：mock `HtmlClient`，验证 added / updated / removed / unchanged 四类。
7. 更新现有测试：`tests/test_sync.py`（重写 `FakeClient` 与对 `wiki.PageContent`/`pageid` 的依赖）、
   `tests/test_index_options.py`（`upsert` 签名变更）。`tests/test_mcp_manager.py` 若经 `DocIndex`
   使用数字 id 亦需核对；`test_sections.py` / `test_mcp_config.py` 预期不受影响。

夹具为**自造的合成 HTML**，不提交任何 VDC 正文内容（版权与合规）。

## 13. 依赖与打包

- 保持**零第三方依赖**：仅用 stdlib（`html.parser`、`urllib.parse`、`re`、`sqlite3`、`json`）。
- `pyproject.toml` 无新增依赖。

## 14. 风险与取舍

| 风险 | 说明 | 缓解 |
|---|---|---|
| 枚举完整性 | 链接爬取只能发现被链接的页 | 种子并入已有 manifest；本树为父子结构，风险低 |
| 接口破坏 | 丢失 `pageid`，影响 manifest/index/MCP | §7 全量说明；MCP 规格单独跟进 |
| 保真度下降 | HTML 是渲染结果，非 wikitext | 已知取舍；raw 保留 HTML 可重建 |
| 同步请求数上升 | 无法批量拿 revid | 条件请求（304）降低代价 |
| 条件请求兼容性 | Anubis 下 304 行为待实测 | 不支持则回退普通 GET |

## 15. 验收标准

1. 抓取过程中，HTTP 层发出的**每一个**请求都通过 `assert_allowed_url`（有单测与断言）。
2. `cs2wt fetch` 能从零构建完整镜像（title/revid/timestamp/raw HTML/manifest）。
3. `cs2wt sync` 能正确识别 added/updated/removed/unchanged 并更新索引。
4. `cs2wt search` / `get` / `list` / `status` 在 title 键下正常工作。
5. 全部单测通过；无第三方依赖新增。