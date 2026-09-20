# MCP 服务端设计

- 日期：2026-09-20
- 状态：待实现
- 关联：`src/cs2wt/{index,sync,fetch,convert,store,http,wiki}.py`（现有 CLI 与索引）

## 1. 背景与目标

项目已有一套离线索引工具链（`cs2wt` CLI）：抓取 Valve Developer Community 上
`Counter-Strike 2 Workshop Tools` 及其子页的原始 wikitext，转换为 Markdown，写入单文件
SQLite FTS5 索引，支持全量抓取（`fetch`）与增量同步（`sync`）。

本设计新增 **MCP 服务端**，把这份离线索引通过 Model Context Protocol 暴露给 AI 助手
（首要目标客户端：opencode2），让 AI 能直接检索与阅读文档，而无需访问网络。

目标：

- 复用现有索引与同步能力，不重复实现抓取/解析逻辑。
- 检索**完全离线**；联网仅发生在后台刷新。
- 对客户端启动友好：不因网络或 Anubis 挑战而阻塞或超时。
- 工具描述自带**触发条件**，适配 opencode2 不主动暴露全部工具的机制。

## 2. 方向决策（已与用户确认）

| 决策点 | 结论 |
|---|---|
| MCP 实现方式 | 官方 `mcp` Python SDK（引入第三方依赖，放弃"零依赖"） |
| 暴露工具集 | `search_docs` / `get_page`（含 `section`）/ `list_pages` |
| 启动刷新 | **后台异步**执行一次，不阻塞 server 就绪 |
| 首次无索引 | 后台**自动全量抓取 + 建索引**，开箱即用 |

## 3. 关键约束

1. **工具触发条件**：opencode2 不会主动暴露全部工具。每个工具的 `description` 必须说明
   "何时使用 / 何时不使用 / 返回什么"；`initialize` 的 server instructions 需概述整体用途，
   以便客户端正确选择与暴露工具。
2. **Anubis 保护**：VDC 站点由 Anubis 反爬代理保护，后台抓取必须复用 `AnubisSession`
   （自动求解 PoW、持久化 cookie、固定 User-Agent）。
3. **SQLite 并发**：后台线程写索引的同时，主线程要能读。需启用 WAL，读写连接分离。
4. **仅 stdio 传输**：服务端由客户端以子进程方式启动，走标准输入输出，不监听端口。

## 4. 架构

### 4.1 模块与入口

- 新增模块 `src/cs2wt/mcp_server.py`。
- 新增 console script：`cs2wt-mcp = cs2wt.mcp_server:main`。
- 不修改现有 CLI 行为；两者共用底层模块。

### 4.2 组件

- **`IndexManager`**
  - 负责数据目录、索引路径、`DocIndex` 读连接的创建与关闭。
  - 维护刷新状态（见 §5），并串行化后台刷新（同一时刻至多一个）。
  - 提供只读方法：`search` / `get` / `list_titles` / `status`，供工具 handler 调用。
  - 线程安全：读连接仅由主（事件循环）线程使用；后台刷新使用独立连接。
- **工具 handler**
  - 纯函数式：接收参数、调用 `IndexManager`、返回结构化结果（MCP `TextContent`，JSON 字符串）。
  - 不直接触碰网络或写盘。
- **`extract_section`**
  - 纯函数：从 Markdown 内容中按标题名切出一个章节。
- **`Refresher`**（可内联进 `IndexManager`）
  - 后台线程入口：判断"无索引则全量、有索引则增量"，执行并更新状态与错误信息。

### 4.3 数据流

```
MCP client (opencode2)
  └─ stdio ──> cs2wt-mcp 进程
                  ├─ 工具 handler ──> IndexManager(读连接) ──> docs.sqlite(FTS5)
                  └─ 后台 Refresher 线程
                        ├─ 无索引: crawl() + build_index()
                        └─ 有索引: sync()
                              └─ 独立写连接 ──> docs.sqlite (WAL)
```

## 5. 启动与刷新流程

1. 进程启动后**立即**完成 MCP `initialize` 并列出工具，不等待网络。
2. 在后台线程启动一次刷新：
   - 若 `<data_dir>/docs.sqlite` 不存在或 `count()==0` → 全量：`crawl(client, prefix, data_dir)`
     然后 `build_index(data_dir, db)`。
   - 否则 → 增量：`sync(client, prefix=prefix, data_dir=data_dir, db_path=db)`。
3. 状态机：

   | 状态 | 含义 | 工具行为 |
   |---|---|---|
   | `INITIALIZING` | 首次全量抓取中，索引为空 | 返回"索引初始化中，请稍后重试"提示 |
   | `REFRESHING` | 有旧索引，后台增量同步中 | 正常检索（旧数据），可附"正在后台更新"提示 |
   | `READY` | 刷新完成 | 正常检索 |
   | `ERROR` | 刷新失败 | 有旧索引则正常检索并附错误摘要；无索引则返回失败说明 |

4. 刷新**只做一次**（进程生命周期内），不做定时器、不做按调用节流。
5. 刷新失败不退出进程：记录错误信息，保留已有索引；不再自动重试。

## 6. 工具定义

所有工具返回 JSON 字符串（`mcp.types.TextContent`）。失败（如未找到页面）返回结构化错误对象，
而非抛出异常。

### 6.1 `search_docs`

