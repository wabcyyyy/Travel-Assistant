# travel-agent-python

AI Agent 服务：接收后端行程生成/调整请求，通过 LangGraph 工作流调用 LLM（千问兼容模式）生成行程，RAG 知识库兜底，失败自动降级。

## 技术栈

- Python 3.12（uv 管理依赖）
- FastAPI 0.111 + Uvicorn
- LangGraph 0.2.44 + LangChain Core
- ChromaDB 1.5.9（RAG 向量库，可选依赖 `rag`）
- PyMySQL（读 MySQL 知识库）

## 工作流（LangGraph）

```
parse ──► search ──► generate ──► reflect ──► format
                │                      │
                └───── 失败/重试 ───────┘
```

- `parse`：意图解析（城市/天数/偏好/预算）
- `search`：RAG 语义检索景点知识，失败回退 `poi_repository` 关键词检索
- `generate`：LLM 生成行程 JSON（prompt 强约束：费用取知识库单价、JSON Schema）
- `reflect`：校验时间冲突 / 开放时间 / 日饱和度，`needs_fix` 时最多 2 轮修正，输出 `validation_log`
- `format`：结构化输出 + 就近排序（`geo.py` haversine 最近邻，无高德路径规划）

**降级**：未配置 `LLM_API_KEY` 或 LLM 连续失败（`MAX_FIX_ATTEMPTS=2`）时，自动切换确定性 `fallback_generate()`，全流程仍可用。

## 目录结构

```
main.py                # 入口（启动时 warmup_rag 导入知识库）
app/
├── api/agent.py       # /api/agent/hello、/v1/generate、/v1/adjust
├── agent/             # workflow / generators / reflect / geo / tools / poi_repository
├── rag/               # store（Chroma 持久化）/ embeddings
├── common/            # config（.env）/ llm_client
└── schemas/           # trip / common
tests/
├── test_reflect.py、test_geo_workflow.py   # 单测
├── api/test_api.py    # 接口自动化（打 Java 8081 测试库）
├── eval/eval_agent.py # Agent 评测（30 用例，真实 LLM）
└── perf/load_test.py  # 性能压测
```

## 启动

```bash
cp .env.example .env   # 填入 LLM_API_KEY、DB_PASSWORD
uv sync                # 安装依赖（uv sync --extra rag 安装向量库）
uv run python main.py  # 0.0.0.0:8000，reload 模式
```

环境变量（`.env`）：`LLM_BASE_URL`（默认 dashscope 兼容模式）、`LLM_API_KEY`、`LLM_MODEL`（默认 qwen-plus）、`LLM_TIMEOUT`、`DEFAULT_BUDGET`、`DB_*`。

## 接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/agent/hello` | 健康检查 |
| `POST /api/agent/v1/generate` | 生成行程（城市/天数/偏好/预算 → 每日计划 + 预算明细 + validation_log） |
| `POST /api/agent/v1/adjust` | 增量调整（替换/删除/排序 + 预算重算推荐） |

启动时自动导出 `openapi.json` 到项目根目录。

## 测试

```bash
# 单测 + 接口自动化冒烟（需 Java 8081 运行中，DB_PASSWORD 需传入）
uv run pytest tests/ -q

# Agent 评测（真实 LLM，30 用例 × 2 遍一致性；--mode=fallback 可无 key 复现）
uv run python tests/eval/eval_agent.py --full
# 报告输出：tests/eval/report/report.json / report.md

# 性能压测（需 Java 8080 + Redis 6380 运行中）
uv run python tests/perf/load_test.py --endpoint all --duration 10 --workers 20
# 报告输出：tests/perf/report/load_report.json / load_report.md
```

## 评测指标（真实 LLM 实测）

工具调用准确率 100%、时间冲突率 0%、重复率 0.48%、预算偏差 20.96%、幻觉检出率 3.33%；两遍一致性 33.3%（不稳定用例清单见报告）。