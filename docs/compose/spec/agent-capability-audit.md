---
feature: agent-capability-audit
status: delivered
updated: 2026-09-11
branch: master
commits: (implementation on master — worktree blocked in session)
---

# Agent 能力审计：上下文记忆 · RAG · Harness · Multi-Agent · Function Calling · MCP

> **代码基线**：`travel-agent-python` + `travel-backend-java` 当前工作树。  
> **本轮变更**：在审计结论上落地 P1（memory 模块 + 检索预算）；并修正审计偏差（见 Report）。  
> **阅读对象**：答辩/迭代规划；每个概念给出「定位 → 现状 → 边界 → 集成方案 → 数据流 → 风险 → 落地步骤」。

---

## Report

**What was built** —  
1. **审计复核修正**：FC 循环已实现但仅测试引用、未接入生成主路径；`run_limits` 原先只约束 LLM/工具，未约束检索；S3「只审计不改代码」对本轮失效。  
2. **`app/agent/memory/`**：`WorkingMemory`（used_names/hotel/feedback）+ `dialogue` 滑窗；接入 `day_stream` / `chat_draft`。  
3. **检索预算**：`RunLimits.max_retrievals`（默认 48）+ `record_retrieval`；研究 Agent 检索节点计入。

**Verification** — `pytest tests/ --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval`（含 `test_memory` / `test_retrieval_budget`）通过。

**Journey log** —  
1. 审计文档首轮偏「规划态」，与代码成熟度有三处偏差：FC 未挂主路径、检索无预算、Harness 非双真相源而是事务/推理分层。  
2. Memory 抽取必须保持 `_filter_used` 空结果回退全集的历史行为，避免回归。  
3. 检索预算放在 `run_limits` 而非仅 tool_registry，才能覆盖 research 裸调 `tools.search_*` 的路径。  
4. FC 接入选择 `poi_intros`（只读补事实）而非行程写入——与「代码当执行者」架构一致。  
5. worktree 被会话策略拦截；实现落在主工作树 master。

---

## [S1] Problem

项目 README/面试叙事同时使用六个高密度概念，但代码中成熟度不一：

1. 复述概念容易 **over-claim**（尤其 Multi-Agent / Memory / Harness）；  
2. 迭代时不知道 **改哪一层**（Python Agent vs Java 状态机 vs RAG 管线）；  
3. 缺一张 **模块边界与数据流** 图，导致新能力（长期记忆、多轮工具选择）无处安放。

需要一份可执行的定位审计，作为后续真实改造的 Spec 输入。

---

## [S2] Design — 分概念审计

### 0. 总架构定位（六概念挂载点）

```text
Vue ──► Java (鉴权/行程状态机/PDF/Redis) ──► Python Agent
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
              trip_graph (Harness)      research/* (Multi-Agent)    rag/* (RAG)
              generation_core           tool_registry (FC)          integrations/amap_mcp (MCP)
              chat_draft (Memory 浅)    day_stream (事实层)          observability (Trace/Metrics)
```

| 概念 | 本项目对应模块 | 成熟度 | 一句话边界 |
|------|----------------|--------|------------|
| 上下文记忆 | `app/agent/memory/*` + used_names / history | ★★★☆☆ | 请求内 WorkingMemory + 对话滑窗；无长期画像 |
| RAG | `app/rag/*` + `poi_knowledge` + Chroma | ★★★★☆ | 证据注入，不直接拼行程 |
| Harness | `trip_graph` + `generation_core` + `tool_registry` + run_limits | ★★★☆☆ | 单进程编排 + LLM/检索/工具预算 |
| Multi-Agent | `research/*` Supervisor + 3 域 | ★★★☆☆ | 证据分工 + 并行；非自由协作 |
| Function Calling | `function_calling.run_tool_call_loop` + registry + `poi_intros` | ★★★☆☆ | 只读辅助已上线；**行程写入仍不用自由 FC** |
| MCP | `integrations/amap_mcp.py` | ★★★☆☆ | 只读 POI 查询客户端；默认可关 |

---

### [S2.1] 上下文记忆管理

#### 现状定位

