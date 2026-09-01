# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ 高德地图 + RAG 知识库** 的三端分离旅行规划系统：用户输入城市、天数与偏好，Agent 自动规划每日行程（含景点门票、餐饮、交通等预算明细），支持地图可视化、拖拽编辑、实时预算重算与 PDF 导出。

> 详细开发过程与计划见 [开发计划.md](./开发计划.md)

## 功能特性

- **AI 行程生成**：完整生成图使用 LangGraph 编排「parse → search → generate → reflect → format」；生产接口按天执行「generate → reflect → retry/fallback」，反思节点检测时间冲突/营业覆盖/路线可达性/饱和度
- **标准化外部能力接入**：Agent 可选接入高德官方 MCP 的只读 POI 查询；MCP 失败或未启用时自动回退本地知识库与旧 Web API，天气、路线等能力暂未进入主链路
- **RAG 知识库**：ChromaDB 持久化 POI 知识，基准 `seed_data.sql` 为 125 条、覆盖 5 城市；执行杭州和酒店增量后当前快照约 186 条、覆盖 6 城市，采用词法 + 语义召回、RRF 融合和业务重排
- **预算引擎**：基于知识库门票价 + 城市消费系数的 D1 单一口径预算，行程生成/编辑后统一重算
- **地图可视化**：高德 JSAPI 渲染景点 Marker、路线连线与列表双向联动
- **行程边界**：单次新建、对话扩展和草稿确认统一最多 7 天，超限请求直接拒绝
- **行程编辑**：拖拽排序、增删改，实时联动预算看板（ECharts 饼图）
- **异步 PDF 导出**：数据库任务记录 + Spring 异步执行 + Thymeleaf 模板 + 中文字体，轮询/下载
- **容错与缓存**：Redis 缓存（POI/行程详情）、LLM 连续失败自动降级为确定性 fallback 生成；异步任务当前基于 Spring `@Async`，尚非消息队列级高可用
- **完整测试体系**：Java/Python 单测、接口自动化（独立测试库）、Agent 离线评测（含 LangGraph 轨迹）、性能压测

## 系统架构

```
┌─────────────────┐      ┌──────────────────┐      ┌──────────────────────┐
│  travel-frontend-vue │ ──►│ travel-backend-java │ ──►│  travel-agent-python   │
│  Vue3 + Vite + TS    │HTTP│  Spring Boot 3.2    │HTTP│  FastAPI + LangGraph   │
│  AMap JSAPI 地图     │/api│  JWT 认证/预算/编辑  │ /api│  LLM 生成 + RAG 检索    │
│  ECharts 预算看板    │    │  Redis 缓存/PDF 导出 │agent│  LLM 降级 fallback     │
└─────────────────┘      └─────────┬────────────┘      └──────────┬───────────┘
                                   │                              │
                            ┌──────▼───────┐              ┌───────▼────────┐
                            │  MySQL 8     │              │  ChromaDB      │
                            │ travel_* 库  │              │  RAG 向量库     │
                            └──────────────┘              └────────────────┘
```

**服务与端口**

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| travel-backend-java | 8080 | 本地主实例（库 `travel_assistant`） |
| travel-backend-java | 8081 | 测试实例（库 `travel_test`，接口自动化专用） |
| travel-agent-python | 8000 | Agent 服务 |
| travel-frontend-vue | 5173 | 前端（Vite dev server，/api 代理到 8080） |
| Redis | 6380 | 缓存（POI/行程详情） |

## 目录结构

```
Travel-Assistant/
├── travel-backend-java/   # Spring Boot 后端（认证/行程/预算/地图/导出）
├── travel-agent-python/   # FastAPI + LangGraph Agent（LLM 生成/反思/RAG/评测/压测）
├── travel-frontend-vue/   # Vue3 前端（登录/生成/详情/列表 + 地图）
├── sql/                   # 建表脚本与种子数据（基准 POI 125 条，含增量脚本；完整快照约 186 条）
└── 开发计划.md            # 开发计划与交付记录
```

## 快速开始

### 一键启停（推荐）

