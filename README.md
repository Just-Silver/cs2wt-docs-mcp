# cs2wt-docs-mcp

离线索引 [Counter-Strike 2 Workshop Tools](https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools)
文档，并通过 **MCP** 提供给 AI 助手使用，同时附带一套 **CLI** 用于抓取、增量同步与索引维护。

抓取 [Valve Developer Community](https://developer.valvesoftware.com) 上 `/wiki/<标题>`
渲染后的 **HTML**，转换为 Markdown 后写入单文件 **SQLite FTS5** 全文索引，之后检索
**完全离线**、无需再访问网络。

页面以 **URL 标题为主键**（HTML 通道拿不到 `pageid`，也不用页面的显示标题）——
URL 标题唯一、稳定、与地址一致。原始 HTML 是 source of truth，索引可随时由它重建。

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
`action=history` 查询的路径。因此本项目**不使用** MediaWiki Action API（`/w/api.php`）。
请求的路径只有两种：渲染页面 **`/wiki/<标题>`**，以及用于枚举页面的
**`/wiki/Special:PrefixIndex/<前缀>`**（干净路径、无 query，robots 未禁）。

唯一允许的请求形态被固化为运行时不变式：URL 形态由 HTTP 层的守卫
`cs2wt.http.assert_allowed_url(url)` 在**每次请求前**校验，违规立即抛
`ValueError`（在请求发出前拦截）；请求方法由客户端 API 保证（`AnubisSession` 只暴露 `get`）：

| 约束 | 值 |
|---|---|
| scheme + host | `https://developer.valvesoftware.com` |
| path | 必须以 `/wiki/` 开头 |
| query / fragment | 必须为空 |
| path 内容 | 不得包含 `/w/`；`Special:` 仅放行 `/wiki/Special:PrefixIndex/` |
| method | 仅 `GET` |

四条 `Disallow` 规则均为路径 / 查询匹配，而上述两种路径都不含 query、不以 `/w/` 开头，
故**不匹配任何一条**（有单测覆盖）。

## 安装

要求 **Python ≥ 3.10**。抓取 / 解析 / CLI 路径只用标准库；MCP 服务端依赖官方
[`mcp`](https://pypi.org/project/mcp/) SDK（`mcp>=2,<3`，当前唯一的运行时依赖）。

从 GitHub 安装（推荐用 [pipx](https://pipx.pypa.io/) 隔离环境）：

```bash
pipx install git+https://github.com/Just-Silver/cs2wt-docs-mcp.git
# 或：pip install git+https://github.com/Just-Silver/cs2wt-docs-mcp.git
```

安装后得到两个入口：`cs2wt`（CLI）与 `cs2wt-mcp`（MCP 服务端，stdio）。

**MCP 无需手动准备数据**：首次运行会自动从 GitHub Release 下载预建索引（见下）。

想自行抓取数据（**联网**、需通过 Anubis 挑战）或参与开发时，用源码安装：

```bash
git clone https://github.com/Just-Silver/cs2wt-docs-mcp.git
cd cs2wt-docs-mcp
pip install -e .
cs2wt fetch     # 全量抓取 /wiki/<标题>，落盘 raw HTML
cs2wt build     # 构建 FTS5 索引
```

之后检索完全离线。

数据默认放在**用户级目录**（与当前工作目录无关，CLI 与 MCP 共用）：

| 平台 | 默认数据目录 |
|---|---|
| Windows | `%LOCALAPPDATA%\cs2wt-docs` |
| macOS | `~/Library/Application Support/cs2wt-docs` |
| Linux | `$XDG_DATA_HOME/cs2wt-docs`（默认 `~/.local/share/cs2wt-docs`） |

用 `--data-dir` / `CS2WT_DATA_DIR` 覆盖。

## CLI 用法

> `fetch` / `sync` 会实时抓取源站，供维护者或自建数据；只想检索的话，MCP 会自动下载预建索引，无需抓取。

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

全局参数：`--data-dir`（默认见「安装」的用户级目录）、`--db`（默认
`<data-dir>/docs.sqlite`）、`--cookie`（默认 `<data-dir>/cookies.txt`）、`--ua`、`--delay`。
（全局参数需写在子命令**之前**，例如 `cs2wt --cookie cookies.txt fetch`。）

## MCP 服务端

除 CLI 外，本项目提供一个 MCP 服务端，把离线索引通过 stdio 暴露给 AI 助手。

```bash
cs2wt-mcp            # 以 stdio 启动
```

数据来源是 GitHub Release（滚动 tag `data-latest`），**不访问源站**：

- **首次运行**：下载预建的 `docs.sqlite` + `manifest.json` 到用户级数据目录。
- **之后每次启动**：拉取约 5KB 的 `manifest.json` 比对 `generated_at`，仅在远端更新时整包替换；
  距上次成功检查不足 24 小时则跳过（`CS2WT_CHECK_INTERVAL`）。
- 已有本地索引时，下载失败不影响使用（照常离线检索）。

环境变量（均有默认值）：`CS2WT_DATA_DIR`、`CS2WT_DB`、`CS2WT_RELEASE_REPO`、
`CS2WT_RELEASE_TAG`、`CS2WT_CHECK_INTERVAL`、`CS2WT_NO_REFRESH`。
设置 `CS2WT_NO_REFRESH=1`（或 `--no-refresh`）可完全关闭自动下载 / 检查。

### 在 OpenCode（V2）中接入

OpenCode V2 在 `mcp.servers` 下配置 MCP 服务器；本地 stdio 服务器用 `"type": "local"`
加 `"command"` 数组。把下面这段放进你的项目 `opencode.jsonc`（或 `.opencode/opencode.jsonc`），
或全局 `~/.config/opencode/opencode.jsonc`——数据目录是用户级的，与工作区无关：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "cs2wt": {
        "type": "local",
        "command": ["cs2wt-mcp"]
      }
    }
  }
}
```

- 索引自动落在**用户级数据目录**（见「安装」），与 OpenCode 的工作区无关，
  所以在任何项目里打开 OpenCode 都开箱即用，**无需**配置路径。
- 首次运行会自动从 Release 下载索引（纯 HTTPS，无需 Anubis）。要改到别处、或用 fork 的
  产物，再加 `"environment": { "CS2WT_DATA_DIR": "...", "CS2WT_RELEASE_REPO": "owner/repo" }`。
- `cs2wt-mcp` 由安装步骤提供。若它不在 `PATH` 上，把 `command` 换成
  `["python", "-m", "cs2wt.mcp_server"]`（或写入入口脚本的绝对路径）。
- 想固定用本地索引、不自动联网检查：加 `"CS2WT_NO_REFRESH": "1"`（`environment` 的值都是字符串）。
- 其余可用环境变量：`CS2WT_DB`、`CS2WT_RELEASE_TAG`、`CS2WT_CHECK_INTERVAL`。

也可用 CLI 添加（会写入项目配置，保留其它设置）：

```bash
opencode mcp add cs2wt -- cs2wt-mcp
opencode mcp list        # 连接正常时显示 connected
```

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
<数据目录>（默认用户级，见「安装」）
  docs.sqlite           # FTS5 索引（title 为主键）；MCP 从 Release 下载
  manifest.json         # 每页 title/revid/timestamp/file + generated_at；同上
  last_check.json       # 上次成功检查 Release 的时间（节流用，本地生成）
  raw/<slug>.html       # 原始 HTML（source of truth）；仅 CLI 自建时存在
  cookies.txt           # Anubis 认证 cookie；仅 CLI 抓取时使用
```

