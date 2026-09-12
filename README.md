# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ RAG 权威知识库 + 高德地图** 的三端分离旅行规划系统。用户输入城市、天数、偏好与预算，Agent 生成带事实溯源的每日行程：知识库条目标注来源与更新时间，模型自选点显式标记「出发前复核」，支持地图可视化、拖拽编辑、附近推荐、预算看板与 PDF 导出。

**项目定位**：一个把「LLM 会编造」当作第一性问题来解的行程生成系统 —— 数据管线、检索、生成、评测、可观测每一层都围绕「事实从哪来、错了怎么发现、降级如何不撒谎」展开。

## 系统架构

```
┌─────────────────────┐        ┌──────────────────────┐        ┌────────────────────────┐
│ travel-frontend-vue │  HTTP  │ travel-backend-java  │  HTTP  │  travel-agent-python   │
│ Vue3 + Vite + TS    │ ─────► │ Spring Boot 3.2      │ ─────► │  FastAPI + LangGraph   │
│ 地图/预算看板/编辑    │  /api  │ JWT/行程/缓存/PDF导出 │ /agent │ 生成+多Agent研究+RAG    │
└─────────────────────┘        └──────────┬───────────┘        └───────────┬────────────┘
                                          │                                │
                                   ┌──────▼───────┐   ┌────────────────────▼─────────────┐
                                   │   MySQL 8    │   │  RAG 层（app/rag）                │
                                   │ 权威 POI 库   │──►│ 三源采集 → bge-m3 向量 → Chroma   │
                                   │ 2142 条/6 城 │   │ BM25+语义+RRF → 精排 → 路由/缓存  │
                                   └──────────────┘   │ 引用式生成落地 → 近邻图 → 遥测     │
                                                      └──────────────────────────────────┘
```

**三端分工**：前端只做展示与交互；Java 负责认证、行程状态机、Redis 缓存、异步 PDF 导出，并把请求转发给 Agent；Python Agent 负责 LLM 编排、RAG 检索、事实落地与质量校验，是唯一决定「行程内容从哪来」的一层。

## RAG 演进：从种子数据到引用式生成

| 阶段 | 做了什么 | 关键结果 |
| --- | --- | --- |
| P0 数据管线 | 高德 Web API（真坐标/评分/人均）+ Wikivoyage（CC BY-SA 署名）+ LLM 兜底，三源对齐清洗后增量 upsert | **2142 条真实 POI / 6 城 / 0 缺坐标**（景点 1083、美食 548、酒店 511），替换全部种子假坐标 |
| P0 语义升级 | embedding 切 bge-m3（1024 维），精排切 bge-reranker-v2-m3 cross-encoder | 融合排序头部 24 条重打分，`0.7×精排 + 0.3×业务分`；杭州「适合老人的自然景点」精排后西湖第一 |
| P1 引用式生成 | 检索结果编号为 `[R1..Rn]` 注入开放模式 Prompt，模型输出 `refs` 引用，生成后三级匹配落地为权威字段 | 杭州 2 天实测 6/6 行程项全部引用落地、refs 全有效、faithfulness 1.0 |
| P2 工程化 | 查询路由（枚举/词法/混合）+ 语义缓存 + 轻量 GraphRAG 近邻图 | 无意图检索 **2-4s → 1ms**；重复查询 **11.4s → 1ms**；「附近推荐」全栈上线 |
| P3 多 Agent 编排 | 酒店/景点/美食三个**研究 Agent**（LLM 推理：规划-检索-评估-补查，轮次上限 2）+ **Supervisor** 整合生成 + 证据型缺口补查 | 证据收集并行化；研究阶段全程可观测（规模/轮次/降级/补查）；「无景点」类缺口只补查对应域而非整体重生成 |

## 核心取舍（面试追问导览）

每一条都是先有问题、后有决策，欢迎按图索骥读代码：

