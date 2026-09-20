# 协作约定与工程要点

本文件定义本项目的协作模式与关键工程约定，避免每次会话重复沟通。

## 语言

- 与用户交流、撰写**用户可见文档**（README / spec / plan）一律使用**简体中文**。
- Git commit 信息使用**中文**。
- **代码注释与 docstring 用英文**——现有代码库（`http.py`、`index.py` 等）皆为英文，勿翻译成中文。

## 决策边界

用户**不熟悉 Python 生态**，分工如下：

- **方向（用户决策）**：技术栈、依赖取舍、架构取向、对外接口 / 工具集、产品定位、仓库命名与可见性、远程仓库操作（创建 / 删除 / 改名 / 推送）。
- **细节（助手自主）**：规格、设计、实现计划、代码结构、命名、测试、错误处理、分支策略。
- 原则：**方向问用户，细节自己定**。出现新的方向性问题时，用简短选项征询，不要长篇论证。

## 工作流程

1. 功能开发前走 brainstorming；architectural 任务把 spec 写入 `docs/superpowers/specs/`，实现计划写入 `docs/superpowers/plans/`。
2. spec 与 plan 由助手**自审**后落盘并提交，不要求用户逐节审批。
3. 开发**一律使用子代理**执行（每个任务派发独立子代理，任务间由助手审查）。
4. 是否新建分支、如何命名由助手决策（默认 `feat/<主题>`，完成后合并回 `main`）。

## 常用命令

```bash
pip install -e .                                            # 先装：MCP 测试直接 import cs2wt
python -m unittest discover -s tests -v                     # 全量测试（全离线，无网络）
python -m unittest discover -s tests -p "test_sync.py" -v   # 单个测试文件
cs2wt fetch && cs2wt build                                  # 抓取 + 建 FTS5 索引
cs2wt-mcp                                                   # 以 stdio 启动 MCP 服务端
```

- **测试命令的坑**：不要用 `python -m unittest tests.test_xxx`——本机 site-packages 里有一个无关的 `tests` 包会抢占它。必须用上面的 `discover -s tests -p "..."` 形式。
- **CLI 全局参数**（`--data-dir` / `--db` / `--cookie` / `--ua` / `--delay`）必须写在**子命令之前**：`cs2wt --cookie cookies.txt fetch`。`--api` 已移除。
- 测试通过注入 fake session/client 保持离线，改抓取/同步时沿用该模式，勿联网。

## 架构要点（不易从文件名看出）

- **抓取只走 HTML 通道** `/wiki/<标题>`：VDC 的 robots.txt 禁止 `/w/api.php` 与 `/w/Special:`，MediaWiki Action API 已弃用。`http.py` 的 `assert_allowed_url` 是硬守卫，所有出站请求都经 `AnubisSession._open`。
- **主键是 `title`**（HTML 拿不到 `pageid`）。raw 为 `<数据目录>/raw/<slug>.html`，`slug = urllib.parse.quote(title, safe="")`。
- **数据目录默认是用户级全局目录**（`store.default_data_dir()`：Windows `%LOCALAPPDATA%\cs2wt-docs`、macOS `~/Library/Application Support/cs2wt-docs`、Linux `$XDG_DATA_HOME/cs2wt-docs`），CLI 与 MCP 共用；可用 `--data-dir` / `CS2WT_DATA_DIR` 覆盖。**绝不要把默认值改回相对 cwd 的 `data/`**——MCP 在用户自己的项目目录里运行，落 cwd 会污染用户工作区。
- `data/`、`cookies.txt`、`*.sqlite`、`.superpowers/`、`.codegraph/` 均被 gitignore，**不要提交**。
- `wiki.py` = `HtmlClient`：`/wiki/` 链接 BFS 枚举（站点无 sitemap）+ 单页抓取。单页瞬态失败按模块常量 `FETCH_RETRIES` / `FETCH_RETRY_DELAY`（`wiki.py` 顶部）重试；404 不重试。
- `htmlparse.py` 是零依赖 HTML 解析/转换模块（`extract_meta` / `extract_links` / `html_to_markdown`），已取代旧的 `convert.py`。
- **同步语义**：删除**只**由页面自身 404 决定，链接枚举仅用于发现新增；标题重命名（重定向）表现为旧键 `removed` + 新键 `added`；revid 未变的页若索引缺失会补 upsert（自愈）。
- **Anubis**：挑战与 `User-Agent` + 客户端 IP 绑定，cookie 约 7 天；**整会话必须保持同一 UA**。CI runner 出口 IP 每轮不同，故每轮重新求解、不缓存 cookie。
- 索引：单文件 SQLite **FTS5**，`title` 为键，`rowid` 跨同步稳定（`upsert` 复用 rowid）。
- 依赖：运行时仅 `mcp>=2,<3`；CLI / 抓取 / 解析路径只用标准库（`html.parser` / `urllib` / `sqlite3`）。新增依赖登记到 `pyproject.toml`。

## 易错点

- 旧 `data/docs.sqlite`（`pageid` schema）**不兼容**：迁移时删库、删 `data/raw/*.wiki`、**保留** `manifest.json`，再 `cs2wt fetch` + `cs2wt build`（详见 README「从旧版本迁移」）。若旧数据仍在仓库 `./data`，这些命令要加 `--data-dir data`（默认已改为用户级目录）。
- CI 工作流 `.github/workflows/update-docs.yml` **无法离线验证**；合入 `main` 后需用 `workflow_dispatch` 手动触发确认（`schedule` 只在默认分支最新提交上生效）。
- `crawl` 会向 stdout 打印抓取进度，测试输出因此有噪音，属正常。
- MCP 启动默认后台刷新（无索引全量抓取、有索引增量同步），`CS2WT_NO_REFRESH=1` 可跳过。