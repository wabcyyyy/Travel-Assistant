# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ 多 Agent 研究 + RAG 权威知识库** 的旅行规划系统。输入城市、天数、偏好与一句话旅行意图，Agent 生成带事实溯源的每日行程：知识库条目标注来源与更新时间，模型自选点显式标记「出发前复核」；生成过程通过 SSE 实时推送进度，支持地图可视化、拖拽编辑、自然语言改行程、附近推荐、预算看板与 PDF 导出。后端为**单一 FastAPI 服务**（Python 3.12）：业务接口、agent 编排与事件流同进程，Spring Boot 版已退役删除（见「后端演进」）。

> **零第三方地理 API（2026-09-15，含底图刷新）**：POI 检索读本地 `poi_knowledge`（`/api/pois`），底图为 **OpenFreeMap** 免 key 在线矢量瓦片（MapLibre 样式文档，署名随图，观感对齐开源项目 TREK），路线默认坐标估算并如实标记 `degraded`——除 LLM 外，运行时不需要任何注册、key 或配额；底图瓦片之外的既有数据断网也能完整演示。图片仍可走 Unsplash/Pexels/维基（服务端代理，可选、未命中落占位块）。

## 核心能力

- **整段流式生成 + SSE 实时进度**：一次 LLM 调用生成整趟（模型看得见全盘，跨天重复/走回头路在源头收敛），边流边解析逐天落库；断线降级轮询，缺天自动逐日修复
- **意图优先**：一句话旅行意图作为最高优先级信号，驱动主题提炼、检索补池与选点；输出每日叙事、拍照机位、天气备选与方案分叉
- **多 Agent 研究编排**：酒店/景点/美食三域并行收集证据（LLM 规划检索 → 评估充分性 → 不足补查），Supervisor 汇总并按校验反馈定向补查，全程 trace
- **事实溯源与诚实降级**：行程项带 `source` / 更新时间 / 核验状态；知识库只作证据，不存在「用候选直接拼装行程」的路径，LLM 失败如实返回待研究草案
- **对话式编辑**：自然语言改行程（换酒店/调节奏/加减天数），SSE 返回草稿卡片，确认后应用并联动预算重算（服务端草稿 + 指纹乐观并发）
- **本地知识与零 geo API**：POI 来自本地 `poi_knowledge`（离线采集管线），底图 OpenFreeMap 免 key；除 LLM 外运行时不需要任何注册与配额
- **可观测**：`X-Agent-Run-ID` 关联全链路脱敏 Trace，`/v1/metrics` 暴露成功/降级/失败、token 分场景、缓存命中与路由分布（支持 Prometheus 文本）
- **前端外观契约**：三套 scheme × 日间/夜间双主题 × 紧凑密度 × 减弱动效，首帧无 FOUC；`theme:lint` 禁裸色与野 z-index、`ep:lint` 对 Element Plus 只减不增（均入 CI）

## 系统架构

```
┌─────────────────────┐              ┌────────────────────────────────────────────┐
│ travel-frontend-vue │     HTTP     │            travel-agent-python             │
│ Vue3 + Vite + TS    │ ───────────► │   FastAPI 单进程后端（业务 + Agent）         │
│ 地图/预算看板/编辑    │     /api     │  ┌──────────────────┐  ┌─────────────────┐ │
└─────────────────────┘              │  │ 业务层            │  │ Agent 层        │ │
                                     │  │ JWT/行程状态机/    │  │ LangGraph 编排/  │ │
                                     │  │ 缓存/异步 PDF/SSE  │  │ 多 Agent 研究/   │ │
                                     │  └────────┬─────────┘  │ 事实落地/RAG     │ │
                                     │           │ 同进程直调  └────────┬────────┘ │
                                     └───────────┼───────────────────────┼─────────┘
                                                 │                       │
                                          ┌──────▼───────┐   ┌───────────▼──────────────────────┐
                                          │ MySQL 8      │   │  RAG 层（app/rag）                │
                                          │ 权威 POI 库   │──►│ 三源采集 → 语义向量 → Qdrant      │
                                          │ 2142 条/6 城 │   │ BM25+向量+RRF → 路由/缓存         │
                                          └──────┬───────┘   │ 引用式生成落地 → 近邻图 → 遥测     │
                                                 │           └──────────────────────────────────┘
                                          ┌──────▼───────┐
                                          │ Redis        │ 缓存/限速/日锁/会话吊销（事件主链路在进程内，Redis 仅尽力广播）
                                          └──────────────┘
```

