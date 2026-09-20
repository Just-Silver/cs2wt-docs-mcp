# MCP 从 Release 取数（落地规格 §10.7）

## 1. 背景与差距

规格 `2026-09-20-html-scraping-design.md` §10.1 / §10.7 早已确定：**MCP 是数据产物的唯一消费端，
只从仓库 Release 取数，永不访问 VDC**；CLI 的抓取通道仅供维护者 / CI 自建数据。

现状与规格冲突：`mcp_manager.default_refresh` 仍是「首次全量 crawl、后续 sync」的实时抓取路径。
后果是使用者首次运行必须联网并通过 Anubis 挑战、耗时且不稳定，谈不上「一键安装」。

本次把 MCP 改为：首次从 Release 全量下载预建索引；后续仅在产物有更新时整包替换。

## 2. 目标 / 非目标

**目标**

- MCP 启动时自动从 GitHub Release（滚动 tag `data-latest`）获取 / 更新索引，纯 HTTPS，无 git、无 gh、无 Anubis。
- 已有本地索引时**离线可用**：更新失败不致命。
- 从 GitHub 源码即可安装（`pipx install git+https://...`），无需发布 PyPI。

**非目标（后续项）**

- CLI 的 `fetch` / `sync` 抓取通道不变（维护者 / CI 用）。
- 不做字节级增量下载（当前 ~300KB，整包足够）。
- 不发布 GitHub Pages 备用源（规格 §10.7 标注为可选）。
- 不发布 PyPI。

## 3. 更新判定（核心）

- **版本标记 = `manifest.json` 的 `generated_at`**（ISO 8601 UTC），由 `fetch.crawl` / `sync` 写入；
  `build_index` / `sync` 同时写入 `docs.sqlite` 的 `meta` 表（键 `generated_at`）。
- 资产固定 URL：`https://github.com/<owner>/<repo>/releases/download/<tag>/<name>`。
- 判定流程：
  1. 下载远端 `manifest.json`（小）；
  2. 读远端 `generated_at`，与**本地 `generated_at`** 比对（本地优先取 `docs.sqlite` 的 `meta`，退回本地 `manifest.json`）；
  3. 远端更新 → 下载 `docs.sqlite` 并整包原子替换，同时更新本地 `manifest.json`；
  4. 相同、或本地更新（本地自抓）→ 跳过。
- 时间比较先 `datetime.fromisoformat` 解析再比；**无法解析视为有更新**（保守下载）。
- 不逐页比对 `revid`：产物整包发布，页级 revid 已在包内，无需网络往返逐页检测。

## 4. 启动流程

| 本地状态 | 行为 | 失败时 |
|---|---|---|
| 无索引（或 db 不可用） | 下载 manifest + docs.sqlite（全量） | `ERROR`（工具返回 status） |
| 有索引 | 下载 manifest（小）→ 比对 → 新则下载 docs.sqlite 替换 | 保持 `READY`，记 warning，下次启动再试 |

「有索引」判定沿用 `_indexed_count(db) > 0`。

## 5. 原子替换

- `docs.sqlite`：下载到 `<db>.tmp` → **关闭 reader** → 删除残留 `<db>-wal` / `<db>-shm` → `os.replace(tmp, db)` → 重开 reader。
  - Windows 上 `os.replace` 覆盖被打开的文件会失败，**必须先关闭 reader**；WAL 残留必须清掉，否则替换后会读到旧 WAL。
- `manifest.json`：先写 `<manifest>.tmp` 再 `os.replace`。
- reader 的关闭 / 重开由 `IndexManager` 负责；`release.py` 只负责把文件取到临时路径。

## 6. 配置（`ServerConfig`）

保留：`data_dir`、`db`、`refresh`（`--no-refresh` / `CS2WT_NO_REFRESH` 关闭自动更新）。

新增：

- `release_repo`：默认 `Just-Silver/cs2wt-docs-mcp`，env `CS2WT_RELEASE_REPO`，`--release-repo` 覆盖（fork 用）。
- `release_tag`：默认 `data-latest`，env `CS2WT_RELEASE_TAG`，`--release-tag` 覆盖。

**移除**：`ua`、`cookie`、`delay`、`prefix`——MCP 不再抓取。`info()` 的 `prefix` 改从索引 `meta` 读取。

## 7. 模块与接口

新增 `src/cs2wt/release.py`（纯标准库 `urllib`）：

- `DEFAULT_REPO`、`RELEASE_TAG`、`HTTP_TIMEOUT`
- `asset_url(repo, tag, name) -> str`
- `update_from_release(config, has_index) -> Path | None`
  返回待替换的临时 db 路径；无需更新返回 `None`。内部完成 manifest 下载、比对、db 下载与 manifest 落盘。

`mcp_manager`：

- refresher 契约改为 `refresher(config, has_index) -> Path | None`（返回 staged db 路径）。
- 新增 `_swap_in(staged)`：锁内关 reader、清 wal/shm、`os.replace`；`_refresh` 的 `finally` 仍调用 `_reopen_reader`。
- 移除对 `fetch` / `sync` / `wiki` / `http` 的依赖。

`mcp_server`：`INSTRUCTIONS` 与工具 docstring 措辞由「后台自动更新」改为「从 GitHub Release 自动下载 / 更新」。

## 8. 错误语义

- 有索引：`update_from_release` 内部捕获网络 / 解析错误，记 warning 并返回 `None`（不改变状态）。
- 无索引：错误向上抛，`IndexManager` 置 `ERROR`，工具返回 `status`。
- 下载中断：临时文件残留无害，下次覆盖；不触碰正式 db。

## 9. 测试（离线，不联网）

- 用 `mock.patch("cs2wt.release.urllib.request.urlopen")` 注入假响应。
- 覆盖：首次全量下载；`generated_at` 相同跳过；远端更新触发替换；离线且有索引不报错；离线且无索引报错；`generated_at` 不可解析视为有更新；`asset_url` 构造；临时文件 + `os.replace` 且清理 wal/shm。
- `mcp_manager`：refresher 返回 staged 路径时替换并重开 reader；返回 `None` 时不动。

## 10. 风险

- Release 资产缺失 / 改名 → 首次运行失败；README 说明可先跑 CLI 自建或稍后重试。
- 仓库改名 / fork → `CS2WT_RELEASE_REPO` 覆盖。
- 时区：`generated_at` 均为 UTC，比较前统一解析。

## 11. 文档

- README：安装（GitHub 源码）、MCP 首次自动下载、离线可用；移除 MCP 的抓取类环境变量说明。
- AGENTS.md：补「MCP 数据来源 = Release，永不访问 VDC」。