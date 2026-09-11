# 多 Agent 升级方案：领域研究 Agent + Supervisor 整合生成

> 状态：**阶段一（骨架）、阶段二（LLM 推理循环 + 缺口补查）、阶段三（指标/评测/README）已全部实施**。
> 定位：求职演示级——架构亮点清晰、链路可跑通、可评测可复现；明确不做 Agent 间自由通信/辩论、持久化记忆、去中心化编排。

---

## 一、目标与口径

把现有"单 Agent + 工具调用"升级为**领域研究 Agent + Supervisor 整合生成**的分工架构：

- 三个领域研究 Agent（**酒店 / 景点 / 美食**）：各自负责"证据收集"，产出结构化**证据包 EvidencePack**；
- Supervisor（**整合生成 Agent**）：需求分解 → 并行派发研究 → 汇总证据生成行程 → 校验缺口 → 再派发补查；
- **口径不变（LLM-only）**：行程内容 100% 由 Supervisor 的 LLM 生成；研究 Agent 只产证据，知识库/高德始终是证据面，绝不直接拼装行程。

## 二、总体架构

```
用户请求
   │
   ▼
┌─────────────────────────────────────────────────────┐
│  Supervisor（整合生成 Agent，兼任主控）               │
│  ① 需求分解 → 生成三个研究任务（ResearchTask）        │
│  ② 并行派发（线程池 fan-out / fan-in） ────────────┐  │
│  ③ 收齐证据包 → 整合为上下文 → 注入 LLM 生成行程     │  │
│  ④ reflect 校验 → 发现缺口 → 再派发对应研究 Agent    │  │
│  ⑤ format_output 事实落地 / 预算 / 质量报告          │  │
└──────────────┬──────────────────────────────────────┘
               │ 并行
      ┌────────┼────────┐
      ▼        ▼        ▼
┌─────────┐┌─────────┐┌─────────┐
│ 酒店研究 ││ 景点研究 ││ 美食研究 │
│  Agent  ││  Agent  ││  Agent  │
│  search_││ search_ ││ search_ │
│  hotels ││attr/food││  foods  │
└─────────┘└─────────┘└─────────┘
  各输出「证据包 EvidencePack」→ 回 Supervisor
```

## 三、核心设计

### 1. 统一契约

**ResearchTask**（研究任务卡）：`{domain, city, preferences, budget, hotel_tier, limit}`——Supervisor 分解后派发给各研究 Agent 的输入。

**EvidencePack**（证据包）：`{domain, items, confidence, rounds, gaps, degraded}`——研究 Agent 的唯一输出，也是证据流的载体：

| 字段 | 含义 |
|---|---|
| `items` | 检索到的 POI 列表（沿用现有 POI 契约字段） |
| `confidence` | 检索置信度（权威库条目占比） |
| `rounds` | 实际检索轮数（阶段一恒为 1，阶段二随 LLM 循环增长） |
| `gaps` | 自查出的缺口描述（如"候选酒店不足"） |
| `degraded` | 是否降级（检索异常/结果为空） |

### 2. 三个研究 Agent：一个工厂，三个实例

**不写三份相似编排**（代码审计报告点名过"三份相似编排并存"）。用参数化工厂 `build_research_graph(domain)`，`DomainConfig` 只描述差异：

| 维度 | 酒店 Agent | 景点 Agent | 美食 Agent |
|---|---|---|---|
| 检索工具 | `search_hotels` | `search_attractions` | `search_foods` |
| 硬约束 | 保留完整可枚举候选集（酒店不走向量 Top-K） | 偏好标签展开 | 必须具体餐厅店名 |
| 阶段二 LLM 推理 | 判断预算档→决定查哪几档 | 判断偏好→决定检索词组合 | 判断菜系→决定检索词 |

工具函数一律**运行时经 `tools` 模块属性解析**（`getattr(tools, tool_name)`），保证单测注入（`patch.object(tools, ...)`）持续生效。

### 3. Supervisor

- **分解**：读取 `GenerateRequest` → 三个 `ResearchTask`；
- **并行派发**：模块级 3-worker 线程池 + `contextvars.copy_context()` 传播 trace 上下文（保证研究 Agent 的工具轨迹挂到本次运行）;
- **单域容错**：任一研究 Agent 异常 → 该域降级为 `degraded=True` 空证据包，**不阻塞**其余域与整合；
- **整合**：三份证据包映射回现有上下文契约 `{candidates, foods, hotels, consumption}`（下游 generate/format 零改动）；
- **补查（阶段二）**：reflect 校验不过时，Supervisor 只重派发对应域研究 Agent，而非整体重生成。

### 4. 与现有链路衔接

- 外部契约（`/v1/generate`、`/v1/generate-day`）**完全不变，Java 侧零改动**；
- 整段生成：`workflow.research` 节点内部改为 Supervisor 研究（图节点已由 `search` 更名 `research`）；
- 逐日路径：`plan-context` 复用 Supervisor 产出上下文；
- `registry` 的 `search_pois` 工具保留（`local_replan`、function-calling 仍在使用）。

