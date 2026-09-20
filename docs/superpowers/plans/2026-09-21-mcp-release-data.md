# 实现计划：MCP 从 Release 取数

对应规格：`docs/superpowers/specs/2026-09-21-mcp-release-data-design.md`

## 约定

- 全程 TDD：先写失败测试，再实现，再跑全量。
- 测试全离线：网络用 `mock.patch("cs2wt.release.urllib.request.urlopen")` 注入。
- 代码注释 / docstring 用英文；用户可见文档与 commit 用中文。
- 全量测试命令：`python -m unittest discover -s tests -v`。

---

## Task 1 — `release.py`：下载与比对

**产出**：`src/cs2wt/release.py`、`tests/test_release.py`

**接口**

```python
DEFAULT_REPO = "Just-Silver/cs2wt-docs-mcp"
RELEASE_TAG = "data-latest"
HTTP_TIMEOUT = 30.0

def asset_url(repo: str, tag: str, name: str) -> str: ...
def update_from_release(config, has_index: bool) -> Path | None: ...
```

**行为**

1. `asset_url` 拼 `https://github.com/{repo}/releases/download/{tag}/{name}`。
2. **节流**：`has_index` 且 `<data-dir>/last_check.json` 记录的**上次成功检查**距今 < `config.check_interval` 秒 → 直接返回 `None`（不发请求）。无索引时忽略节流。
3. 下载远端 `manifest.json` → 解析 JSON → 取 `generated_at`。
4. 本地 `generated_at`：优先 `docs.sqlite` 的 `meta` 表（只读打开），退回本地 `manifest.json`；都没有则视为无版本。
5. 无需更新（`has_index` 且远端不更新）→ 记录检查时间、返回 `None`。
6. 需要更新：把 `docs.sqlite` 下载到 `<db>.tmp`，把远端 manifest 原子写入本地 `manifest.json`，记录检查时间，返回 `<db>.tmp`。
7. 检查**成功**才写 `last_check.json`；`has_index=True` 时捕获 `urllib` / `json` 错误，`print` 警告并返回 `None`（不写检查时间）；`has_index=False` 时向上抛。

**测试**

- `asset_url` 构造正确。
- 首次（无索引）：下载 db 与 manifest，返回 tmp 路径。
- 远端 `generated_at` 相同 → 返回 `None`，不下载 db。
- 远端较新 → 返回 tmp 路径。
- `generated_at` 不可解析 → 视为更新。
- 有索引 + 网络异常 → 返回 `None`、不抛、不写 `last_check.json`。
- 无索引 + 网络异常 → 抛。
- 节流：`last_check.json` 在窗口内 → 不发请求；窗口外 → 发请求；无索引 → 忽略节流。

**验收**：`python -m unittest discover -s tests -p "test_release.py" -v`

---

## Task 2 — `mcp_config.py`：配置项调整

**产出**：改 `src/cs2wt/mcp_config.py`、改 `tests/test_mcp_config.py`

**行为**

- 新增 `release_repo`（`--release-repo` / `CS2WT_RELEASE_REPO` / 默认 `release.DEFAULT_REPO`）。
- 新增 `release_tag`（`--release-tag` / `CS2WT_RELEASE_TAG` / 默认 `release.RELEASE_TAG`）。
- 新增 `check_interval`（`--check-interval` / `CS2WT_CHECK_INTERVAL` / 默认 `86400` 秒）。
- 移除 `ua` / `cookie` / `delay` / `prefix` 字段与对应参数、env。
- `refresh` 语义不变（`--no-refresh` / `CS2WT_NO_REFRESH`）。

**测试**：默认值、env 覆盖、argv 优先、`--no-refresh`、`check_interval` 解析。

**验收**：`python -m unittest discover -s tests -p "test_mcp_config.py" -v`

---

## Task 3 — `mcp_manager.py`：改为 Release 更新

**产出**：改 `src/cs2wt/mcp_manager.py`、改 `tests/test_mcp_manager.py`

**行为**

- 删除 `default_refresh`、`_new_client` 及 `fetch` / `sync` / `wiki` / `http` 依赖。
- 新增 `default_update(config, has_index) -> Path | None`，转调 `release.update_from_release`。
- refresher 契约：`refresher(config, has_index) -> Path | None`。
- `_refresh`：调 refresher；若返回 staged 路径 → `_swap_in(staged)`；`finally` 仍 `_reopen_reader`。
- `_swap_in(staged)`：锁内关 reader、删除 `<db>-wal` / `<db>-shm`、`os.replace(staged, db)`。
- `info()`：`prefix` 从 reader 的 `get_meta("prefix")` 读取（无则空串）。

**测试**（更新现有用例以匹配新字段与新契约）

- refresher 返回 `None` → 状态 `READY`，不动索引。
- refresher 抛错 → `ERROR`。
- refresher 返回 staged 路径 → 替换 db、重开 reader、能查到新内容。
- 替换后旧 `-wal` / `-shm` 不再存在。
- 关闭后不被刷新线程复活（沿用现有用例）。

**验收**：`python -m unittest discover -s tests -p "test_mcp_manager.py" -v`

---

## Task 4 — 文案与文档

**产出**：改 `src/cs2wt/mcp_server.py`、`README.md`、`AGENTS.md`

- `INSTRUCTIONS` 与工具 docstring：数据来自 GitHub Release，启动时后台下载 / 更新，离线可用。
- README：
  - 安装：`pipx install git+https://github.com/Just-Silver/cs2wt-docs-mcp.git`（或 pip 等价写法）。
  - MCP 数据来源与首次自动下载；移除 `CS2WT_UA` / `CS2WT_COOKIE` / `CS2WT_DELAY` / `CS2WT_PREFIX` 说明；
    新增 `CS2WT_RELEASE_REPO` / `CS2WT_RELEASE_TAG`。
  - CLI 抓取章节标注「维护者 / 自建数据」。
- AGENTS.md：补 MCP 数据来源要点。

---

## Task 5 — 全量验证与提交

- `python -m unittest discover -s tests -v` 全绿。
- `python -c "import cs2wt.release, cs2wt.mcp_server"` 无误。
- 提交（中文信息），推送，`workflow_dispatch` 已有 Release 可作真实冒烟（可选）。

---

## 依赖顺序

Task 1、Task 2 可并行；Task 3 依赖二者；Task 4 依赖 Task 3 的接口定稿；Task 5 最后。