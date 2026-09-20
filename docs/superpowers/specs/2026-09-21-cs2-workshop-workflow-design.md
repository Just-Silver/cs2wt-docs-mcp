# CS2 Workshop 地图制作工作流（MCP）设计

> 本文是**目标形态**的设计规格。落地分阶段（先子包验证、再拆项目），见 §11。

## 1. 背景与目标

现有仓库 `cs2wt-docs-mcp` 只做一件事：检索 CS2 Workshop Tools 官方 Wiki 文档。

目标是把它扩展成**一个完整的工作流**：agent 全自动产出一张可玩的 CS2 地图关卡。工作流涵盖
「查文档 → 设计关卡 → 生成地图 → 编译 → 启动测试 → 迭代」，通过**一个 MCP 宿主**对外暴露。

**验收标准（v1）= 最小可玩闭环**：程序生成几何 + 出生点 + 目标点，编译出能进游戏跑起来的
地图，全程无需人工开 Hammer。

## 2. 目标 / 非目标

**目标**

- agent 通过 MCP 工具，从一份结构化关卡规格生成 `.vmap` 文本，命令行编译成可玩地图。
- 纯本地运行（Windows + CS2 + Workshop Tools），不依赖远程 CI/CD。
- 生成过程**确定性、可复现、可离线测试**（不依赖 CS2 进程）。
- 保留并整合现有文档检索能力，作为工作流的一环。

**非目标（v1 明确不做）**

- 不驱动 Hammer GUI、不做 Hammer 插件/逆向（成本极高，见 §3）。
- 不做二进制 vmap 写入（`.vmap` 是文本 KeyValues2 DMX，直接写文本）。
- 不做斜面/楼梯/非轴对齐几何（v1 只做盒体 blockout）。
- 不做美术质量、光照烘焙质量调优、Workshop 发布。
- 不做多活动会话/并行建图。

## 3. 关键事实与约束（已调研核实）

- **`.vmap` 是文本 KeyValues2 DMX 格式**，可程序化生成。先例：`dotthegod/MC2CS`（纯 Python，
  从 Minecraft 结构生成带纹理的 vmap，含面剔除、实体生成、对接 `resourcecompiler`）。
- **编译可无 GUI**：官方文档明确「Hammer Build Map 窗口的 Command Line 可复制进 `.bat`，
  无需打开 CS2 Tools 即可编译地图」。可用工具：`resourcecompiler`、`VRAD3`、`vpk`、
  `dmxconvert`、`resourcecopy`、`source1import`（位于 `game/bin/win64/`）。
- **Hammer 无官方编辑 API**；社区 `Nnamllit1/hammer-addons` 是插件宿主，但**不暴露地图对象
  编辑**。故「驱动 Hammer 建几何」不在本方案内。
- **光照编译依赖光追 GPU**；v1 用 fast/无光照编译即可，不阻塞闭环。
- 项目路径形如 `<CS2>/content/csgo_addons/<addon>/maps/<map>.vmap`（content 为源，game 为编译产物）。

## 4. 命名与仓库结构（目标形态）

- 仓库：`cs2-workshop-mcp`
- 包命名空间：`cs2workshop.*`；文档模块 `cs2docs`
- MCP 命令：`cs2workshop-mcp`

`src/` 按职责拆包，一个**宿主包**对外暴露 MCP；每个包一份 `AGENTS.md` + 独立测试：

| 包 | 职责 | 依赖 |
|---|---|---|
| `cs2workshop.core` | 关卡规格模型 + vmap 文本序列化（几何/实体/材质 → KV2 DMX）。纯能力库，零第三方依赖 | 无 |
| `cs2workshop.addon` | addon 目录布局、路径解析、资源清单、材质编译编排 | core |
| `cs2workshop.compile` | 构造并调用 `resourcecompiler`/`vpk`，解析编译日志 | core |
| `cs2workshop.launch` | 启动 CS2 并加载地图测试，进程管理 | core |
| `cs2docs` | 现有 wiki 文档检索（从当前仓库迁入，含 fetch/build/release 管线） | 无 |
| `cs2workshop.mcp` | **宿主**：对外暴露 MCP 工具，串联以上各包（可含 CLI） | 全部 |

依赖方向单向；能力库**不得反向引用宿主**。

配套：`docs/planning/`、`CHANGELOG.md`、根 `AGENTS.md`（项目地图 + 依赖方向 + 跨项目铁律）。

## 5. 关卡规格（v1）

一份 JSON 文件即地图的**源真相**，agent 直接编辑；程序按规格**确定性**生成 vmap。

```jsonc
{
  "name": "de_test",
  "sky": "sky_day01_01",
  "materials": { "floor": "materials/dev/...", "wall": "...", "ceiling": "..." },
  "rooms": [
    { "id": "a", "min": [0,0,0], "max": [1024,1024,256], "materials": { /* 覆盖默认 */ } }
  ],
  "corridors": [ { "id": "c1", "from": "a", "to": "b", "width": 128, "height": 128 } ],
  "spawns":    { "ct": [ {"pos":[x,y,z], "angle":0} ], "t": [ /* ... */ ] },
  "objectives":{ "bombsites": [ {"id":"A", "min":[...], "max":[...]} ] },
  "lights":    [ {"type":"light_environment", "pos":[...], "angles":[...], "brightness":1.0} ],
  "props":     [ {"model":"models/...", "pos":[...], "angles":[...]} ]
}
```