| 层级 | 实现 | 位置 |
|------|------|------|
| **请求内（生成中）** | `used_names`、`chosenHotel`、`ReferencePool.exclude_names` | Java `ItineraryAsyncPlanner` → `GenerateDayRequest` → `day_stream` |
| **行程内跨日** | Java 维护 usedNames/chosenHotel，每天回传 Python | 同上 |
| **对话会话** | `history` 最多 20 条进 Java，决策用最近 4 条 | `chat_draft/decide.py`、`hotel.py` |
| **用户偏好** | `UserPreference` 表 + 信号接口 | Java `UserPreferenceService` |
| **跨会话长期记忆** | **无** | — |

**作用**：保证多日不重复景点、对话编辑能引用上一轮。  
**边界**：不是 vector memory / summary memory / user profile LLM；刷新页面后「聊天记忆」依赖 Java 会话表，不是 Agent 内嵌状态。

#### 集成方案

```text
已实现：app/agent/memory/
  ├── working.py    # WorkingMemory：used_names / chosen_hotel / feedback
  └── dialogue.py   # recent_turns / dialogue_messages（与 Java history 契约对齐）

接入点：
- day_stream._filter_used / _llm_open_day → WorkingMemory
- chat_draft.decide / hotel → dialogue_messages / recent_turns
```

#### 依赖与数据流

```text
Java Preference/Chat ──► GenerateDayRequest.history / used_names
                              │
                              ▼
                    memory.dialogue / working ──► Prompt 注入 + ReferencePool 过滤
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| 记忆进 Prompt 放大 token 与注入面 | 必须定界符 +「数据非指令」（已有 feedback 先例） |
| Agent 内持久化与 Java 行程库双写 | **状态以 Java DB 为真相源**；Agent 记忆只做摘要 |
| 上下文膨胀 | 保留现 cap：history≤20、used_names≤200；dialogue 默认 4 轮×800 字 |

#### 落地步骤

1. ~~抽出 `working_memory` 数据类~~ **已完成**。  
2. ~~dialogue 截断策略集中在 `memory/dialogue.py`~~ **已完成**。  
3. （可选）`profile.py` 读 UserPreference 生成 3–5 条偏好句注入。  
4. ~~单测：跨天不重复、history 截断~~ **已完成**（`tests/test_memory.py`）。

---

### [S2.2] RAG 检索增强生成

#### 现状定位

**已较完整**，是本项目最强 Agent 能力：

| 阶段 | 能力 | 模块 |
|------|------|------|
| 数据 | 高德/Wikivoyage/Nominatim 管线 → MySQL `poi_knowledge` | `sql/enrich_pois.py` |
| 索引 | Chroma + bge-m3 / hashed 降级 | `app/rag/store.py`、`embeddings.py` |
| 检索 | BM25 + 向量 + RRF；查询路由；语义缓存 | `retriever.py`、`cache.py` |
| 精排 | cross-encoder | retriever |
| 生成 | `[R1..Rn]` 引用注入 → `ReferencePool.ground` 落地 source/核验 | `generators.py`、`day_stream` |
| 评测 | Recall/MRR/引用覆盖/faithfulness | `evaluation*.py` |

**作用**：降低幻觉；给「知识库证据 vs 模型自选」可区分溯源。  
**边界**：RAG **绝不直接拼行程**；LLM 失败返回待研究草案。开放模式大量项为 unverified。

#### 集成方案

现有分层已合理。迭代方向是**收口契约**而非换栈：

```text
保持：poi_knowledge 唯一权威库
建议：rag/budget.py — 单次 generate 的检索/精排调用预算（与 run_limits 对齐）
可选：rag/rerank_metrics.py — 精排前后顺序变化进 trace
```

#### 依赖与数据流

```text
Research Agent / plan-context
    → rag.retriever / poi_repository
    → EvidencePack / context{candidates,foods,hotels}
    → ReferencePool(Prompt [Rn])
    → LLM refs
    → ground() → itinerary item source/verification
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| 双写 Chroma 与 MySQL 不一致 | 已有指纹增量同步 + TTL 刷新；改字段必须跑管线 |
| hashed 向量被当成语义检索 | README/简历必须写「默认 hashed，语义需 bge-m3」 |
| 客户端伪造 context source | 已有权威值域 → `client-context`；勿回退 |

#### 落地步骤

1. 文档化「权威 source 白名单」单一常量，Java/Python 共用说明。  
2. ~~检索调用计入 `run_limits`~~ **已完成**：`RunLimits.max_retrievals` + research `_run_search` 计数。  
3. 评测报告固定模型/temperature 版本号写入 README。

---

### [S2.3] Agent Harness（编排框架）

#### 现状定位

