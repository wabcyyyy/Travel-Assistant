# 生成链路模块蓝图（G-2.1）

> 本文件是 G-2.2~2.4 拆分的**验收依据**：只定义形状与依赖方向，不列清单。
> 新增生成能力时先读这里，再决定放哪一层。

## 一句话职责

| 模块 | 一句话 |
|---|---|
| `generation_core.py` | 纯规则骨架：摊铺、去重、预算估算、坐标几何——不 import 上面任何模块 |
| `budget.py` | 预算档位与约束句、餐价钳制、0 价补水 |
| `suggestions.py` | 备选池：候选组装、类别地板与上限、缺口补齐 |
| `reference_pool.py` | 参考资料池：把权威候选编成可引用的编号资料，并把模型引用落地回权威字段 |
| `generators.py` | 内容组装原语与对外面（纯函数优先，无编排） |
| `narrative.py` | 叙事字段清洗：限值截断、类型降级、指令残留剥离 |
| `grounding.py` | 事实落地：坐标校验与本地权威补点 |
| `day_prompts.py` | Prompt 组装：系统提示绑定、约束句拼装、日/整段两种入口的 LLM 调用 |
| `day_stream.py` | 单日链路：一次生成的编排与落地（反思/重试不在此） |
| `day_workflow.py` | 单日图的门面 |
| `stream_parser.py` | 流式 JSON 解析：跨块拼装与逐天产出 |
| `trip_stream.py` | 整段流式：边流边落地，产出 NDJSON 事件 |
| `workflow.py` | 图工作流的门面：生成 → 校验 → 修复循环 |

## 依赖方向（禁反向）

```
trip_stream ──┐
day_stream ───┼─→ workflow ──→ generators ──→ generation_core
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

1. **新增一个纯计算规则**（摊铺/去重/折算）→ 放 `generation_core.py`，抄它的无依赖风格。
2. **新增一个约束句或档位** → 放 `budget.py` / `day_prompts.py`，抄 `budget_clause` 的"空输入返回空串"契约。
3. **新增一类备选池条目** → 放 `suggestions.py`，抄它的类别上限与地板守卫。
4. **新增一次 LLM 调用入口** → 放 `day_prompts.py`，抄 `llm_open_day` 的"未配置即抛、失败向上"口径。
5. **新增一条编排分支** → 放 `workflow.py` 的门面函数，抄 `day_workflow` 的图编排与 fallback 路由（节点不抛，一律路由到降级节点）。

## 拆分纪律

- **等积拆分，只搬不改**：函数体逐行搬移，不顺手"优化"；行为判据是流式快照（逐字节）与 eval ratchet（指标不降）。
- **不留包装层**：改换归属就直接迁移全部调用方，不保留 re-export 兼容壳（门面模块除外——门面本身就是公开面）。
- **可 mock 契约不许破**：把函数搬到新模块时，同步迁移测试的 `patch.object(<模块>, "<名字>")` 目标，保持"调用期解析"语义。