1. **知识库永远只是证据，行程内容 100% 由 LLM 生成**。检索结果以编号参考资料 `[R1..Rn]` 注入 Prompt 引导模型选点，命中项落地权威字段与溯源；系统里不存在"用知识库候选直接拼装行程"的路径——LLM 失败时如实返回待研究草案，绝不冒充生成结果。候选池白名单的旧方案（LLM 只能从候选里选）已被引用式取代：白名单限定了内容来源，参考资料只提供证据。
2. **开放模式是主力**。早期候选池白名单规模不足，直接导致高预算行程的酒店选择被迫降档——这是切换的根因。现在 LLM 凭自身知识选点、高德落真实坐标，知识库规模不再限制行程上限。
3. **引用落地：名称精确/归一化/refs 编号三级匹配，只做全等不做子串包含**。「杭州西湖适合老人自然景点」包含「西湖」，若做包含匹配会被误路由；refs 与名称冲突时名称获胜，模型缩写经 refs 命中后名称归一为权威名，保证后续链路一致。
4. **缓存的安全边界比命中率重要**。降级结果与空结果一律不缓存——否则一次 DB 抖动会被固化 5 分钟；`index_version` 变化整体失效；近似命中只在同过滤签名桶内比较。
5. **查询路由只改执行路径，不改数据边界**。无意图查询走评分枚举、精确名走 BM25 直查，有意图才付出向量+精排的成本。
6. **每层降级都可观测、如实呈现**。精排挂→退融合排序；语义挂→退词法；DB 不可用→从 Chroma 元数据恢复；LLM 失败→待研究草案（不是假行程）。所有降级写入 trace 与 metrics，前端如实展示 degraded 原因。
7. **附近推荐只用真实坐标**。GraphRAG 空间网格近邻；坐标缺失一律返回空而不是伪造「附近」——假坐标做附近推荐会把用户导航到错误位置。
8. **评测口径严格分离**。离线单测 223 条（mock 模型输出、零外部依赖、可复现）与真实 LLM 评测（固定模型/temperature/Prompt 版本）分开报告；生成质量指标（引用覆盖率/refs 有效率/忠实度）已接入评测与遥测。
9. **多 Agent 只做证据分工，不做内容分工**。酒店/景点/美食三个研究 Agent 各自规划检索、评估证据充分性、必要时补查一轮，输出结构化证据包；Supervisor 的 LLM 仍是唯一行程内容来源（LLM-only 不变）。子 Agent 之间不通信（星型拓扑），证据缺口由 Supervisor 按校验反馈定向补查——分工的收益是并行与聚焦，代价是成本/延迟，用轮次上限 + 快模型控制。

## 功能特性