```bash
start-all.cmd   # 双击即可：自动拉起 Redis + 后端 + Agent + 前端（后台运行），已启动的自动跳过，最后做健康检查
stop-all.cmd    # 一键全停（加参数 /I 连 Redis 一起停：stop-all.cmd -IncludeRedis）
```

> 服务窗口需保持打开，关窗即停该服务。前置条件仅两个：MySQL 已运行、首次使用前完成下方「初始化数据库」与各端 `.env` 配置。

### 手动启动

#### 前置依赖

- JDK 17+、Maven 3.8+
- MySQL 8.0+（本地 3306）
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 18+（Vite 5）
- Redis（缓存必需，端口 6380）

### 1. 初始化数据库

```bash
mysql -uroot -p < sql/schema.sql        # 建完整数据库结构
mysql -uroot -p < sql/seed_data.sql     # 基准数据：125 条 POI + 城市消费系数（5 个城市）
mysql -uroot -p < sql/add_hangzhou.sql  # 追加杭州 POI（幂等）
mysql -uroot -p < sql/add_hotels.sql    # 追加各城市知识库酒店（经济/舒适/高端三档，幂等）
mysql -uroot -p < sql/add_hotel_tier.sql # 已有数据库补充住宿偏好字段（幂等）
mysql -uroot -p < sql/add_hangzhou_hotel_options.sql # 补充杭州各档换房候选（幂等）
mysql -uroot -p < sql/add_hotel_room_types.sql # 补充酒店房型与每晚参考价（幂等）
mysql -uroot -p < sql/add_itinerary_chat_message.sql # 持久化行程对话记忆（幂等）
mysql -uroot -p < sql/add_intro_columns.sql # 已有数据库补充管家讲解与景点介绍字段
mysql -uroot -p < sql/add_user_preference.sql # 已有数据库补充用户偏好统计表（幂等）
```

> `schema.sql` 已包含当前完整表结构；增量脚本用于已有数据库升级。酒店价格均为参考估算：优先尝试联网查询当前挂牌参考价，失败时使用知识库基准价×季节系数。它不代表指定日期、房型的实时库存成交价，最终应以酒店供应商报价为准。季节系数规则见 `app/common/season.py` 与 `common/SeasonPrice.java`。

### 2. 启动后端（travel-backend-java）

```bash
cd travel-backend-java
cp .env.example .env   # 填入 AMAP_WEB_KEY、MYSQL_PASSWORD（spring-dotenv 自动读取）
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8"

# 8081 测试实例（接口自动化用，连接独立测试库）
# 先在 .env 中加一行 MYSQL_DB=travel_test，再另开终端执行：
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8" "-Dspring-boot.run.arguments=--server.port=8081"
```

> 也支持直接用系统环境变量（`AMAP_WEB_KEY` / `MYSQL_*` 等），优先级高于 `.env`。

### 3. 启动 Agent 服务（travel-agent-python）

```bash
cd travel-agent-python
cp .env.example .env   # 填入 LLM_API_KEY（千问兼容模式）、DB_PASSWORD
uv sync                # 安装依赖（RAG/ChromaDB 为运行时必需依赖）
uv run python main.py  # 启动于 8000，自动 warmup RAG 导入知识库
```

未配置 `LLM_API_KEY` 时自动降级为确定性 fallback 生成，全流程仍可用。

### 4. 启动前端（travel-frontend-vue）

```bash
cd travel-frontend-vue
cp .env.example .env   # 填入 VITE_AMAP_JS_KEY / VITE_AMAP_SECURITY_CODE
npm install
npm run dev            # http://localhost:5173
```

> ⚠️ 高德 JS key 需在控制台配置 **`localhost:5173` 域名白名单** 才能渲染地图（Web 服务 key 不受限）。

### 环境变量