- 签名：`search_docs(query: str, limit: int = 10) -> str`
- 触发条件（description 要点）：
  - **使用**：当需要根据关键词/术语查找 CS2 Workshop Tools 文档时；回答任何涉及该工具集用法、
    概念、命令、实体的技术问题前，应优先用它定位来源页面。
  - **不使用**：已知确切页面标题或 pageid 时，直接 `get_page` 更高效；与 CS2 Workshop Tools
    无关的问题不要使用。
  - **返回**：命中的页面列表，每项含 `pageid`、`title`、`url`、`snippet`、`score`（bm25，越小越相关）。
- 实现：`IndexManager.search`（基于 `DocIndex.search`）。

### 6.2 `get_page`

- 签名：`get_page(id_or_title: str, section: str | None = None) -> str`
- 触发条件：
  - **使用**：已经知道页面标题或 pageid，需要读取正文；或想读取某个章节以控制返回体积。
  - **不使用**：只知道模糊关键词时先用 `search_docs`。
  - **返回**：`pageid`、`title`、`url`、`revid`、`timestamp`、`content`；指定 `section` 时
    `content` 仅含该章节。
- 参数解析：`id_or_title` 若为纯数字按 pageid 查，否则按标题查（`get_by_title`）。
- `section` 匹配规则（见 §7）。

### 6.3 `list_pages`

- 签名：`list_pages() -> str`
- 触发条件：
  - **使用**：需要了解文档覆盖范围、列举全部页面，或确认某主题是否有收录。
  - **不使用**：已有明确查询词时用 `search_docs`。
  - **返回**：`{count, pages:[{pageid,title}]}`。
- 实现：`IndexManager.list_titles`。

### 6.4 Server instructions

`initialize` 返回的 `instructions` 字段概述：

> 本服务提供 Counter-Strike 2 Workshop Tools 官方文档（Valve Developer Community）的离线全文检索。
> 先 `search_docs` 定位，再用 `get_page` 精读；已知页名可直接 `get_page`。数据在服务启动时后台
> 自动更新，无需手动触发。

## 7. Section 提取

`extract_section(markdown: str, section: str) -> str | None`

- 识别行首 `#{1,6} ` 形式的 Markdown 标题（`convert.py` 的输出格式）。
- 匹配：先精确匹配标题文本（去空白、大小写不敏感）；否则退化为包含匹配；再否则返回 `None`。
- 切出范围：从匹配标题行起，到下一个**同级或更高级**标题前（即包含其子章节）。
- 无匹配时返回 `None`，由 `get_page` 转换为"未找到该章节"的结构化结果。

## 8. 并发与存储

- `DocIndex` 增加可选 WAL 设置（仅 MCP 路径启用，避免影响 CLI 行为）：
  连接建立后执行 `PRAGMA journal_mode=WAL;`。
- 读连接：`IndexManager` 主线程持有，`check_same_thread=True`（默认）。
- 写连接：后台线程内自建 `DocIndex`，用完关闭。
- WAL 下读写可并发；刷新完成后无需重开读连接即可看到新数据。

## 9. 配置

优先级：命令行参数 > 环境变量 > 默认值。

| 配置 | CLI 参数 | 环境变量 | 默认 |
|---|---|---|---|
| 数据目录 | `--data-dir` | `CS2WT_DATA_DIR` | `data` |
| 索引路径 | `--db` | `CS2WT_DB` | `<data-dir>/docs.sqlite` |
| 页面前缀 | `--prefix` | `CS2WT_PREFIX` | `Counter-Strike 2 Workshop Tools` |
| API 地址 | `--api` | `CS2WT_API` | 现有默认 |
| User-Agent | `--ua` | `CS2WT_UA` | 现有默认 |
| Cookie 路径 | `--cookie` | `CS2WT_COOKIE` | `cookies.txt` |
| 请求间隔 | `--delay` | `CS2WT_DELAY` | `1.0` |
| 禁用后台刷新 | `--no-refresh` | `CS2WT_NO_REFRESH` | 否 |

`--no-refresh` 用于测试/离线场景：启动后不联网，直接用现有索引。

## 10. 错误处理

- **索引未就绪**：工具返回 `{status:"initializing", message:"..."}`，不视为错误。
- **刷新失败**：捕获异常，记录到状态；`ERROR` 且无索引时工具返回明确失败说明。
- **页面/章节未找到**：返回 `{found:false, ...}`。
- **参数错误**：返回结构化错误，不抛异常给客户端。
- 所有异常都不得导致进程退出。

## 11. 测试

新增离线单测（不联网）：

1. `extract_section`：精确匹配、大小写/空白、包含匹配、含子章节、未命中。
2. 工具 handler：用临时构建的 `DocIndex` 验证 `search_docs` / `get_page`（含 section）/ `list_pages`
   的返回结构与未找到分支。
3. `IndexManager` 状态：`--no-refresh` 下为 `READY`；mock 刷新失败后进入 `ERROR` 且不崩溃。
4. 现有 6 个单测保持通过。

## 12. 依赖与打包

- `pyproject.toml` 增加 `dependencies = ["mcp"]`。
- 增加 `[project.scripts] cs2wt-mcp = "cs2wt.mcp_server:main"`。
- 保持 `requires-python = ">=3.10"`。

## 13. 非目标（YAGNI）

- 不做索引写操作类工具（增删改由 CLI 负责）。
- 不做语义/向量检索、不做 embedding。
- 不做认证、多用户、远程传输（HTTP/SSE）；仅 stdio。
- 不做定时刷新、按调用节流、手动 refresh 工具。
- 不改动现有 CLI 的命令与行为。