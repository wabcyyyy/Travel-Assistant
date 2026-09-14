# travel-agent-python

AI Agent 服务：接收后端行程生成/调整请求，通过 LangGraph 工作流调用 LLM（千问兼容模式）生成行程，并通过高德官方 MCP 获取外部事实。生成采用 **LLM-only 原则**：行程内容 100% 由 LLM（开放模式）生成，权威知识库以编号参考资料注入 Prompt 只作**证据**——命中项落地权威字段与溯源，未命中项显式标记待复核；LLM 失败时如实返回待研究草案，绝不以知识库候选拼装行程冒充生成结果。

生产主链路为**整段流式生成**（`/v1/generate-stream`）：一次 LLM 调用生成整趟行程（模型看得见全盘，跨天重复与片区走回头路在源头收敛），流式增量解析 `daily_plans` 数组，每解析出一个完整天立即做引用落地/坐标补齐/双通道去重（归一化同名 + 落地坐标 <80m），以 JSON Lines 逐天下发；`/v1/generate`（整段非流式，走同一张 LangGraph 图）用于直接调用与离线评测，`/v1/generate-day` 供编排器做恢复续跑与缺天修复。

## 技术栈

- Python 3.12（uv 管理依赖）
- FastAPI 0.111 + Uvicorn
- LangGraph 0.2.44 + LangChain Core
- Qdrant（向量检索库；本地嵌入式持久化默认起跑，`QDRANT_URL` 可切独立服务；索引可随时由 MySQL 全量重建）
- PyMySQL（读 MySQL 权威 POI 库）
- 高德官方 MCP Server（Streamable HTTP，可选）

## 工作流（LangGraph）

```
parse ──► research ──► generate ──► reflect ──► format
                 │                       │
                 └───── 失败/重试/补查 ───┘

research 节点（多 Agent 研究层）：Supervisor 并行派发 酒店/景点/美食 三个研究 Agent
  （LLM 规划检索策略 → 工具检索 → 评估充分性 → 不足补查一轮），输出证据包 EvidencePack；
  校验发现"无景点"类证据缺口时只重派发对应研究 Agent 补查。

generate 内部（LLM-only，知识库只作证据）：
  开放模式（唯一路径）：LLM 知识选点 + 权威参考资料[Rn]注入 → refs 引用落地 → 坐标 provider chain
  失败降级：           重试一次 → 仍失败返回"待研究草案"（绝不以知识库拼装行程）
```

- `parse`：意图解析（城市/天数/偏好/预算）
- `research`：多 Agent 研究编排 —— 三域研究 Agent 并行收集证据（RAG 混合检索 + 高德→Google→Nominatim 地理兜底），Supervisor 汇总证据包并驱动证据型缺口补查
- `generate`：开放模式为主；权威参考资料命中项落地为 `partially_verified/observed` 并回填真实 `source`，模型自选点标 `unverified/before_departure`（国外坐标经 Nominatim 落真实值）
- `reflect`：校验时间冲突 / 营业时间覆盖 / POI 间路线可达性 / 日饱和度 / 景点存在性，`needs_fix` 时最多 2 轮修正，输出 `validation_log`
- `format`：结构化输出 + 确定性预算重算（门票按选中票价、餐饮按选中餐厅人均、酒店走实时价→季节系数定价链）

每次混合检索写入脱敏 Trace 事件 `retrieval/poi.hybrid_search`（含路由路径、provider、模型版本、候选数、精排耗时、fallback 标记），缓存命中写 `retrieval/cache_hit`；可通过 `X-Agent-Run-ID` 追踪完整检索链路。

## RAG 层（app/rag）