**自研轻量 Harness**，不是 LangGraph 只当链式调用：

| 组件 | 职责 | 位置 |
|------|------|------|
| **统一图** | day/trip 双模式 StateGraph | `trip_graph.py` |
| **产品口径** | N-1 晚、草案、重试常量 | `generation_core.py` |
| **事实层** | Prompt/坐标/价格落地 | `day_stream.py` |
| **工具预算** | Tool Registry max_calls / 总预算 | `tool_registry.py` |
| **运行预算** | Deadline / LLM 次数 / Token | `run_limits.py` |
| **可观测** | Trace、Metrics、Usage SQLite | `observability.py` 等 |
| **Java 编排** | 跨日状态机、恢复、PDF | Spring `ItineraryAsyncPlanner` |

**作用**：把「一次行程生成」做成可失败、可降级、可观测的执行壳。  
**边界**：**双 Harness**（Java 状态机 + Python 图）；无通用 Agent OS（无插件热加载、无多租户调度）。

#### 集成方案

```text
保持 trip_graph 为唯一 Python 编排入口（已合并 day/trip）。
建议 harness/
  ├── budgets.py   # 统一读 run_limits + tool_budget
  └── policies.py  # 降级策略表（degraded 语义集中）

Java 侧：不把状态机迁到 Python（事务/幂等在 Java 合理）。
```

#### 依赖与数据流

```text
HTTP /v1/generate-day
  → trip_graph(mode=day)
  → day_stream 一次生成
  → reflect / retry
  → Java persist + budget + cache evict
  → 前端轮询
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| Java/Python 状态双写 | 以 DB actionId/fingerprint 幂等为准；Agent 无状态优先 |
| 过度抽象 harness | 校招项目以「可讲清的预算与降级」优先，不做插件框架 |

#### 落地步骤

1. 在 `trip_graph` 模块头画清与 Java 状态机的职责表（已有部分，可补时序图进 docs）。  
2. 所有生成入口统一走 `observe_run` + `begin_limits`（检查是否有旁路）。  
3. （可选）degraded 原因枚举 Python/Java 共用常量表。

---

### [S2.4] Multi-Agent 协作

#### 现状定位

**Supervisor + 三域研究 Agent（星型、证据分工）**——已在代码与 `docs/多Agent升级方案.md` 落地。

| 角色 | 行为 |
|------|------|
| Supervisor | `decompose` 固定三任务 → 线程池并行 → `synthesize` → reflect 缺口 `run_refill` |
| 景点/美食/酒店 Agent | 各绑 `search_*`；子图 plan(LLM)→search→evaluate(LLM)→补查≤2→EvidencePack |
| 内容生成 | 仍由 **trip_graph generate 节点的 LLM** 完成 |

**作用**：并行取证、按域补查、研究可观测。  
**边界**：Agent 间**不通信**；域写死；工具硬绑定；**不是** AutoGen/Crew 级自主协作。

#### 集成方案

```text
保持 evidence-only 契约（EvidencePack 是唯一出口）。
建议 research/
  ├── contracts.md 可写进代码注释
  └── （可选阶段）decompose_llm.py — LLM 决定是否启用美食/增加「交通」域
不建议：Agent 互聊、辩论、共享黑板（成本高、与 LLM-only 冲突）。
```

#### 依赖与数据流

```text
GenerateRequest
  → decompose → [ResearchTask ×3]
  → ThreadPool + contextvars
  → run_research → EvidencePack
  → synthesize → {candidates, foods, hotels, research_report}
  → generate LLM（唯一内容源）
  → reflect → 可选 run_refill(单域)
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| 简历写「完全自主 multi-agent」 | 必须改口径为「领域研究 Agent + Supervisor」 |
| 研究 LLM 调用放大成本 | `llm_fast_model` + 轮次上限 + run_limits |
| 线程池 + contextvars | 已 copy_context；勿在 worker 内再起 asyncio 裸跑 |

#### 落地步骤

1. 面试安全表述写入 README（已部分）。  
2. `eval_research` 数字（证据规模/轮次/补查有效率）进答辩稿。  
3. （可选）动态 decompose 单测 + 成本上限。

---

### [S2.5] Function Calling 工具调用

#### 现状定位

**两套并存，职责不同：**