## 架构

| 模块 | 职责 |
|---|---|
| `anubis.py` | 解析并求解 Anubis PoW 挑战 |
| `http.py` | 带 cookie jar 与限速的 HTTP 会话，自动过挑战；含合规守卫 `assert_allowed_url` |
| `wiki.py` | HTML 客户端 `HtmlClient`：PrefixIndex 枚举 + `/wiki/<标题>` 单页抓取 |
| `htmlparse.py` | 从 HTML 提取元数据 / 链接，并转 Markdown（零依赖） |
| `fetch.py` | 按前缀全量抓取文档树（raw HTML） |
| `sync.py` | 增量同步（逐页 revid 比对，新增/更新/删除） |
| `store.py` | manifest 与 raw HTML 文件的读写（按 title） |
| `index.py` | SQLite FTS5 索引（`title` 为键，rowid 跨同步稳定） |
| `release.py` | 从 GitHub Release 下载 / 比对预建索引（MCP 的数据来源） |
| `cli.py` | 命令行入口 |

## 增量同步

`cs2wt sync` 分两条相互独立的路径：

- **已有页**：对 manifest 中每一页逐页抓取，比对 HTML 中的 `oldid`（revid）。
  - 返回 **404**，或页面**变成重定向** → 判定删除，从索引与 manifest 移除（raw 文件保留归档）；
  - 返回 200 且 revid 变化 → 重抓、覆写 raw、更新索引；
  - 其它失败（超时 / 网络等）→ 单页在客户端层最多重试 `FETCH_RETRIES` 次
    （模块常量 `cs2wt.wiki.FETCH_RETRIES`，默认 3），仍失败则跳过该页、保留原记录，
    计入失败清单（`SyncReport.failed`），不判为删除。
