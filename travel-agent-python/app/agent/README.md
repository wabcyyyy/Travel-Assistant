# 生成链路模块蓝图（G-2.1）

> 本文件是 G-2.2~2.4 拆分的**验收依据**：只定义形状与依赖方向，不列清单。
> 新增生成能力时先读这里，再决定放哪一层。

## 一句话职责

| 模块 | 一句话 |
|---|---|
| `generation_core.py` | 纯规则骨架：N-1 晚住宿节奏、摊铺、预算估算、脏项与模型申报字段清洗——不 import 上面任何模块 |
| `poi_identity.py` | 点位同一性判定：名称归一、球面距离（0/0 判缺失）、跨天去重——与 `generation_core` 同层的叶子 |
| `budget.py` | 预算档位与约束句、餐价钳制、0 价补水 |
| `suggestions.py` | 备选池：候选组装、类别地板与上限、缺口补齐 |
| `suggestion_grounding.py` | 备选池的批量后验证（「发现更多」那 24-40 个名字唯一一次被外部数据检验） |
| `reference_pool.py` | 参考资料池：把权威候选编成可引用的编号资料，并把模型引用落地回权威字段 |
| `landing.py` | 两条生成链路共用的落地步骤：脏项过滤 → 引用/本地落地 → 证伪点删除 |
| `existence.py` | 存在性解析器：可插拔 provider 的三值判定（证实/证伪/未判定）+ 同城硬闸 + 证据票签发 |
| `existence_commercial.py` | 付费 provider（高德 / Google Places）：无 key 一律如实未判定，不占免费配额 |
| `grounding_evidence.py` | 证据票：「本服务真的抓过这一行」的不可伪造凭据 |
| `grounding_labels.py` | 背书口径唯一实现：来源值域 + 证据校验 → 溯源标签（三条链路共用） |
| `grounding.py` | 事实落地：坐标校验与本地权威补点（判定委托 `existence`） |
| `map_link.py` | 地图深链：关键词/路线两种 URL 与 GCJ-02 偏移 |
| `open_plans.py` | 图路径的逐日草案：补池 → 落地 → 删证伪点 → 组装（与 `trip_stream` 产出同构） |
| `generators.py` | 内容组装原语与对外面（纯函数优先，无编排） |
| `narrative.py` | 叙事字段清洗：限值截断、类型降级、指令残留剥离、模型申报字段剥离 |
| `day_prompts.py` | Prompt 组装：系统提示绑定、约束句拼装、日/整段两种入口的 LLM 调用 |
| `day_stream.py` | 单日链路：一次生成的编排与落地（反思/重试不在此） |
| `day_workflow.py` | 单日图的门面 |
| `stream_parser.py` | 流式 JSON 解析：跨块拼装与逐天产出 |
| `trip_stream.py` | 整段流式：边流边落地，产出 NDJSON 事件 |
| `workflow.py` | 图工作流的门面：生成 → 校验 → 修复循环 |

## 依赖方向（禁反向）

```
trip_stream ──┐
day_stream ───┼─→ workflow ──→ generators ──→ generation_core / poi_identity
              │      │            │  │  │
              │      │            │  │  └─→ budget / suggestions / reference_pool
              │      │            │  └────→ narrative / grounding / day_prompts
              │      └───────────────────→ formatting / reflect
              └──────────────────────────→ research（只读证据）
```

- **自上而下单向**：`stream → workflow → generators → generation_core`。上层可以调用下层，下层**不得** import 上层。
- `stream` 层（trip_stream / day_stream）负责编排与事件；`workflow` 负责图与循环；`generators` 及其兄弟模块负责"造内容"；`generation_core` 只做规则。
- `formatting/`（价格/事实/质量）与 `reflect.py`（校验）是 workflow 的**下游**，不得反过来 import 生成模块。
- 事件模型只认 `app/schemas/stream_events.py`：事件构造 → `to_wire`，别在业务代码里手搓键名。

## 参考实现

- **编排与降级**：抄 `research/`——子任务边界清晰、失败响亮降级、全程 trace 事件。
- **纯规则模块**：抄 `generation_core.py`——不 import 兄弟模块、函数式、可单测。
- **薄门面**：抄 `day_workflow.py`——只做转发与导出，不承载逻辑。
- **可 mock 性**：抄 `tool_registry.py` 的 handler 约定——被 patch 的函数经模块属性在调用期解析。

## 新增生成能力先抄谁

1. **新增一个纯计算规则**（住宿节奏/摊铺/折算）→ 放 `generation_core.py`，抄它的无依赖风格。
2. **新增一类"是不是同一个点位"的判定** → 放 `poi_identity.py`：名称归一与距离门槛只准有一份，否则去重与存在性判定会各说一套。
3. **新增一个约束句或档位** → 放 `budget.py` / `day_prompts.py`，抄 `budget_clause` 的"空输入返回空串"契约。
4. **新增一类备选池条目** → 放 `suggestions.py`，抄它的类别上限与地板守卫。
5. **新增一次 LLM 调用入口** → 放 `day_prompts.py`，抄 `llm_open_day` 的"未配置即抛、失败向上"口径。
6. **新增一条编排分支** → 放 `workflow.py` 的门面函数，抄 `day_workflow` 的图编排与 fallback 路由（节点不抛，一律路由到降级节点）。

## 拆分纪律

- **等积拆分，只搬不改**：函数体逐行搬移，不顺手"优化"；行为判据是流式快照（逐字节）与 eval ratchet（指标不降）。
- **不留包装层**：改换归属就直接迁移全部调用方，不保留 re-export 兼容壳（门面模块除外——门面本身就是公开面）。
- **可 mock 契约不许破**：把函数搬到新模块时，同步迁移测试的 `patch.object(<模块>, "<名字>")` 目标，保持"调用期解析"语义。
