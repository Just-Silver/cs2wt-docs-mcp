# cs2wt-docs-mcp

离线索引 [Counter-Strike 2 Workshop Tools](https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools)
文档，并通过 **MCP** 提供给 AI 助手使用，同时附带一套 **CLI** 用于抓取、增量同步与索引维护。

抓取 [Valve Developer Community](https://developer.valvesoftware.com) 上 `/wiki/<标题>`
渲染后的 **HTML**，转换为 Markdown 后写入单文件 **SQLite FTS5** 全文索引，之后检索
**完全离线**、无需再访问网络。

页面以 **`title` 为主键**（HTML 通道拿不到 `pageid`）。原始 HTML 是 source of truth，
索引可随时由它重建。

## 背景：为什么需要一个 Anubis 求解器

VDC 站点由 [Anubis](https://github.com/TecharoHQ/anubis) 反爬代理保护，所有客户端
（包括非 `Mozilla` UA）都会被要求完成一个 SHA-256 工作量证明：

```
hex(sha256(randomData + str(nonce))) 以 difficulty 个 0 开头
```

`cs2wt.http.AnubisSession` 会自动解析挑战、求解、提交并持久化认证 cookie
（`techaro.lol-anubis-auth`，约 7 天有效）。挑战与 `User-Agent` 和客户端 IP 绑定，
所以**整个会话必须保持同一个 UA**。

## robots.txt 合规

VDC 的 `robots.txt` 禁止了 `/w/api.php`、`/w/Special:` 以及带 `title=Special:` /
`action=history` 查询的路径。因此本项目**不使用** MediaWiki Action API（`/w/api.php`），
只请求渲染页面 **`/wiki/<标题>`**。

唯一允许的请求形态被固化为运行时不变式：URL 形态由 HTTP 层的守卫
`cs2wt.http.assert_allowed_url(url)` 在**每次请求前**校验，违规立即抛
`ValueError`（在请求发出前拦截）；请求方法由客户端 API 保证（`AnubisSession` 只暴露 `get`）：

| 约束 | 值 |
|---|---|
| scheme + host | `https://developer.valvesoftware.com` |
| path | 必须以 `/wiki/` 开头 |
| query / fragment | 必须为空 |
| path 内容 | 不得包含 `/w/`，不得包含 `Special:` |
| method | 仅 `GET` |

四条 `Disallow` 规则均为路径 / 查询匹配，而 `/wiki/<标题>` 不含 query、不以 `/w/` 开头，
故**不匹配任何一条**（有单测覆盖）。

## 安装

无需第三方依赖，仅用 Python 标准库（Python ≥ 3.10）。

```bash
pip install -e .
```

或直接用源码运行：

```bash
set PYTHONPATH=src        # Windows (cmd)
python -m cs2wt --help
```

## CLI 用法

```bash
# 首次全量抓取（默认 prefix: "Counter-Strike 2 Workshop Tools"）
cs2wt fetch

# 增量同步：只更新变化的页面（逐页 revid 比对）
cs2wt sync
cs2wt sync --dry-run          # 只报告将发生的变更，不写盘

# 从下载的原始 HTML 构建 FTS5 索引
cs2wt build

# 检索 / 读取 / 列表 / 状态
cs2wt search "material editor" --limit 5
cs2wt get "Counter-Strike 2 Workshop Tools/Level Design/Compiling"
cs2wt list
cs2wt status
```

全局参数：`--data-dir`（默认 `data`）、`--db`（默认 `<data-dir>/docs.sqlite`）、
`--cookie`、`--ua`、`--delay`。（全局参数需写在子命令**之前**，例如
`cs2wt --cookie cookies.txt fetch`。）

## MCP 服务端

除 CLI 外，本项目提供一个 MCP 服务端，把离线索引通过 stdio 暴露给 AI 助手。

```bash
pip install -e .
cs2wt-mcp            # 以 stdio 启动
```

环境变量（均有默认值）：`CS2WT_DATA_DIR`、`CS2WT_DB`、`CS2WT_PREFIX`、
`CS2WT_UA`、`CS2WT_COOKIE`、`CS2WT_DELAY`、`CS2WT_NO_REFRESH`。

启动后服务端立即就绪，并在后台执行一次刷新：本地无索引时自动全量抓取并建索引，
已有索引时做增量同步。设置 `CS2WT_NO_REFRESH=1`（或 `--no-refresh`）可跳过刷新。

暴露的工具：

- `search_docs(query, limit)`：全文检索，返回 `count` 与 `results`
  （每项含 `title`、`url`、`snippet`、`score`）。
- `get_page(id_or_title, section)`：读取页面正文，可按章节截取。`id_or_title` 为纯数字时
  按数字 rowid 查询，否则按页面标题查询；返回 `found`、`title`、`url`、`revid`、
  `timestamp`、`content`。
- `list_pages()`：列出全部收录页面（每项含 `title`）。

> 标识符由 `pageid` 改为 `title` 是本次抓取通道变更的破坏性影响之一。

## 数据布局

```
data/
  raw/<slug>.html       # 原始 HTML（source of truth），slug = quote(title, safe="")
  manifest.json         # 每页 title/revid/timestamp/file
  docs.sqlite           # FTS5 索引（title 为主键）
cookies.txt             # Anubis 认证 cookie（可复用，勿提交）
```

## 架构

| 模块 | 职责 |
|---|---|
| `anubis.py` | 解析并求解 Anubis PoW 挑战 |
| `http.py` | 带 cookie jar 与限速的 HTTP 会话，自动过挑战；含合规守卫 `assert_allowed_url` |
| `wiki.py` | HTML 客户端 `HtmlClient`：链接 BFS 枚举 + `/wiki/<标题>` 单页抓取 |
| `htmlparse.py` | 从 HTML 提取元数据 / 链接，并转 Markdown（零依赖） |
| `fetch.py` | 按前缀全量抓取文档树（raw HTML） |
| `sync.py` | 增量同步（逐页 revid 比对，新增/更新/删除） |
| `store.py` | manifest 与 raw HTML 文件的读写（按 title） |
| `index.py` | SQLite FTS5 索引（`title` 为键，rowid 跨同步稳定） |
| `cli.py` | 命令行入口 |

## 增量同步

`cs2wt sync` 分两条相互独立的路径：

- **已有页**：对 manifest 中每一页逐页抓取，比对 HTML 中的 `oldid`（revid）。
  - 返回 **404** → 判定删除，从索引与 manifest 移除（raw 文件保留归档）；
  - 返回 200 且 revid 变化 → 重抓、覆写 raw、更新索引；
  - 其它失败（超时 / 网络等）→ 跳过该页、保留原记录，计入失败清单（`SyncReport.failed`），不判为删除。
- **新页**：从根页面做 `/wiki/` 链接 BFS，发现 manifest 之外的 title 并抓取入库。

枚举只用于**发现新增**；删除只由该页自身的 404 决定，因此枚举遗漏不会造成误删。
与旧版 `list=allpages` 一次拿全量 revid 相比，现在同步是 O(页数) 次普通 GET 请求，
此代价在文档中明确（条件请求见「后续项」）。

## 定时更新（GitHub Actions）

`.github/workflows/update-docs.yml` 负责把数据产物集中持久化到 Release（供下载与分发）：

- **触发**：`schedule` 每月 1 日 03:17 UTC 全量抓取一次（`fetch` + `build`），并发布到
  GitHub Release 滚动 tag **`data-latest`**（资产：`docs.sqlite` + `manifest.json`）。
- **手动兜底**：另提供 `workflow_dispatch`。GitHub **公共仓库连续 60 天无活动会自动禁用
  定时 workflow**（这里的"活动"指仓库活动，而非 workflow 运行）；届时可在仓库的
  Actions 页面手动触发，或对仓库产生一次提交以重新启用。
- CI 每次运行的出口 IP 不同，上一轮的 Anubis cookie 不可复用，故每轮都重新求解 PoW，
  且**不把 cookie 提交进 git**（使用 `$RUNNER_TEMP` 临时路径）。

## 从旧版本迁移

本次抓取通道由 MediaWiki Action API（`pageid` 键、`raw/*.wiki`）切换为
`/wiki/<标题>` HTML（`title` 键、`raw/*.html`）。旧数据无法直接复用（schema 与文件格式
都变了），按以下步骤重建即可：

```bash
# 保留 data/manifest.json（fetch 会读取其 title 作为 BFS 种子）
# 删除 data/docs.sqlite        # 旧 schema 不兼容
# 删除 data/raw/*.wiki         # 旧格式，改用 raw/*.html
cs2wt fetch                    # 以现有 manifest 的 title 为种子，HTML 全量抓取
cs2wt build                    # 重建 FTS5 索引
```

不提供 wikitext → HTML 的转换（无意义）。保留 `manifest.json` 是为了把它已有的 title
并入 BFS 种子，避免因链接爬取遗漏而丢页。

## 后续项

- **条件请求（304）优化**：`sync` 目前逐页普通 GET，后续可用
  `If-None-Match` / `If-Modified-Since` 降低带宽；若站点 / Anubis 不支持 304，则回退普通
  GET，行为不变。
- **MCP 只从 Release 取数**：后续让 MCP 通过纯 HTTPS 下载 `manifest.json` 比对
  `generated_at`，有新版本时原子替换 `docs.sqlite`，从而完全不接触 VDC 源站。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 合规

VDC 内容通常为 **CC BY-NC-SA**。本项目只请求 robots.txt 允许的 `/wiki/<标题>` 路径
（由 `assert_allowed_url` 硬约束），保持请求间隔（默认 `--delay 1.0`）。请仅作本地个人
用途，分发时保留署名与许可。本仓库只包含代码，不包含抓取到的文档内容。

## 许可证

MIT