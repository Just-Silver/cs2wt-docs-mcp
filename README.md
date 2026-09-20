# cs2wt-docs-mcp

离线索引 [Counter-Strike 2 Workshop Tools](https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools)
文档，并通过 **MCP** 提供给 AI 助手使用，同时附带一套 **CLI** 用于抓取、增量同步与索引维护。

抓取 [Valve Developer Community](https://developer.valvesoftware.com) 的
MediaWiki 原始 wikitext，转换后写入单文件 **SQLite FTS5** 全文索引，之后检索
**完全离线**、无需再访问网络。

## 背景：为什么需要一个 Anubis 求解器

VDC 站点由 [Anubis](https://github.com/TecharoHQ/anubis) 反爬代理保护，所有客户端
（包括非 `Mozilla` UA）都会被要求完成一个 SHA-256 工作量证明：

```
hex(sha256(randomData + str(nonce))) 以 difficulty 个 0 开头
```

`cs2wt.http.AnubisSession` 会自动解析挑战、求解、提交并持久化认证 cookie
（`techaro.lol-anubis-auth`，约 7 天有效）。挑战与 `User-Agent` 和客户端 IP 绑定，
所以**整个会话必须保持同一个 UA**。

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

# 增量同步：只更新变化的页面（全量 revid 比对）
cs2wt sync
cs2wt sync --dry-run          # 只报告将发生的变更，不写盘

# 从下载的原始 wikitext 构建 FTS5 索引
cs2wt build

# 检索 / 读取 / 列表 / 状态
cs2wt search "material editor" --limit 5
cs2wt get "Counter-Strike 2 Workshop Tools/Level Design/Compiling"
cs2wt list
cs2wt status
```

全局参数：`--data-dir`（默认 `data`）、`--db`（默认 `<data-dir>/docs.sqlite`）、
`--cookie`、`--api`、`--ua`、`--delay`。

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

## MCP 服务端（规划中）

MCP 是面向 AI 的主入口。设计要点：

- 复用同一套索引与抓取代码，**不重复实现**；
- 进程启动时检查一次更新；每次工具调用带节流地检查；需要时**后台异步**抓取，
  当前检索先用现有索引返回，不阻塞；
- 暴露工具：`search_docs`、`get_page`、`list_pages` 等。

## 数据布局

```
data/
  raw/<pageid>.wiki     # 原始 wikitext（source of truth）
  manifest.json         # 每页 pageid/title/revid/timestamp
  docs.sqlite           # FTS5 索引
cookies.txt             # Anubis 认证 cookie（可复用，勿提交）
```

## 架构

| 模块 | 职责 |
|---|---|
| `anubis.py` | 解析并求解 Anubis PoW 挑战 |
| `http.py` | 带 cookie jar 与限速的 HTTP 会话，自动过挑战 |
| `wiki.py` | MediaWiki Action API 客户端（`formatversion=2` + continuation） |
| `fetch.py` | 按前缀全量抓取文档树 |
| `sync.py` | 增量同步（全量 revid 比对，新增/更新/删除/移动） |
| `store.py` | manifest 与 raw 文件的读写 |
| `convert.py` | wikitext → Markdown（轻量、零依赖） |
| `index.py` | SQLite FTS5 索引（`pageid` 作 `rowid`，便于增量更新） |
| `cli.py` | 命令行入口 |

## 增量同步

`cs2wt sync` 使用 `generator=allpages` + `prop=revisions` 一次遍历拿到全部页面的
`pageid/title/revid/timestamp`，与本地 manifest 比对：

- **新增**：wiki 有、本地无 → 抓取并入库；
- **更新**：`revid` 或标题变化（移动）→ 重抓、覆写 raw、更新索引；
- **删除**：本地有、wiki 无 → 从索引和 manifest 移除，raw 文件保留归档；
- **未变**：跳过，不产生任何内容请求。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 合规

VDC 内容通常为 **CC BY-NC-SA**，且站点明确使用 Anubis 反爬。请仅作本地个人
用途，遵守 `robots.txt`，保持请求间隔（默认 `--delay 1.0`），分发时保留署名与
许可。本仓库只包含代码，不包含抓取到的文档内容。

## 许可证

MIT