- 单位统一 Hammer unit；坐标系与 Source 2 一致。
- `rooms` 为轴对齐盒体；`corridors` 连接两个房间（由两端房间与宽高推导出盒体）。
- 实体 classname 映射（`info_player_counterterrorist` / `light_environment` / 包点 brush entity /
  `prop_static` 等）**以 spike 实测为准**，不在本规格硬编码。
- 校验规则（`map_validate`）：房间重叠、走廊端点不存在、缺出生点、目标点在房间外、材质路径非法等。

## 6. vmap 生成（`cs2workshop.core`）

- 输入：LevelSpec（§5）；输出：`.vmap` 文本（KeyValues2 DMX）。
- 参考 MC2CS 的 writer 结构：世界几何（world）按材质/空间分组为面片网格，逐面写 UV 与材质引用；
  实体写入 entity lump；世界参数（sky 等）写入 worldspawn。
- 生成必须是**纯函数**：同一 spec → 字节一致的 vmap（便于测试与 diff）；随机 ID/引用用固定种子或
  由 spec 派生。
- 不在本层碰文件系统之外的东西；不调用任何 Valve 工具。

## 7. addon 与编译（`cs2workshop.addon` / `cs2workshop.compile`）

- `addon`：解析/创建 addon 目录结构；把生成的 vmap 落到 `content/csgo_addons/<addon>/maps/`；
  维护材质资源清单。
- `compile`：构造 `resourcecompiler` 命令行（**参数以 spike 实测为准**），子进程执行；
  解析 stdout/stderr，归纳为「成功 / 失败 + 关键日志行」返回给 agent。
- 材质：v1 先用引擎自带 dev 材质，不强制编译自定义材质（可延后）。
- 路径发现：自动定位 CS2 安装（Steam 库），失败可由配置覆盖。

## 8. 启动测试（`cs2workshop.launch`）

- 启动 CS2 并以控制台命令加载本地地图（`map <name>`），用于 agent 自测。
- 进程管理：不阻塞宿主；返回可观测状态（是否启动、日志关键行）。
- v1 只做「能启动并加载」，不做游戏内自动化验收。

## 9. MCP 工具面（v1）

| 工具 | 作用 |
|---|---|
| `map_spec_schema` | 返回规格 schema/说明（agent 据此写 JSON） |
| `map_create(name)` | 脚手架：建 addon 目录 + 空规格文件 |
| `map_validate(spec)` | 校验规格，返回问题清单 |
| `map_build(spec)` | 确定性把规格编译成 vmap，写入 addon |
| `map_compile(name, mode)` | 调 `resourcecompiler`/`vpk`，返回日志摘要 |
| `map_launch(name)` | 启动 CS2 加载地图测试 |
| `map_summary(spec)` | 回读规格摘要（agent 自省） |
| `docs_*`（沿用现有） | 文档检索，工作流中供 agent 查证 |

- 工具参数带默认值、返回 `Task<string>`/中文提示、错误不抛异常（沿用现有 MCP 约定）。
- 工具族按前缀命名空间化：`map_*` / `docs_*`。

## 10. 端到端工作流

```
map_create → agent 写/改 level.json → map_validate → map_build
  → map_compile → map_launch → （据反馈迭代）
```

## 11. 落地阶段

- **第 0 步 · spike（最高优先级）**：照 MC2CS 做法产出「一个房间 + 出生点 + 一盏灯」的 vmap，
  用 Hammer Build Map 的命令行在 `.bat` 里跑通编译，确认**无需开 Hammer 即可出可玩地图**，
  并确定实体 classname 与 `resourcecompiler` 参数。**此步不通，整体方案不成立。**
- **阶段 1 · 子包验证**：在当前仓库内先以 `cs2workshop.*` 子包实现 core/addon/compile/launch 与
  宿主 MCP，跑通闭环。此阶段**不改仓库名**、不拆独立发行包。
- **阶段 2 · 拆项目 + 改名**：跑通后，按 §4 拆成独立包、迁移 `cs2docs`、仓库改名为
  `cs2-workshop-mcp`（远程改名与可见性由用户操作）。

## 12. 测试策略

- `core`：纯离线单测——同一 spec 生成字节一致 vmap；几何/实体/校验规则覆盖；用固定样例做快照测试。
- `addon`/`compile`：用假子进程/注入命令构造器测试命令行与日志解析，不真跑 `resourcecompiler`。
- `launch`：假进程测试启动命令与状态机。
- 端到端：需真实 CS2 环境，手动/本机验证，不进 CI。

## 13. 风险

- **vmap 结构 / 编译参数未验证** → 第 0 步 spike 前置，失败则回退（考虑 `source1import` 或调 Hammer）。
- **光照依赖光追 GPU** → v1 用 fast/无光照编译规避。
- **CS2 更新导致格式/工具参数变化** → 编译参数集中在 `compile` 包，便于更新；实体映射集中在 core。
- **仓库改名** → 影响现有 Release 取数配置（`CS2WT_RELEASE_REPO`）与安装说明，迁移时同步。