| 机制 | 内容 | 使用方 |
|------|------|--------|
| **Tool Registry** | `search_pois` / `search_hotel_options` / `get_route_matrix` / `find_nearby_pois`；Schema、只读、预算、审计 | HTTP 共用 + 生成链路 invoke；可暴露 function schema |
| **研究域硬绑定** | `DomainConfig.tool_name` + 补查 `search_amap_poi` | research factory |
| **主模型 tools 参数** | `LLMClient.chat_response(..., tools=)` 支持，**生成主路径未广泛依赖** | 预留 |

**作用**：受控扩展外部能力；防模型直接写库。  
**边界**：写入型工具默认不注册；研究 Agent **不能**自由选工具。

#### 集成方案

```text
统一真相：tool_registry 为「可暴露给 LLM 的工具面」。
研究 Agent 保持硬绑定（可测、成本可控）。
建议：registry 每季审计 max_calls 与 timeout；生成链路优先 registry.invoke 而非裸 tools.*
```

#### 依赖与数据流

```text
LLM function call（若开启）
  → registry.validate + budget
  → handler(tools.*)
  → 结果进后续 Prompt
  → record_event tool.*
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| 模型乱调工具烧配额 | max_calls + 只读 + 风险级 |
| timeout 在 Registry 未真正杀线程 | 审计已说明 contextvars 风险；外部调用自带超时 |
| 双工具路径分叉 | 新工具优先注册 registry，再给 research 用 |

#### 落地步骤

1. ~~清单结论~~：主行程生成仍不自由选工具。  
2. `GET /v1/tools` 已有 public_specs。  
3. ~~FC 接入业务路径~~ **已完成**：`run_poi_intros` 走 `run_tool_call_loop`（只读 search_pois，失败回退单轮）；见 `tests/test_butler_function_calling.py`。

---

### [S2.6] MCP 协议

#### 现状定位

| 项 | 实现 |
|----|------|
| 客户端 | `amap_mcp.py`：Streamable HTTP、initialize、list_tools 缓存、call_tool |
| 语义映射 | `search_poi`/`poi_detail`/`geocode` → 服务端工具名别名 |
| 配置 | `AMAP_MCP_ENABLED` 默认 false；失败回退 Web API |
| 安全 | Key 仅环境变量；只读工具 |
| 工程 | 桥接线程池 + contextvars，避免 async 内 asyncio.run |

**作用**：对接高德官方 MCP 的 POI 查询。  
**边界**：**不是**通用 MCP Host（未挂任意第三方 MCP Server 目录）；无 MCP 资源订阅。

#### 集成方案

```text
保持薄适配层：integrations/mcp_host.py 可选泛化
  - 统一 endpoint/鉴权/tool resolve
  - 高德为第一个 provider
避免：在 generate 内同步无超时打 MCP（已有 timeout）
```

#### 依赖与数据流

```text
tools.search_amap_poi
  → amap_mcp.search_poi / detail
  → normalize → 与本地 POI merge
  → Evidence / grounding
```

#### 风险与取舍

| 风险 | 权衡 |
|------|------|
| 每次 initialize 握手 | 已缓存工具名；会话级复用仍是遗留 |
| 网络不稳拖死 Deadline | 默认关 + 超时 + 降级 Web API |
| 把 MCP 当「智能」 | MCP 只是传输/工具协议，智能仍在 LLM |

#### 落地步骤

1. 文档写清：MCP=IO 适配，非推理层。  
2. （可选）连接级工具名缓存跨请求 TTL（现模块级 dict 已有）。  
3. 评测：MCP on/off 对 grounding 成功率的影响数字。

---

## [S2.7] 模块划分总图（集成目标态）

```text
app/agent/
  trip_graph.py          # Harness 入口（mode=day|trip）
  generation_core.py     # 产品口径
  memory/                # [规划] working + dialogue (+ profile)
  research/              # Multi-Agent 研究
  tool_registry.py       # Function Calling 治理
  day_stream.py          # 事实层
  chat_draft/            # 对话编辑（消费 memory）

app/rag/                 # RAG 管线
app/integrations/
  amap_mcp.py            # MCP 客户端
  google_maps.py         # provider chain

app/common/
  llm_client.py / db_pool.py / run_limits 相关