**分层**：前端只做展示与交互；FastAPI 服务同时承担两件事——**业务面**（认证、行程状态机、缓存、异步 PDF 导出、SSE 事件流）与 **Agent 面**（LLM 编排、多 Agent 研究、事实落地与质量校验），两者同进程直调，省掉跨语言序列化与一条 SSE 转发桥。知识库永远只作证据：检索结果以编号参考资料注入 Prompt 引导模型选点，命中项落地权威字段与溯源；系统不存在「用知识库候选直接拼装行程」的路径，LLM 失败时如实返回待研究草案。

**后端演进（Java 版已删除）**：这个项目最初是「Vue + Spring Boot + Python Agent」三端结构，Spring 侧承载认证 / 行程状态机 / 缓存 / PDF / SSE 网关。为了把 agent 能力与持久化放进同一进程，后端已按绞杀者路线整体迁到 FastAPI：**Java 侧 50 个业务端点有 49 个在 FastAPI 上等价落地**（剩下 1 个是刻意退役的内部探针），迁移完成后该模块已从工作树删除——它原先依赖的 schema SQL 与印刷字体已迁入本仓（各一份，避免双份真相漂移）。旧代码随时可从 git 历史取回，恢复步骤与「原先谁负责什么」的对照表见 `ARCHIVED.md`。

## 快速开始

### 前置条件