- **数据**：MySQL `poi_knowledge` 权威库（2142 条/6 城，`sql/enrich_pois.py` 三源管线灌入）→ SHA256 `content_fingerprint` 增量同步 Qdrant；embedding/文档版本变化触发全量重建防向量混模
- **检索**（retriever.py）：语义召回（默认本地 bge-small-zh-v1.5，可换 bge-m3；依赖/模型不可用时响亮降级 hashed）+ BM25 词法召回 → RRF 融合 → 业务重排 → 精排（默认关闭，可选 cross-encoder，窗口 24 条，`0.7×精排+0.3×业务分`）；前置查询路由——无意图查询（仅城市+品类泛词）走评分枚举、精确名走词法直查、有意图才走向量+精排，路由只改路径不改权威边界
- **缓存**（cache.py）：精确键 + 同签名桶内语义近似（cosine≥阈值）两级命中；TTL/LRU/`index_version` 整体失效；降级结果与空结果不缓存
- **近邻图**（graph.py）：城市→0.02° 网格→haversine 精滤的空间层 + 标签倒排层，支撑「附近推荐」与 `same_tag` 同类推荐；坐标缺失不入图
- **评测**（evaluation.py / evaluation_generation.py）：检索侧 Recall@k/MRR/nDCG/权威引用率；生成侧引用覆盖率/refs 有效率/资料利用率 + LLM-judge 忠实度（`python -m app.rag.evaluation_generation 杭州` 可直接跑真实链路）

## 目录结构

```
main.py                # 入口（启动时 warmup 并增量同步 RAG 索引）
app/
├── api/agent.py       # 全部 HTTP 端点（生成/编辑/对话/附近推荐/指标/Trace）
├── agent/             # workflow / research(多Agent研究层) / trip_stream(整段流式生成) / day_stream(开放模式事实层) / generators(ReferencePool) / reflect / tools / tool_registry / observability
├── rag/               # retriever(混合检索+路由+精排) / store(同步+缓存+图) / vector_collection(Qdrant) / cache / graph / embeddings / evaluation(_generation)
├── common/            # config(.env) / llm_client / season
└── schemas/           # trip（含 FactEvidence/SourceRecord 溯源模型）/ common
sql/enrich_pois.py     # 数据管线（国内 高德+Wikivoyage / 国外 Nominatim+Wikivoyage → 清洗 → 增量 upsert）
tests/
├── test_*.py          # 393 条离线单测（检索/路由/缓存/图/引用落地/跨天双通道去重/流式解析/白名单/反思/安全编辑/多 Agent 研究/国外地理兜底/审计修复回归）
├── api/               # 接口自动化（打 Java 8081 测试库）
├── agent_eval/        # 检索/研究/Agent/LLM 四套评测 + 失败回放 + 基线消融
└── perf/load_test.py  # 性能压测
```

## 启动

```bash
cp .env.example .env   # 填入 LLM_API_KEY、DB_PASSWORD
uv sync                # 安装运行时依赖（含 Qdrant 客户端与语义 embedding 依赖）
uv run python scripts/fetch_rag_model.py  # 首次：预置 RAG 语义模型（国内可设 HF_ENDPOINT=https://hf-mirror.com）
uv run python main.py  # 127.0.0.1:8000，默认不开启 reload
```