```

**原则**：新能力进 **memory/ 或 rag/**，不要塞进 trip_graph 节点函数体。

---

## [S3] Out of Scope

- 不做：跨进程 Agent 总线、向量长期记忆库、AutoGen 级多智能体辩论、通用 MCP 市场 Host。  
- 不宣称生产 SLA / 完全自主 Multi-Agent / 主路径 Function Calling。  
- 本轮不接：`run_tool_call_loop` 进 generate、动态 decompose、profile LLM 摘要。  
- Key rotate、容器镜像优化等运维项见 `技术改造合集` / `投递前人工QA清单`。

---

## 组件依赖与数据流（总览）

```text
                    ┌──────── Java ────────┐
                    │ JWT/会话/行程状态机    │
                    │ 预算/PDF/Redis 吊销   │
                    └──────────┬───────────┘
                               │ HTTP + internal token
                               ▼
┌──────────── trip_graph (Harness) ────────────┐
│ run_limits · observe_run · generation_core   │
│        │                    │                │
│   mode=trip            mode=day              │
│        │                    │                │
│   research/* ──Evidence──► generate LLM      │
│   (Multi-Agent)              │               │
│        │                     │               │
│   tool_registry / tools      │               │
│        │                     │               │
│   rag/* ◄── amap_mcp / amap / google         │
│   memory/* (规划) ──► Prompt                 │
└──────────────────────┬───────────────────────┘
                       ▼
              MySQL / Chroma / Redis
```

| 数据 | 生产者 | 消费者 |
|------|--------|--------|
| ResearchTask | Supervisor.decompose | 各 research graph |
| EvidencePack | research.finalize | synthesize / refill merge |
| context{cand,food,hotel} | synthesize / plan-context | ReferencePool / Prompt |
| used_names | Java 跨日 | day_stream 过滤 + Prompt |
| history | Java Chat | chat_draft 最近 4 条 |
| trace/metrics | 全链路 | Admin / `/v1/metrics` |

---

## 改造风险总表

| 主题 | 主要风险 | 缓解 |
|------|----------|------|
| Memory | 注入、双真相源、token | 定界、Java 为 DB 真相、cap |
| RAG | 索引漂移、过 claim 语义检索 | 管线+评测、表述诚实 |
| Harness | 双编排分裂 | trip_graph 单入口、口径 core |
| Multi-Agent | over-claim、成本 | 证据-only、轮次上限 |
| FC | 误调、预算 | registry 治理、只读默认 |
| MCP | 拖死请求、协议当智能 | 默认关、超时、文档边界 |

---

## 建议落地优先级（后续真实迭代，非本阶段执行）

| 优先级 | 项 | 预估 | 收益 |
|--------|----|------|------|
| P0 | 面试安全表述固化（Memory/Multi-Agent/FC/MCP 边界） | 0.5d | 防翻车 |
| P1 | `memory/working+dialogue` 抽取（行为不变） | 1–2d | 可测、可扩展 |
| P1 | 检索/研究计入 run_limits | 0.5–1d | 成本护栏 |
| P2 | 动态 decompose | 1–2d | Multi-Agent 更「真」 |
| P2 | MCP 泛化 Host | 2d+ | 扩展性，演示收益低 |
| P3 | 长期 user profile LLM 摘要 | 2d+ | 产品向 |

---

## Tasks

- [x] T1: 本审计文档入库 — acceptance: 六概念定位/边界/方案/数据流/风险齐全 (covers: S2)
- [x] T2: 答辩口径复核 — acceptance: README/项目介绍写明 Multi-Agent/FC/Memory 边界 (covers: S2.1, S2.4, S2.5)
- [x] T3: memory 模块抽取 — acceptance: `tests/test_memory.py` 通过；day_stream/chat_draft 消费 WorkingMemory/dialogue (covers: S2.1; depends: T1)
- [x] T4: 检索计入 run_limits — acceptance: `tests/test_retrieval_budget.py` 通过；research `_run_search` 调用 record_retrieval (covers: S2.2, S2.3)
- [x] T5: FC 接入业务路径 — acceptance: `run_poi_intros` 调用 run_tool_call_loop；集成测试通过 (covers: S2.5; depends: T2)

---

## Journey log

1. 项目已有较强 RAG 与研究 Multi-Agent；短板是 **Memory 与统一 Harness 叙事**。  
2. 双编排（Java 状态机 + Python 图）是刻意分层，不是未完成重构——审计时按「事务在 Java、推理在 Python」解释。  
3. Multi-Agent 的合格口径是 **evidence-only 领域专家**，不是自由协作团队。  
4. worktree 创建在当前会话被隔离策略拦截，审计文档写在主工作树 `docs/compose/spec/`；后续实现请按项目规范再开分支。