### 5. 预算 / 可观测 / 评测（演示级）

| 维度 | 设计 |
|---|---|
| 降级 | 子域异常 → degraded 证据包；研究阶段整体失败 → 回退现有开放模式行为 |
| 可观测 | trace 前缀分域（`research.hotel/attraction/food`）；`research_summary` 决策事件记录各域证据包统计 |
| 评测 | eval_research.py（按域证据质量 + 补查有效率）+ eval_agent 研究指标 + test_research_eval 回归 |

## 四、实施路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| 一 | EvidencePack/ResearchTask 契约 + 研究 Agent 工厂（确定性检索）+ Supervisor 接入 workflow / plan-context | ✅ 已实施 |
| 二 | 子 Agent 加"规划-检索-评估-补查"LLM 循环；Supervisor 缺口再派发动态边 | ✅ 已实施 |
| 三 | 指标（研究规模/轮次/降级/补查）+ 评测（按域证据质量 + 补查有效率）+ README | ✅ 已实施 |

### 阶段二实现细节

- 研究子图升级为 `plan_query → search → evaluate → (finalize | refine→search)`：
  - `plan_query`（LLM，`reasoning.plan_research`）：输出扩展偏好/补充关键词/检索规模；
  - `evaluate`（LLM，`reasoning.evaluate_research`）：判定证据充分性，不足给补充词；
  - 轮次上限 `RESEARCH_LLM_ROUNDS=2`：补查轮直接收尾，不重复评估（省一次模型调用）；
  - 证据为空时评估**确定性判定不足**（不调模型），默认补充词经高德并入；
  - 任何 LLM 异常回退确定性默认值，绝不阻塞研究。
- Supervisor 缺口补查：`workflow` 新增 `refill_research` 节点与 `refill` 路由——
  reflect 校验发现"证据型缺口"（当前为"未安排任何景点"→ 景点域）时，只重派发该域
  研究 Agent（`run_refill`：扩大规模+扩展偏好）合并证据后重新生成，补查预算 `MAX_REFILLS=1`。
- LLM 推理函数在 `app/agent/research/reasoning.py`，模块级可 patch；子图内一律
  运行时经 `reasoning`/`tools` 模块属性解析，单测注入契约统一生效。

### 阶段三实现细节

- **指标**：`observability.MetricsRegistry` 新增 `research_items/research_rounds/
  research_degraded/research_refills`；Supervisor `synthesize` 统一上报证据规模/
  推理轮次/降级包数，`refill` 路由上报补查次数，随 `/v1/metrics` 与 Prometheus 透出。
- **评测**：
  - `tests/agent_eval/eval_research.py`：按域证据质量（规模/置信度/轮次/降级/缺口）
    + Supervisor 补查有效率（首轮空 → 补查可合并），输出 JSON/MD 报告；
  - `eval_agent.py` 报告新增 `research_rounds_avg` / `research_pack_avg`（从 schedule_report 汇总）；
  - `tests/agent_eval/test_research_eval.py` 确定性回归断言。
- **README**：P3 演进行 + 核心取舍第 9 条（多 Agent 只做证据分工不做内容分工）+ 功能特性 +
  测试与评测表；图节点 `search` 更名 `research` 保持叙事与代码一致。

## 五、风险与取舍

- **延迟**：并行研究 ≈ 最慢子域 → 复用语义缓存吸收重复查询；
- **成本**：阶段二起子 Agent 调 LLM 增加 → 研究轮次上限 2 轮 + 使用 `llm_fast_model`；
- **一致性**：三域证据可能地理矛盾 → 整合 prompt 按地理位置约束 + reflect 路线校验兜底（已有）；
- **明确不做**：Agent 间自由通信/辩论、持久化记忆、去中心化编排。

## 六、目录结构

```
app/agent/research/
  __init__.py    # 对外导出 run_research / run_research_context / run_refill / merge_candidates
  evidence.py    # ResearchTask / EvidencePack 契约
  reasoning.py   # 研究 LLM 推理：plan_research（检索规划）/ evaluate_research（充分性评估）
  domains.py     # 三域 DomainConfig（工具名 / 参数映射 / 缺口判定）
  factory.py     # build_research_graph(domain) + run_research(task)（规划-检索-评估-补查循环）
  supervisor.py  # decompose / run_research_parallel / synthesize / run_refill / merge_candidates
```

## 七、验证口径

- 新增 `tests/test_research_agents.py`：证据包结构 / Supervisor 整合映射 / 单域故障容错 /
  LLM 推理循环（规划扩展、评估补查轮次）/ 缺口补查端到端 / workflow 接入冒烟；
- 既有单测全绿（研究 LLM 推理函数与 search 工具统一经模块属性解析，测试 patch
  `tools.search_*` 与 `reasoning.plan/evaluate_research`）；
- `pytest --ignore=tests/api`（当前 **211 passed**）、`mvn -q compile`、`npm run build`。