- **新页**：用 `/wiki/Special:PrefixIndex/<前缀>` 枚举出全部页面，发现 manifest 之外的 title 并抓取入库。

枚举只用于**发现新增**；删除只由该页自身的 404 / 重定向决定，因此枚举遗漏不会造成误删。
同步仍是 O(页数) 次普通 GET 请求（条件请求见「后续项」）。

## 定时更新（GitHub Actions）

`.github/workflows/update-docs.yml` 负责把数据产物集中持久化到 Release（供下载与分发）：

- **触发**：`schedule` 每月 1 日 03:17 UTC 全量抓取一次（`fetch` + `build`），并发布到
  GitHub Release 滚动 tag **`data-latest`**（资产：`docs.sqlite` + `manifest.json`）。
- **手动兜底**：另提供 `workflow_dispatch`。GitHub **公共仓库连续 60 天无活动会自动禁用
  定时 workflow**（这里的"活动"指仓库活动，而非 workflow 运行）；届时可在仓库的
  Actions 页面手动触发，或对仓库产生一次提交以重新启用。
- CI 每次运行的出口 IP 不同，上一轮的 Anubis cookie 不可复用，故每轮都重新求解 PoW，
  且**不把 cookie 提交进 git**（使用 `$RUNNER_TEMP` 临时路径）。
- 抓取步骤用 `nick-fields/retry` 做整脚本重试，只覆盖**整轮失败**（如 Anubis / 网络整体
  不可用）；单页失败已由客户端层的单页重试处理，不依赖整脚本重跑。

## 从旧版本迁移

本次抓取通道由 MediaWiki Action API（`pageid` 键、`raw/*.wiki`）切换为
`/wiki/<标题>` HTML（`title` 键、`raw/*.html`）。旧数据无法直接复用（schema 与文件格式
都变了），按以下步骤重建即可：

```bash
# 保留 data/manifest.json（fetch 会读取其 title 作为 BFS 种子）
# 删除 data/docs.sqlite        # 旧 schema 不兼容
# 删除 data/raw/*.wiki         # 旧格式，改用 raw/*.html
cs2wt fetch                    # PrefixIndex 全量枚举 + 以现有 manifest 的 title 为种子
cs2wt build                    # 重建 FTS5 索引
```

不提供 wikitext → HTML 的转换（无意义）。保留 `manifest.json` 是为了把它已有的 title
并入种子，作为 PrefixIndex 之外的兜底。

> 若旧数据在仓库内的 `./data`：默认数据目录已改为用户级目录（见「安装」），给上面两条
> 命令加 `--data-dir data` 即可继续用原位置。

## 后续项

- **条件请求（304）优化**：`sync` 目前逐页普通 GET，后续可用
  `If-None-Match` / `If-Modified-Since` 降低带宽；若站点 / Anubis 不支持 304，则回退普通
  GET，行为不变。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 合规

VDC 内容通常为 **CC BY-NC-SA**。本项目只请求 robots.txt 允许的 `/wiki/<标题>` 与
`/wiki/Special:PrefixIndex/<前缀>` 路径（由 `assert_allowed_url` 硬约束），保持请求间隔
（默认 `--delay 1.0`）。请仅作本地个人用途，分发时保留署名与许可。本仓库只包含代码，
不包含抓取到的文档内容。

## 许可证

MIT