- **AI 行程生成**：LangGraph 编排 `parse → research → generate → reflect → format`，反思节点校验时间冲突/营业覆盖/路线可达/单日饱和度/**景点存在性**，不达标自动回喂修复；LLM 失败时返回待研究草案，绝不以知识库拼装行程冒充
- **国外目的地支持**：高德（仅中国）空结果自动切 Google Places / OSM Nominatim 落真实坐标，路线兜底 Google Routes / 坐标估算；前端国外自动切 Leaflet+OSM 免 key 地图；知识库可 `--cities 巴黎` 免 key 采集（Nominatim + Wikivoyage 原文）
- **多 Agent 研究编排**：酒店/景点/美食三个研究 Agent 并行收集证据（LLM 规划检索策略、评估充分性、不足补查一轮），Supervisor 汇总证据生成并驱动证据型缺口补查（如「无景点」→ 只重派发景点研究 Agent）；研究规模/推理轮次/降级/补查次数全部写入 trace 与 metrics。**边界：evidence-only 星型分工，不是完全自主 Multi-Agent**
- **Function Calling（受限）**：`poi_intros` 走 `run_tool_call_loop`，模型可调用 Tool Registry 只读工具（如 `search_pois`）补事实后再写介绍；失败回退单轮生成。生成主行程仍不依赖模型自由选工具
- **上下文记忆**：`app/agent/memory` 提供请求内 WorkingMemory（used_names/酒店）与对话滑窗；无长期向量记忆
- **事实溯源**：行程项携带 `source`（`mysql.poi_knowledge` / `amap.poi` / `llm.open_day`）、更新时间与核验状态；开放模式生成的地点标注「参考估算/待确认」，前端可见
- **附近推荐**：行程项一键展开知识库真实近邻（品类/评分/步行距离），数据来自权威库坐标网格，可一键跳高德
- **预算引擎**：门票按实际选中票价、餐饮按选中餐厅人均、酒店走「联网实时价 → 基准价×季节系数」定价链，编辑后实时重算（ECharts 看板）
- **地图可视化**：高德 JSAPI Marker 与行程列表双向联动
- **行程编辑**：拖拽排序、增删改、替换推荐、自然语言编辑、版本快照与回滚
- **附近检索工具化**：`find_nearby_pois` 注册进受控 Tool Registry，模型侧 function calling 与 HTTP API 共用同一实现
- **可观测**：`X-Agent-Run-ID` 关联全链路脱敏 Trace（含检索路由/缓存命中/工具调用/降级事件），`/v1/metrics` 暴露成功/降级/失败、token 分场景统计、缓存命中与路由分布，支持 Prometheus 文本格式
- **异步 PDF 导出**：任务表 + Spring `@Async` + Thymeleaf 模板 + 中文字体，轮询下载

## 目录结构

```
Travel-Assistant/
├── travel-backend-java/   # Spring Boot 3.2：认证/行程状态机/Redis 缓存/RestClient+熔断/异步 PDF/Agent 转发
├── travel-agent-python/   # FastAPI + LangGraph：LLM 生成/事实落地/RAG/评测/可观测
│   ├── app/rag/           # retriever(混合检索+路由+精排) store(同步+缓存+近邻图) evaluation(_generation)
│   ├── app/common/db_pool.py  # MySQL 连接池（复用/ping 自愈/上限）
│   ├── sql/enrich_pois.py # 数据管线（国内 高德+Wikivoyage / 国外 Nominatim+Wikivoyage → upsert → 索引同步）
│   └── tests/             # 223 条离线单测 + agent_eval(检索/研究/Agent/LLM 四套评测) + perf
├── travel-frontend-vue/   # Vue3：生成/详情/列表/地图/附近推荐/管理端
└── sql/                   # 建表 + 幂等增量脚本
```

## 快速开始

### 一键启停（推荐）

```bash
# 依赖（跨平台，推荐）
docker compose up -d mysql redis

# 或 Windows 脚本拉起全部本地进程
start-all.cmd   # Redis + 后端 + Agent + 前端
stop-all.cmd    # 一键全停（加 /I 连 Redis 一起停）
```

应用容器化（可选）：`docker compose --profile apps up -d --build`，详见 [docs/技术改造合集.md](docs/技术改造合集.md)。

前置条件：MySQL 已运行；首次使用完成「初始化数据库」与各端 `.env` 配置。

### 1. 初始化数据库

```bash
mysql -uroot -p < sql/schema.sql            # 完整表结构（含溯源/偏好/版本/导出表）
mysql -uroot -p < sql/seed_data.sql         # 兜底种子（后续被真实数据覆盖）
mysql -uroot -p travel_assistant < sql/migrate_current_schema.sql   # 已有库升级用
```

**灌入真实 POI 数据**（替代种子假数据，可 `--cities 杭州` 分城执行）。**跑管线前先执行迁移**（为 `poi_knowledge` 加 `avg_cost` 人均消费列 + `(city,name,category)` 唯一键 + 历史重复行收敛）：

```bash
mysql -uroot -p travel_assistant < sql/add_poi_avg_cost_and_unique.sql   # 建议先备份 poi_knowledge
cd travel-agent-python
.venv\Scripts\python.exe ..\sql\enrich_pois.py    # 默认零 LLM 模式：高德+Wikivoyage 原文，每城约 1-3 分钟
.venv\Scripts\python.exe ..\sql\enrich_pois.py --with-llm   # 可选：LLM 翻译/补齐（高质量，约 30-60 分钟）
```

### 2. 启动后端（travel-backend-java）

```bash
cd travel-backend-java
cp .env.example .env   # 必填 MYSQL_PASSWORD、JWT_SECRET（≥32）、AGENT_INTERNAL_TOKEN
mvn spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8"
```

### 3. 启动 Agent（travel-agent-python）

```bash
cd travel-agent-python
cp .env.example .env   # 填入 LLM_API_KEY、DB_PASSWORD、AGENT_INTERNAL_TOKEN（与 Java 一致）
uv sync
uv run python main.py  # 127.0.0.1:8000，启动时 warmup 并增量同步 RAG 索引
```

语义模型按需启用：`.env` 设 `RAG_EMBEDDING_PROVIDER=sentence-transformers`、`RAG_RERANK_PROVIDER=cross-encoder`（模型本地目录，见 `models/`）；未安装/未配置时自动降级哈希向量与融合排序，全流程仍可用。

### 4. 启动前端（travel-frontend-vue）

```bash
cd travel-frontend-vue
cp .env.example .env   # 填入 VITE_AMAP_JS_KEY / VITE_AMAP_SECURITY_CODE
npm install
npm run dev            # http://localhost:5173
```

> 高德 JS key 需在控制台配置 `localhost:5173` 域名白名单。未配置 `LLM_API_KEY` 时 Agent 如实返回待研究草案（知识库只作证据不生成内容），需完整体验生成功能请配置 LLM。

## 演示脚本（3 分钟走查）

1. **登录** → 生成页输入「杭州 · 2 天 · 2 人 · 自然风光/人文历史 · 预算 3000」
2. **详情页**：地图与列表联动；预算看板分门票/餐饮/交通/酒店；行程项展示来源与核验标签（知识库项「已核实/部分核实」，模型自选点「待确认」）
3. **附近推荐**：点任一景点行「附近」→ 展开知识库真实近邻（如西湖 → 龙井八景 692m、中国茶叶博物馆 1080m），点击跳高德
4. **编辑**：拖拽调序、替换酒店档位、自然语言改行程，预算实时重算
5. **导出**：发起 PDF 导出 → 轮询 → 下载
6. **可观测**（加分项）：响应头 `X-Agent-Run-ID` → `GET /api/agent/v1/runs/{id}` 看本次检索路由/缓存/工具调用轨迹；`GET /api/agent/v1/metrics` 看缓存命中率与路由分布

## 测试与评测

| 套件 | 命令（travel-agent-python 下） | 说明 |
| --- | --- | --- |
| 离线单测 | `uv run pytest --ignore=tests/api -q` | **249+ passed**，零外部依赖；覆盖检索路由/缓存/图/引用落地/反思/安全编辑/多 Agent/记忆/FC/MCP/审计回归 |
| Agent 离线评测 | `uv run python tests/agent_eval/eval_agent.py` | 固定权威 fixture：POI 权威率/字段引用/冲突/重复/预算/轨迹完整率/研究轮次与证据规模 |
| 多 Agent 研究评测 | `uv run python tests/agent_eval/eval_research.py` | 按域证据质量（规模/置信度/轮次/降级/缺口）+ Supervisor 补查有效率 |
| RAG 检索评测 | `uv run python tests/agent_eval/eval_retrieval.py` | Recall@5/10、MRR、NDCG、过滤准确率、偏好命中、权威引用率 |
| 生成质量评测 | `uv run python -m app.rag.evaluation_generation 杭州` | 引用覆盖率/refs 有效率/资料利用率 + LLM-judge 忠实度（默认 6 城） |
| 真实 LLM 评测 | `uv run python tests/agent_eval/llm_eval.py` | 固定模型/temperature/Prompt 版本，与离线结果分开报告 |
| Java 单测 | `mvn test`（travel-backend-java 下） | **25 passed**：预算引擎 + 生成编排状态机（部分失败续跑/幂等 409/恢复任务防死循环） |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` | 并发 QPS/p50/p95/p99 |

## 安全说明

- 真实密钥只存 `.env`（已 gitignore），仓库仅跟踪 `.env.example`；`.test-report/`、`.test-token.txt`、`.test-user.txt` 一并 ignore，禁止把测试 JWT/联调 dump 提交入库
- **提交/开源前必须 rotate**：LLM Key、高德 Web/JS Key、Unsplash Key、MySQL 密码、`JWT_SECRET`、`AGENT_INTERNAL_TOKEN`
- Java 启动强制校验：`JWT_SECRET` 非空且 ≥32 字符（`ENFORCE_SECRET_CHECK=true`，本地可临时关掉）；`AGENT_INTERNAL_TOKEN` 与 Python 侧一致
- Java ↔ Agent 内部调用支持 `AGENT_INTERNAL_TOKEN` 双端校验；Agent 绑定非回环地址且未配置 token 时启动直接 fail-fast，杜绝匿名烧钱接口
- `/api/amap/geocode`、`/api/amap/poi` 需登录（代理高德 Web API、消耗配额）；`staticmap`/`poi-photo`/`image` 仅作同源图片展示代理，参数校验/编码 + host 白名单 + **有界 LRU 缓存（2048）**
- 高德 MCP key 仅放服务端环境变量；Agent 默认只监听 `127.0.0.1`
- 生成/编辑类接口的错误响应只回通用文案，内部异常原文（字段校验/SQL/第三方报错）完整记日志不外泄；Trace 落盘前对 URL key 与 Bearer 令牌集中脱敏
- 行程项溯源字段（source/更新时间/核验状态）让「模型说的」和「知识库说的」在数据层面可区分；客户端传入的参考资料来源不在权威值域内时不背书，降级为待复核估算
- 登录按「IP+用户名」**滑动窗口**限速；**仅当 remoteAddr 命中 `TRUSTED_PROXIES` 才解析 `X-Forwarded-For`**；限速/日锁/续跑标记统一走 **Redis（`DistributedStateService`）**，故障降级进程内；**注册**密码 6–24 位且须含字母+数字（登录不做长度校验，兼容历史演示账号）；工程化改造汇总见 [docs/技术改造合集.md](docs/技术改造合集.md)
- **JWT 服务端吊销**：签发含 `jti`；`POST /api/auth/logout` 将 token SHA-256 写入 Redis 黑名单（TTL=剩余有效期）；鉴权过滤器拒绝已吊销 token；Redis 故障时降级进程内黑名单（仅单机）
- **会话凭据**：浏览器主通道为 **HttpOnly Cookie**（`TA_AUTH`，`SameSite=Lax`，可选 `Secure`）；**登录响应体不再回传 JWT**；支持 `POST /api/auth/logout-all` 多端登出；Cookie 会话的写请求校验 Origin 白名单（CSRF 缓解）
- 第三方合规：Wikivoyage 为 CC BY-SA（`source` 字段标注来源，衍生数据开源时需遵守 ShareAlike）；Nominatim UA 含联系方式；Google Places 缓存期限需遵守 Google Maps Platform 条款；Unsplash 按其 API 指南使用。本项目定位**本地演示/作品**，未做生产级合规审计

## 已知局限（面试/评审请先读）

| 局限 | 说明 |
| --- | --- |
| 非生产系统 | 单机演示；无集群、无真正多实例限流/会话吊销集群方案 |
| 酒店预算 | 默认 `LIVE_PRICE_SEARCH=true`（联网实时价搜索开启，受 `MAX_LIVE_QUERIES` 约束）；关闭后走「知识库基准价 × 季节系数」估算。两条路径都**不是 OTA 实时成交价** |
| 开放模式行程 | LLM 自选点标注「待确认/参考估算」，Reflection 校验时间与路线可达，**不保证店铺仍营业** |
| 双后端 | Vue→Java→Python：Java 负责鉴权/状态机/异步/PDF，Agent 负责智能；是有意拆分，非「必须生产形态」 |
| 生成编排 | **已合并为一张图** `trip_graph.unified_agent_graph`（mode=day/trip）；事实层 `day_stream`；口径 `generation_core`；`workflow`/`day_workflow` 为门面 |
| JWT | 无服务端吊销黑名单；logout 仅清前端态，有效期内 token 仍可用 |
| 评测 | 离线单测与真实 LLM 评测分开；小样本 faithfulness 不能外推全量 |

详见 [docs/校招面试审查报告.md](docs/校招面试审查报告.md) 与 [docs/代码审计报告.md](docs/代码审计报告.md)。

Agent 六大能力（记忆 / RAG / Harness / Multi-Agent / Function Calling / MCP）定位与迭代方案见 [docs/compose/spec/agent-capability-audit.md](docs/compose/spec/agent-capability-audit.md)。

## 开源 / 投递前安全清单

1. **Rotate** 全部第三方 Key（LLM / 高德 Web+JS / Unsplash / 可选 Google）与本地 `JWT_SECRET`、`AGENT_INTERNAL_TOKEN`、MySQL 口令  
2. 确认未跟踪任何 `.env`、`.test-report/`、`*.token`  
3. 运行 `pwsh scripts/check-secrets.ps1`  
4. 阅读 [docs/合规与开源安全.md](docs/合规与开源安全.md)（第三方 ToS、CC BY-SA、Nominatim/Google 缓存政策）  
5. 若历史提交曾含真实 Key：必须在服务商侧作废旧 Key，勿假设「删文件=安全」  
6. 投递/演示前按 [docs/投递前人工QA清单.md](docs/投递前人工QA清单.md) 勾选 Go/No-Go