| 变量 | 服务 | 说明 |
| --- | --- | --- |
| `AMAP_WEB_KEY` | Java/Python 降级 | 高德 Web 服务 key（MCP 未启用或失败时使用） |
| `AMAP_MCP_ENABLED` | Python | 是否启用高德官方 MCP |
| `AMAP_MCP_URL` | Python | 高德 MCP endpoint，默认 `https://mcp.amap.com/mcp` |
| `AMAP_MCP_KEY` | Python | 高德 MCP 服务端 key，仅放在服务端环境变量 |
| `MYSQL_HOST/PORT/USER/PASSWORD/DB` | Java/Python | 数据库连接（Java 另有 `REDIS_HOST/PORT`） |
| `JWT_SECRET` | Java | JWT 密钥；未配置时使用进程级随机密钥，重启后旧登录失效 |
| `SERVER_ADDRESS/CORS_ALLOWED_ORIGINS` | Java | 默认仅监听本机并只允许本地前端跨域 |
| `AGENT_SERVICE_URL` | Java | Agent 服务地址，默认 `http://localhost:8000` |
| `AGENT_INTERNAL_TOKEN` | Java/Python | Java 调用 Agent 的内部认证 token；两端应配置相同值，留空仅适合本机开发 |
| `AGENT_RELOAD` | Python | 是否启用 Uvicorn 热重载；开发环境可设为 `true`，部署环境保持 `false` |
| `AGENT_HOST/AGENT_CORS_ORIGINS` | Python | Agent 默认仅监听 `127.0.0.1`，需要远程部署时显式调整 |
| `LLM_API_KEY/BASE_URL/MODEL` | Python | 千问 OpenAI 兼容接口（默认 qwen-plus） |
| `LIVE_PRICE_SEARCH/MAX_LIVE_QUERIES` | Python | 酒店联网实时定价开关（DashScope 搜索插件）与每次生成最大查询数 |
| `DEFAULT_BUDGET` | Python | 默认预算，默认 1000 |
| `VITE_AMAP_JS_KEY/SECURITY_CODE` | 前端 | 高德 JS key 与安全码 |

## 测试体系

| 套件 | 命令 | 说明 |
| --- | --- | --- |
| Java 单测 | `mvn test`（travel-backend-java） | 当前 8 个预算引擎 JUnit/Mockito 用例 |
| Python 单测（不含需服务的 API 测试） | `uv run pytest --ignore=tests/api -q`（travel-agent-python） | 可离线运行，覆盖工作流、白名单、反思和安全编辑 |
| Agent 离线评测 | `uv run python tests/agent_eval/eval_agent.py` | 固定权威 fixture，输出 POI 引用/冲突/重复/预算/轨迹指标 |
| Agent 真实 LLM 评测 | 需在离线评测基础上另行配置模型与数据版本 | 必须固定模型、temperature、Prompt 版本并报告一致性，不能用离线结果冒充 |
| Agent 失败回放 | `uv run python tests/agent_eval/replay.py` | 回放未知 POI、路线不足、营业时间越界等安全拦截 |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` | 20 workers 并发 QPS/p50/p95/p99 |

## 安全说明

- 所有真实密钥只放 `.env`（已 gitignore），仓库仅跟踪 `.env.example` 占位文件
- 接口自动化使用独立 `travel_test` 库与随机测试账号，不污染生产数据
- `/api/test/**` 与 Agent 的 `/test-generate` 仅用于本机联通性检查；部署环境应移除或限制到管理网络
- Agent 生成接口返回 `X-Agent-Run-ID`；`GET /api/agent/v1/runs/{run_id}` 可查询最近的脱敏轨迹，`GET /api/agent/v1/metrics` 可查看互斥的成功/降级/失败、LLM/工具/MCP 调用、token、重试和 fallback 指标

## 当前验证结果

- 截至 2026-09-01，Python 离线单测 72 passed（`pytest --ignore=tests/api -q`）；Java 8 个单测通过，前端类型检查和生产构建通过
- Agent 离线评测：6 个固定案例，权威 POI/字段引用/冲突/路线/重复/预算指标符合预期
- 真实 LLM 双跑：6 个案例、12 次运行，一致性率 100%，failed 0；12 次均为 `degraded`，均触发确定性 fallback
- 真实评测明细：`travel-agent-python/tests/agent_eval/report/llm_report.json`

> 真实评测中的“100%”是双跑结果一致性，不是 LLM 直出成功率；报告中的 12 次运行最终状态均为 `degraded`。异步生成使用 Spring `@Async`，重启恢复、跨实例指标和任务持久化仍属于后续增强方向。
