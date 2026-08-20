# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ 高德地图 + RAG 知识库** 的三端分离旅行规划系统：用户输入城市、天数与偏好，Agent 自动规划每日行程（含景点门票、餐饮、交通等预算明细），支持地图可视化、拖拽编辑、实时预算重算与 PDF 导出。

> 详细开发过程与计划见 [开发计划.md](./开发计划.md)

## 功能特性

- **AI 行程生成**：LangGraph 编排「意图解析 → 知识检索 → LLM 生成 → 反思校验 → 格式化」五节点工作流，反思节点自动检测时间冲突/开放时间/饱和度，最多 2 轮修正
- **RAG 知识库**：ChromaDB 持久化 125 条景点知识（5 城市），语义检索失败自动回退关键词检索
- **预算引擎**：基于知识库门票价 + 城市消费系数的 D1 单一口径预算，行程生成/编辑后统一重算
- **地图可视化**：高德 JSAPI 渲染景点 Marker、路线连线与列表双向联动
- **行程编辑**：拖拽排序、增删改，实时联动预算看板（ECharts 饼图）
- **异步 PDF 导出**：任务队列 + Thymeleaf 模板 + 中文字体，轮询/下载
- **高可用**：Redis 缓存（POI/行程详情）、LLM 连续失败自动降级为确定性 fallback 生成
- **完整测试体系**：Java/Python 单测、接口自动化（独立测试库）、Agent 评测（30 用例真实 LLM）、性能压测

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
| travel-backend-java | 8080 | 生产实例（库 `travel_assistant`） |
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
├── sql/                   # 建表脚本与种子数据（poi_knowledge 125 条）
└── 开发计划.md            # 开发计划与交付记录
```

## 快速开始

### 前置依赖

- JDK 17+、Maven 3.8+
- MySQL 8.0+（本地 3306）
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 18+（Vite 5）
- Redis（缓存必需，端口 6380）

### 1. 初始化数据库

```bash
mysql -uroot -p < sql/schema.sql      # 建 8 张表
mysql -uroot -p < sql/seed_data.sql   # 种子数据：125 条 POI 知识 + 城市消费系数
```

### 2. 启动后端（travel-backend-java）

```bash
# 8080 生产实例（Windows PowerShell）
$env:AMAP_WEB_KEY="你的高德Web服务key"
$env:MYSQL_PASSWORD="数据库密码"
mvn spring-boot:run -Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8

# 8081 测试实例（接口自动化用，连接独立测试库）
$env:MYSQL_DB="travel_test"
mvn spring-boot:run -Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8 -Dspring-boot.run.arguments=--server.port=8081
```

### 3. 启动 Agent 服务（travel-agent-python）

```bash
cd travel-agent-python
cp .env.example .env   # 填入 LLM_API_KEY（千问兼容模式）、DB_PASSWORD
uv sync                # 安装依赖（含 RAG 可选依赖）
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
| `AMAP_WEB_KEY` | Java | 高德 Web 服务 key（POI/地理编码） |
| `MYSQL_HOST/PORT/USER/PASSWORD/DB` | Java/Python | 数据库连接（Java 另有 `REDIS_HOST/PORT`） |
| `JWT_SECRET` | Java | JWT 密钥（默认 dev 值，生产必改） |
| `AGENT_SERVICE_URL` | Java | Agent 服务地址，默认 `http://localhost:8000` |
| `LLM_API_KEY/BASE_URL/MODEL` | Python | 千问 OpenAI 兼容接口（默认 qwen-plus） |
| `DEFAULT_BUDGET` | Python | 默认预算，默认 1000 |
| `VITE_AMAP_JS_KEY/SECURITY_CODE` | 前端 | 高德 JS key 与安全码 |

## 测试体系

| 套件 | 命令 | 说明 |
| --- | --- | --- |
| Java 单测 | `mvn test`（travel-backend-java） | 预算引擎 6 用例 |
| Python 单测 + 接口自动化 | `uv run pytest tests/`（travel-agent-python） | 28 用例，接口自动化跑 8081 测试库 |
| Agent 评测 | `uv run python tests/eval/eval_agent.py --full` | 30 用例 × 真实 LLM，输出工具准确率/冲突率/幻觉率等 |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` | 20 workers 并发 QPS/p50/p95/p99 |

## 安全说明

- 所有真实密钥只放 `.env`（已 gitignore），仓库仅跟踪 `.env.example` 占位文件
- 接口自动化使用独立 `travel_test` 库与随机测试账号，不污染生产数据