环境变量（`.env`）：`LLM_BASE_URL`（默认 dashscope 兼容模式）、`LLM_API_KEY`、`LLM_MODEL`（默认 qwen-plus）、`LLM_FAST_MODEL`（内容生成统一模型：行程/景点介绍/研究/对话决策；qwen-turbo 省钱但对篇幅类软约束遵循差，推荐 qwen-plus，留空复用 `LLM_MODEL`）、`LLM_TIMEOUT`（批量生成 200-300 字介绍时输出可达 4000+ token，建议 ≥240）、`DEFAULT_BUDGET`、`DB_*`、`AGENT_INTERNAL_TOKEN`（配置后保护生成/编辑接口；`AGENT_HOST` 绑定非回环地址且未配置 token 时启动直接报错，留空仅适合本机回环开发）、`AGENT_RELOAD`（开发环境可设为 `true`）。向量库（Qdrant）：`QDRANT_URL` 为空默认走本地嵌入式持久化（`QDRANT_PATH`，启动自动从 MySQL 全量重建），配置后（如 `http://localhost:6333`，`docker compose up -d qdrant`）切独立服务；`QDRANT_COLLECTION`、`QDRANT_TIMEOUT` 控制集合名与超时。选型依据与升级触发条件见 `../docs/ADR-0001-向量库选型-Qdrant.md`。RAG 默认使用 `RAG_EMBEDDING_PROVIDER=semantic` 的本地 bge-small-zh-v1.5 语义向量（首次需执行 `uv run python scripts/fetch_rag_model.py` 把模型预置到 `RAG_MODEL_CACHE_DIR`，服务运行期不联网下载；国内可设 `HF_ENDPOINT=https://hf-mirror.com`）；依赖或模型不可用时自动降级为 `hashed` 哈希/词法特征，启动日志有显式告警、索引遥测带 `fallback` 标记。`RAG_EMBEDDING_MODEL`、`RAG_MODEL_CACHE_DIR` 控制模型与缓存目录；精排默认关闭（`RAG_RERANK_PROVIDER=none`），需要时下载对应模型（`--rerank`）并开启。`RAG_TOP_K`、`RAG_RRF_K` 控制候选数量和 RRF 常数，`RAG_DOCUMENT_VERSION` 变化会触发全量重建，`RAG_REFRESH_SECONDS`（默认 60）控制索引惰性增量刷新周期——数据管线跑完后服务自动感知，无需重启。表结构由 Java 后端的 Flyway 迁移创建（`travel-backend-java/src/main/resources/db/migration/`：空库执行 V1 基线、既有库打基线跳过 V1 只跑后续 V2+），无需手工执行建表/增量 SQL；Flyway 之前的历史增量脚本留档于 `../sql/archive/`。启用高德官方 MCP 时配置 `AMAP_MCP_ENABLED=true`、`AMAP_MCP_URL=https://mcp.amap.com/mcp` 和服务端密钥 `AMAP_MCP_KEY`。若配置 `ROUTE_SERVICE_ENABLED=true`，路线服务优先调用高德步行/驾车 API；调用失败、超出预算或缺坐标时回退坐标估算并标记 degraded。`SCHEDULE_OPTIMIZER_ENABLED=true` 控制确定性时间窗优化器。`TOOL_MAX_CALLS` 控制单次 Agent 请求的工具调用总预算，单工具风险、版本、Schema、超时和调用上限由 Tool Registry 管理；`AGENT_DEADLINE_SECONDS`、`MAX_LLM_CALLS`、`MAX_TOKEN_BUDGET` 和 `MAX_REPLANS` 控制单次运行边界，`TRACE_STORAGE_PATH` 控制 JSONL Trace 持久化位置（错误文本中的 API key/Bearer 令牌会集中脱敏）。

## 接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/agent/hello` | 健康检查 |
| `POST /api/agent/v1/generate-stream` | 整段流式生成（JSON Lines：start / day / day_patch / suggestions / done / error 逐天事件，事件体 camelCase） |
| `POST /api/agent/v1/generate` | 生成行程（城市/天数/偏好/预算 → 每日计划 + 预算明细 + validation_log + `status`；直接调用与离线评测用） |
| `POST /api/agent/v1/adjust` | 增量调整（替换/删除/排序 + 预算重算推荐） |
| `POST /api/agent/v1/generate-day` | 单日生成（恢复续跑 / 缺天修复；开放模式 + 权威参考资料注入，知识库只作证据） |
| `POST /api/agent/v1/plan-context` | 一次性构建检索上下文（候选/餐饮/酒店/消费系数） |
| `POST /api/agent/v1/poi-nearby` | 同城权威 POI 近邻（轻量 GraphRAG 附近推荐；坐标缺失返回空，不伪造） |
| `POST /api/agent/v1/poi-intros` | 景点详细介绍批量生成 |
| `POST /api/agent/v1/city-guide` | 城市引导对话（不确定去哪时按偏好推荐） |
| `POST /api/agent/v1/chat-turn` | 行程对话编辑（封闭动作集决策） |
| `POST /api/agent/v1/replan-local` | 按受影响日期、锁定点和候选池执行局部重规划 |
| `GET /api/agent/v1/metrics` | 进程内运行指标（成功率/降级率/失败率/token 分场景/缓存命中/路由分布） |
| `GET /api/agent/v1/metrics/prometheus` | Prometheus 文本格式导出 |
| `GET /api/agent/v1/tools` | 已注册工具的 Schema、风险、超时和调用预算（需内部 token） |
| `GET /api/agent/v1/runs/{run_id}` | 按 `run_id` 查询脱敏 Trace（内存最近 100 条 + JSONL 持久化回放） |