- Docker（MySQL 8 + Redis）或本地同版本服务
- Node.js 18+、Python 3.12 + [uv](https://docs.astral.sh/uv/)
- LLM API Key（阿里云百炼等 OpenAI 兼容端点）——地理能力全部本地化，不需要任何地图/POI 平台的 key

### 1. 初始化数据库与基础设施

```bash
docker compose up -d mysql redis
# 表结构无需手工执行 SQL：后端启动时自动迁移（Alembic 按版本序执行 app/db/migrations/sql/ 下的 V*.sql；
# 空库全量建表，已有表的库只打版本点、绝不重跑 DDL）
```

### 2. 启动后端（travel-agent-python，业务 + Agent 同一进程）

```bash
cd travel-agent-python
cp .env.example .env        # 必填 DB_PASSWORD、JWT_SECRET（≥32 位）、AGENT_INTERNAL_TOKEN、LLM_API_KEY
uv sync
uv run python scripts/fetch_rag_model.py  # 首次：预置 RAG 语义模型（国内可设 HF_ENDPOINT=https://hf-mirror.com）
uv run python main.py       # 127.0.0.1:8000；启动即迁移 schema，随后预热并增量同步 RAG 索引
```

### 3. 启动前端（travel-frontend-vue）

```bash
cd travel-frontend-vue
cp .env.example .env        # 空白模板：前端不需要任何 key
npm install
npm run dev                 # http://localhost:5173（/api 代理到 :8000）
```

> Windows 也可用根目录 `start-all.cmd` 一键拉起全部进程（`stop-all.cmd` 全停）。
> 未配置 `LLM_API_KEY` 时 Agent 如实返回待研究草案（不会用知识库拼装行程冒充结果）。

### 4.（可选）查看迁移前的 Java 实现

`travel-backend-java/` 是迁移前的第一版后端，**已从工作树删除**。需要对照时按 `ARCHIVED.md` 从 git 历史取回（含"原先谁负责什么"的 Spring → FastAPI 位置对照表）。

### 可选：种子与真实 POI 数据

表结构由后端启动时的自动迁移创建（Alembic 按版本序执行 `app/db/migrations/sql/V*.sql`），之后可灌数据；种子仅为兜底，生产质量的数据由**离线**采集管线生成（默认零 LLM：Wikivoyage 免 key，可选高德源需 key；每城约 1-3 分钟）：

```bash
mysql -uroot -p travel_assistant < sql/seed_data.sql    # 兜底种子（可被真实数据覆盖）
cd travel-agent-python
uv run python ../sql/enrich_pois.py            # 国内 6 城；--cities 巴黎 采集海外城市
uv run python ../sql/enrich_pois.py --with-llm # 可选：LLM 翻译/补齐（约 30-60 分钟）
```

## 测试与评测

```bash
just check                       # 一键门禁（九步：lint/format/typecheck/边界/规模/密钥/测试+覆盖率/diff-cover/契约漂移）
just test                        # 后端离线单测（零外部依赖，全走离线替身）
just eval                        # Agent 离线评测（mock 驱动，行为改动后对比指标）
just fe-check                    # 前端构建 + theme:lint + ep:lint + 单测
```

| 套件 | 说明 |
| --- | --- |
| 离线单测 | 事件契约与漂移门禁 / 断流取消 / 叙事契约 / 引用落地 / 跨天去重 / 反思 / 多 Agent / SSE / PDF 导出 / 后台管理 |
| 活栈契约 | `uv run pytest tests/api -q`（需先起后端）：登录/行程/导出/后台端到端 |
| Agent 评测 | 离线 mock 评测 + 真实 LLM 评测（固定模型与 Prompt 版本）+ RAG 检索评测；行为回归门禁（快照 + eval ratchet）已入 CI |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` |

> 完整命令清单与门禁口径见 [`AGENTS.md`](AGENTS.md) 与 [`travel-agent-python/AGENTS.md`](travel-agent-python/AGENTS.md)。

## 仓库结构

```
Travel-Assistant/
├── AGENTS.md               # 跨仓约定与哲学（命令、契约流程、门禁纪律）— 改代码前先读
├── ARCHIVED.md             # Java 版退役说明：位置对照表 + 从 git 历史取回的命令
├── justfile                # 单命令入口（just check / test / eval / snapshot / fe-check）
├── travel-agent-python/    # FastAPI 单进程后端：业务接口 + LangGraph 编排 + 多 Agent 研究 + RAG（见其 AGENTS.md）
│   └── app/agent/README.md # 生成链路模块蓝图（依赖方向与"新增能力先抄谁"）
├── travel-frontend-vue/    # Vue3：生成 / 三栏工作台（行程·地图·发现）/ 列表 / 图鉴 / 管理端
├── contracts/              # 跨端契约导出物（schema + openapi + 前端生成类型，drift 门禁）
└── sql/                    # 数据种子与离线采集管线
```

## 安全说明

- 真实密钥只存 `.env`（已 gitignore），仓库仅跟踪 `.env.example`；**公开 / 部署前必须 rotate** 全部第三方 Key 与本地 `JWT_SECRET`、`AGENT_INTERNAL_TOKEN`、MySQL 口令
- 后端启动强制校验 `JWT_SECRET`（非空且 ≥32 字符；规则沿用迁移前 Spring 侧的 `@NotBlank @Size(min=32)`）；`AGENT_INTERNAL_TOKEN` 保护 HTTP 直调 agent 的入口，服务绑定非回环地址且未配置 token 时启动 fail-fast
- **会话凭据**为 HttpOnly Cookie（`SameSite=Lax`），登录响应不回传 JWT；支持服务端吊销（`/api/auth/logout` 将 token 写入 Redis 黑名单）与多端登出；写请求校验 Origin 白名单（CSRF 缓解）
- 登录 / 注册按「IP + 用户名」滑动窗口限速，限速 / 日锁 / 续跑标记统一走 Redis，故障自动降级进程内
- 生成 / 编辑类接口的错误响应只回通用文案，内部异常原文完整记日志不外泄；Trace 落盘前对 URL key 与 Bearer 令牌集中脱敏
- 第三方合规：Wikivoyage 内容为 CC BY-SA（`source` 字段标注来源）；离线采集脚本访问 Nominatim 时 UA 含联系方式；本项目定位**本地演示 / 学习项目**，未做生产级合规审计

## 已知局限

| 局限 | 说明 |
| --- | --- |
| 非生产系统 | 单机演示；无集群、无真正多实例限流 / 会话吊销集群方案 |
| 酒店价格 | 联网实时价与基准价估算都**不是 OTA 实时成交价** |
| 开放模式行程 | LLM 自选点标注「待确认 / 参考估算」，校验时间与路线可达，**不保证店铺仍营业** |
| 海外坐标 | 坐标来自本地知识库采集结果；库里没有的城市坐标如实留空（界面提示覆盖范围，不假装有数据） |
| RAG 默认口径 | 默认本地语义（`semantic` + bge-small-zh-v1.5，可换 bge-m3）；模型/依赖不可用时响亮降级为 hashed 哈希向量（启动告警 + 遥测 `fallback`）；精排默认关闭（可选 cross-encoder） |
| 多 Agent 定性 | 酒店/景点/美食三域**并行工具研究** + Supervisor 汇总补查，不是自主协商的多 Agent 协作 |
| 记忆边界 | 请求内 WorkingMemory + 对话滑窗（4 轮 × 800 字）；无长期画像、无跨会话向量记忆 |
| 评测口径 | 离线单测与真实 LLM 评测分开报告；小样本评测结果不能外推全量 |
