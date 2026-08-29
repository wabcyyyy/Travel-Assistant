# travel-agent-python

AI Agent 服务：接收后端行程生成/调整请求，通过 LangGraph 工作流调用 LLM（千问兼容模式）生成行程，并通过高德官方 MCP 获取外部事实；RAG 知识库兜底，失败自动降级。

## 技术栈

- Python 3.12（uv 管理依赖）
- FastAPI 0.111 + Uvicorn
- LangGraph 0.2.44 + LangChain Core
- ChromaDB 1.5.9（RAG 持久化存储，运行时依赖；语义 embedding 为可选依赖 `rag`）
- PyMySQL（读 MySQL 知识库）
- 高德官方 MCP Server（Streamable HTTP，可选）

## 工作流（LangGraph）

```
parse ──► search ──► generate ──► reflect ──► format
                │                      │
                └───── 失败/重试 ───────┘
```

- `parse`：意图解析（城市/天数/偏好/预算）
- `search`：统一检索接口执行 Chroma 语义召回 + BM25 风格关键词召回，使用 RRF 和偏好/评分/预算业务规则重排；失败回退 `poi_repository` 关键词检索
- `generate`：LLM 生成行程 JSON（prompt 强约束：费用取知识库单价、JSON Schema）
- `reflect`：校验时间冲突 / 营业时间完整覆盖 / POI 间路线可达性 / 日饱和度，`needs_fix` 时最多 2 轮修正，输出 `validation_log`
- `format`：结构化输出 + 确定性预算重算；路线校验使用坐标距离估算并包含固定/比例容错，不等同于实时导航

每次混合检索会写入脱敏 Trace 事件 `retrieval/poi.hybrid_search`，包含 provider、模型版本、BM25/语义候选数、RRF 融合数量、最终 POI ID、耗时和 fallback 标记；因此可通过 `X-Agent-Run-ID` 追踪检索链路。

**降级**：未配置 `LLM_API_KEY` 或 LLM 连续失败（`MAX_FIX_ATTEMPTS=2`）时，自动切换确定性 `fallback_generate()`，全流程仍可用。

## 目录结构

```
main.py                # 入口（启动时 warmup_rag 导入知识库）
app/
├── api/agent.py       # /api/agent/hello、/v1/generate、/v1/adjust（内部 token 可选）
├── agent/             # workflow / generators / reflect / geo / tools / poi_repository
├── rag/               # retriever（可插拔 Embedding/混合召回）/ store（Chroma 持久化）/ embeddings
├── common/            # config（.env）/ llm_client
└── schemas/           # trip / common
tests/
├── test_reflect.py、test_geo_workflow.py   # 单测
├── api/test_api.py    # 接口自动化（打 Java 8081 测试库）
├── agent_eval/         # Agent 离线评测（固定数据 + LangGraph 轨迹）
└── perf/load_test.py  # 性能压测
```

## 启动

```bash
cp .env.example .env   # 填入 LLM_API_KEY、DB_PASSWORD
uv sync                # 安装运行时依赖（包含 ChromaDB）
uv run python main.py  # 127.0.0.1:8000，默认不开启 reload
```

环境变量（`.env`）：`LLM_BASE_URL`（默认 dashscope 兼容模式）、`LLM_API_KEY`、`LLM_MODEL`（默认 qwen-plus）、`LLM_TIMEOUT`、`DEFAULT_BUDGET`、`DB_*`、`AGENT_INTERNAL_TOKEN`（配置后保护生成/编辑接口，留空仅适合本机开发）、`AGENT_RELOAD`（开发环境可设为 `true`）。RAG 默认使用 `RAG_EMBEDDING_PROVIDER=hashed` 的离线哈希/词法特征；安装 `uv sync --extra rag` 并准备本地模型缓存后，可设置 `RAG_EMBEDDING_PROVIDER=semantic`、`RAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`。`RAG_TOP_K`、`RAG_RRF_K` 控制候选数量和 RRF 常数，`RAG_DOCUMENT_VERSION` 变化会触发全量重建。已有数据库需要先执行 `../sql/add_poi_provenance.sql` 和 `../sql/add_user_preference.sql`。启用高德官方 MCP 时配置 `AMAP_MCP_ENABLED=true`、`AMAP_MCP_URL=https://mcp.amap.com/mcp` 和服务端密钥 `AMAP_MCP_KEY`。

## 接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/agent/hello` | 健康检查 |
| `POST /api/agent/v1/generate` | 生成行程（城市/天数/偏好/预算 → 每日计划 + 预算明细 + validation_log + `status`） |
| `POST /api/agent/v1/adjust` | 增量调整（替换/删除/排序 + 预算重算推荐） |
| `GET /api/agent/v1/metrics` | 查看进程内 Agent 运行指标（需配置内部 token 时同样鉴权） |
| `GET /api/agent/v1/runs/{run_id}` | 查询最近 100 条运行中的单条脱敏 Trace（不存在或过期返回 404） |

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
# 回放未知 POI、路线不足、营业时间越界等安全失败案例

# 接口自动化冒烟（需 Java 8081 运行中，DB_PASSWORD 需传入）
uv run pytest tests/api -q

# 性能压测（需 Java 8080 + Redis 6380 运行中）
uv run python tests/perf/load_test.py --endpoint all --duration 10 --workers 20
# 报告输出：tests/perf/report/load_report.json / load_report.md
```

## 离线评测指标（当前工作树可复现）

固定 fixture 评测覆盖 POI 权威引用、事实字段引用、时间冲突、跨天重复、预算一致性、fallback 成功率和轨迹完整率；RAG 专项评测另行统计 Recall@5/10、MRR、NDCG、城市/类别过滤准确率、偏好命中率、价格字段完整率和权威引用率。真实 LLM 指标需在固定模型、temperature、Prompt 版本和知识库快照后单独生成，不能直接复用 fixture 报告。

真实 LLM 双跑评测：

```bash
# 必须配置真实 LLM_API_KEY；脚本会固定当前模型、temperature=0.3、Prompt 版本，逐遍记录 run_id、脱敏 Trace、token、调用/重试/fallback 和失败原因
uv run python tests/agent_eval/llm_eval.py --limit 6
# 报告：tests/agent_eval/report/llm_report.json
```

- 运行接口生成后，可通过响应头 `X-Agent-Run-ID` 关联日志；`GET /api/agent/v1/runs/{run_id}` 查询该运行的脱敏 Trace。生成响应的 `status` 为 `success`、`degraded` 或 `failed`：未配置/调用失败走确定性 fallback 时为 `degraded`，最终校验仍有问题也会降级；未捕获的生成异常通过错误信封表示 `failed`。`GET /api/agent/v1/metrics` 提供互斥的成功率、降级率、失败率、平均事件耗时、LLM/工具/MCP 调用数、token、重试、fallback 和 MCP 失败率。当前是进程内指标，生产多实例部署应接入 Prometheus/OpenTelemetry。