启动时自动导出 `openapi.json` 到项目根目录。

## 测试

```bash
# 离线单测与 Agent 评测（不依赖 Java/MySQL/外部 API）
uv run pytest --ignore=tests/api -q
uv run python tests/agent_eval/eval_agent.py
# 报告输出：tests/agent_eval/report/report.json / report.md
uv run python tests/agent_eval/replay.py
# RAG 专项离线评测（哈希 Embedding + 固定 fixture）
uv run python tests/agent_eval/eval_retrieval.py
# 生成质量评测（引用覆盖率/refs 有效率/资料利用率 + LLM-judge 忠实度，走真实链路）
uv run python -m app.rag.evaluation_generation 杭州
# 回放未知 POI、路线不足、营业时间越界等安全失败案例

# 接口自动化冒烟（需 Java 8081 运行中，DB_PASSWORD 需传入）
uv run pytest tests/api -q

# 性能压测（需 Java 8080 + Redis 6380 运行中）
uv run python tests/perf/load_test.py --endpoint all --duration 10 --workers 20
# 报告输出：tests/perf/report/load_report.json / load_report.md
```

## 离线评测指标（当前工作树可复现）

固定 fixture 评测覆盖 POI 权威引用、事实字段引用、时间冲突、跨天重复、预算一致性、fallback 成功率和轨迹完整率；路线/优化器消融脚本 `tests/agent_eval/eval_baselines.py` 使用固定 `fixture-route` 替身对比坐标基线与路线优化基线，报告写入 `tests/agent_eval/report/baseline_report.md`。RAG 专项评测另行统计 Recall@5/10、MRR、NDCG、城市/类别过滤准确率、偏好命中率、价格字段完整率和权威引用率。真实 LLM 指标需在固定模型、temperature、Prompt 版本和知识库快照后单独生成，不能直接复用 fixture 报告。

真实 LLM 双跑评测：

```bash
# 必须配置真实 LLM_API_KEY；脚本会固定当前模型、temperature=0.3、Prompt 版本，逐遍记录 run_id、脱敏 Trace、token、调用/重试/fallback 和失败原因
uv run python tests/agent_eval/llm_eval.py --limit 6
# 报告：tests/agent_eval/report/llm_report.json
```

- 运行接口生成后，可通过 `X-Request-ID` 与响应头 `X-Agent-Run-ID` 关联 Java/Python 链路；`GET /api/agent/v1/runs/{run_id}` 查询该运行的脱敏 Trace。Trace 事件包含 request/run/span/parent span 关联，Registry 工具事件还包含 tool call/action ID。生成响应的 `status` 为 `success`、`degraded` 或 `failed`：开放模式生成必然标注关键事实需出发前复核（`degraded`），LLM 未配置或重试耗尽返回待研究草案，0 可交付项时 `failed`（质量报告 BLOCKED，Java 侧不会将其落库为成功）。`GET /api/agent/v1/metrics` 提供互斥的成功率、降级率、失败率、平均事件耗时、LLM/工具/MCP 调用数、token、重试、fallback、工具预算耗尽和 MCP 失败率。当前是进程内指标，生产多实例部署应接入 Prometheus/OpenTelemetry。
