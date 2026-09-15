# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ 多 Agent 研究 + RAG 权威知识库** 的旅行规划系统。输入城市、天数、偏好与一句话旅行意图，Agent 生成带事实溯源的每日行程：知识库条目标注来源与更新时间，模型自选点显式标记「出发前复核」；生成过程通过 SSE 实时推送进度，支持地图可视化、拖拽编辑、自然语言改行程、附近推荐、预算看板与 PDF 导出。后端为**单一 FastAPI 服务**（Python 3.12）：业务接口、agent 编排与事件流同进程，Spring Boot 版已退役删除（见「后端演进」）。

> **零第三方地理 API（2026-09-15，含底图刷新）**：POI 检索读本地 `poi_knowledge`（`/api/pois`），底图为 **OpenFreeMap** 免 key 在线矢量瓦片（MapLibre 样式文档，署名随图，观感对齐开源项目 TREK），路线默认坐标估算并如实标记 `degraded`——除 LLM 外，运行时不需要任何注册、key 或配额；底图瓦片之外的既有数据断网也能完整演示。图片仍可走 Unsplash/Pexels/维基（服务端代理，可选、未命中落占位块）。

## 功能特性

- **AI 行程生成（整段流式 + SSE 实时进度）**：全新行程一次 LLM 调用生成整趟——模型看得见全盘，跨天重复、片区走回头路在生成源头收敛；边流边解析、逐天落坐标与落库，并经进程内事件总线把进度推给 SSE 订阅者，前端逐天点亮，断线自动降级回轮询；流中断/缺天自动降级逐日修复（含单日反思闭环：时间冲突 / 路线可达 / 营业时间覆盖 / 节奏饱和度 / 预算超支等 11 类规则，不达标回喂重试）
- **意图优先**：一句话旅行意图（如「巴塞罗那 3 天：高迪建筑 + 老城美食，住老城方便步行」）作为最高优先级生成信号，驱动主题提炼、研究检索词补池与选点；行程输出主题标题、每日叙事、拍照机位、可执行提示、天气备选与方案分叉
- **多 Agent 研究编排**：酒店 / 景点 / 美食三个研究 Agent 并行收集证据（LLM 规划检索策略、评估充分性、不足补查一轮），Supervisor 汇总生成并按校验反馈定向补查；证据规模 / 轮次 / 降级 / 补查全部写入 trace 与 metrics
- **事实溯源**：行程项携带 `source`（本地知识库 / 开放研究 / 模型）、更新时间与核验状态；开放模式生成的地点标注「参考估算 / 待确认」，前端可见
- **海外目的地支持**：点位来自本地知识库（离线采集管线可免 key 采海外城市：Nominatim + Wikivoyage 原文），任意城市只要有库内数据就能加点；库内没有的城市坐标如实留空并在界面提示
- **对话式编辑**：自然语言修改已生成行程（换酒店、调节奏、加减天数），SSE 流式返回草稿卡片，确认后应用并联动预算重算
- **点位导航**：行程行与贴底详情卡均带地图跳转外链（外部超链接，非 API 依赖）；附近推荐只用本地库内的真实坐标与距离
- **预算横条**：门票按实际选中票价、餐饮按选中餐厅人均、酒店走「LLM 联网挂牌价（可选）→ 基准价 × 季节系数」定价链，编辑后实时重算（详情页头部横向预算条 + 天级小计）
- **行程管理**：拖拽排序（含跨天）、增删改、行内时间/费用快捷编辑、酒店档位替换、发现面板排入/拖拽入天、选择态批量条、优化路线（确定性重排 + 快照可回滚）、版本快照与回滚
- **异步 PDF 导出**：导出任务表 + 进程内有界工作池（池满退回请求线程就地渲染，任务不丢）+ reportlab 排版印刷版行程单（含叙事字段与预算附录），完成后经事件通道通知下载
- **可观测**：`X-Agent-Run-ID` 关联全链路脱敏 Trace（检索路由 / 缓存命中 / 工具调用 / 降级事件 / 流式事件），`/v1/metrics` 暴露成功 / 降级 / 失败、token 分场景统计、缓存命中与路由分布，支持 Prometheus 文本格式
- **外观契约（令牌工程，非主题包）**：中性 slate 面 + 单一强调色；三套 scheme × **日间/夜间双主题（默认日间）** × 紧凑密度（含字号倍率）× 减弱动效（系统偏好与手动覆盖两路），首帧无 FOUC（内联引导脚本 + 唯一运行时写入口 `appearance.ts`）；**玻璃面只用于有内容流过的表面**（顶栏/日目录/分享页轻顶栏），静态卡片一律白卡 + 发丝边；登机牌 Hero 的**票根**（两侧半圆缺口 + 虚线分隔 + 双语微标签）与统计行的**深色护照卡**、mono 计数行等设计细节对齐 TREK（见 `theme.css` 与 SPEC §18）；`npm run theme:lint` 机器强制禁裸色与野 z-index，豁免表只准变短
- **v2.6 设计升级（对标 TREK + Wanderlog）**：详情页重做为**三栏工作台**（行程/地图/发现 + 贴底详情卡，≥1280 常驻、逐级折叠到单列分段）；顶部**胶囊导航**；**per-day day-tint** 令牌（日头/编号徽/站点行/地图钉/TOC 同源取色）；产品主路径交互控件换为**自研 `components/ui` 层**（`npm run ep:lint` 对 Element Plus **只减不增**强制，CI 已接）；拉丁字体换为自托管 Geist；Wanderlog 式流程（拖拽入天/就近推荐/选择态批量/优化路线端点）——完整规格见 SPEC §19

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
                                          │ Redis        │ 缓存/限速/日锁/会话吊销（事件不再过 Redis）
                                          └──────────────┘
```

**分层**：前端只做展示与交互；FastAPI 服务同时承担两件事——**业务面**（认证、行程状态机、缓存、异步 PDF 导出、SSE 事件流）与 **Agent 面**（LLM 编排、多 Agent 研究、事实落地与质量校验），两者同进程直调，省掉跨语言序列化与一条 SSE 转发桥。知识库永远只作证据：检索结果以编号参考资料注入 Prompt 引导模型选点，命中项落地权威字段与溯源；系统不存在「用知识库候选直接拼装行程」的路径，LLM 失败时如实返回待研究草案。

**后端演进（Java 版已删除）**：这个项目最初是「Vue + Spring Boot + Python Agent」三端结构，Spring 侧承载认证 / 行程状态机 / 缓存 / PDF / SSE 网关。为了把 agent 能力与持久化放进同一进程，后端已按绞杀者路线整体迁到 FastAPI：**Java 侧 50 个业务端点有 49 个在 FastAPI 上等价落地**（剩下 1 个是刻意退役的内部探针），迁移完成后该模块已从工作树删除——它原先依赖的 schema SQL 与印刷字体已迁入本仓（各一份，避免双份真相漂移）。旧代码随时可从 git 历史取回，恢复步骤与「原先谁负责什么」的对照表见 `ARCHIVED.md`；跨语言的契约与 16 条陷阱记录见 `docs/PLAN-后端统一到FastAPI-v3.md`。

## 快速开始

### 前置条件

- Docker（MySQL 8 + Redis）或本地同版本服务
- JDK 17、Node.js 18+、Python 3.12 + [uv](https://docs.astral.sh/uv/)
- LLM API Key（阿里云百炼等 OpenAI 兼容端点）——地理能力全部本地化，不需要任何地图/POI 平台的 key

### 1. 初始化数据库与基础设施

```bash
docker compose up -d mysql redis
# 表结构无需手工执行 SQL：后端启动时自动迁移（Alembic 按版本序执行同一批 db/migration/V*.sql；
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

表结构由后端启动时的自动迁移创建（Alembic 按版本序执行 `db/migration/V*.sql`），之后可灌数据；种子仅为兜底，生产质量的数据由**离线**采集管线生成（默认零 LLM：Wikivoyage 免 key，可选高德源需 key；每城约 1-3 分钟）：

```bash
mysql -uroot -p travel_assistant < sql/seed_data.sql    # 兜底种子（可被真实数据覆盖）
cd travel-agent-python
uv run python ../sql/enrich_pois.py            # 国内 6 城；--cities 巴黎 采集海外城市
uv run python ../sql/enrich_pois.py --with-llm # 可选：LLM 翻译/补齐（约 30-60 分钟）
```

## 测试与评测

| 套件 | 命令 | 说明 |
| --- | --- | --- |
| 离线单测 | `uv run pytest tests/ --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval -q`（travel-agent-python 下） | 零外部依赖（模型 / DB / 外部服务全走离线替身，数量以 CI 为准）；覆盖事件契约校验与漂移门禁 / 断流取消 / 事件发布 / 叙事契约 / 引用落地 / 跨天双通道去重 / 流式解析 / 反思 / 多 Agent / 海外守卫 / SSE 与对话改行程 / PDF 导出 / 后台管理 / 启动即迁移等 |
| 活栈契约测试 | `uv run pytest tests/api -q`（需先起后端） | 登录 / 行程 / 导出 / 后台的端到端契约；默认打 `127.0.0.1:8000`（`API_BASE_URL` 可覆盖） |
| 迁移完成度门禁 | `uv run python scripts/check_endpoint_coverage.py`（CI 内自动执行） | 解析 Java 控制器映射并与装配后路由求差集；残留端点必须逐条登记，数字不靠手抄 |
| 切流量契约门禁 | `uv run pytest tests/test_cutover_contract.py -q`（离线套件内） | 静态扫描前端调用点（含 `fetch`/`EventSource`）与活栈测试路径，断言全部由 FastAPI 提供；另查前端不得硬编码 `:8080` |
| Java 单测（源码已删除） | 需先按 `ARCHIVED.md` 从 git 历史取回模块与资源 | 迁移前第一实现的编排 / 幂等 / SSE 网关用例，仅供历史对照 |
| Agent 离线评测 | `uv run python tests/agent_eval/eval_agent.py` | POI 权威率 / 字段引用 / 冲突 / 重复 / 预算 / 轨迹完整率 |
| 多 Agent 研究评测 | `uv run python tests/agent_eval/eval_research.py` | 按域证据质量 + Supervisor 补查有效率 |
| RAG 检索评测 | `uv run python tests/agent_eval/eval_retrieval.py`（`--provider semantic` 走本地语义模型） | Recall@k、MRR、NDCG、权威引用率 |
| 真实 LLM 评测 | `uv run python tests/agent_eval/llm_eval.py` | 固定模型 / temperature / Prompt 版本；`--cases tests/agent_eval/themed_cases.json` 跑三套同题主题评测 |
| 前端 | `npm run build`（travel-frontend-vue 下） | vue-tsc strict + vite 构建门禁 |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` | 并发 QPS / p50 / p95 / p99 |

## 目录结构

```
Travel-Assistant/
├── ARCHIVED.md             # Java 版（Spring Boot）退役说明：位置对照表 + 从 git 历史取回的命令
├── travel-agent-python/    # FastAPI 单进程后端 + LangGraph：业务接口 / LLM 生成 / 多 Agent 研究 / 事实落地 / RAG / 评测 / 可观测
│   ├── app/agent/          # 编排图 / 研究 Agents / 生成器 / 反思 / 事件发布
│   ├── app/rag/            # retriever(混合检索+路由+精排) store(同步+缓存+近邻图)
│   ├── app/db/             # ORM 模型 / 会话与逻辑删除作用域 / Alembic（按序执行共享的 V*.sql）
│   ├── app/api/business/   # 业务域（鉴权/行程/本地点位检索/图片代理/导出/后台），按前缀即可灰度切流
│   ├── app/prompts/        # Prompt 模板（版本化）
│   ├── scripts/            # 端点覆盖度核对 / schema 契约核对 / 契约导出 / RAG 模型预置
│   └── tests/              # 离线单测 + tests/api 活栈契约 + agent_eval(评测集与报告) + perf
├── travel-frontend-vue/    # Vue3：生成 / 三栏工作台(行程·地图·发现) / 列表 / 图鉴 / 管理端
│   ├── src/components/ui   # 自研交互控件层（去 EP 的落点；ep:lint 门禁只减不增）
│   ├── src/components/trip # 工作台子组件（日卡/地图面板/发现面板/贴底详情卡/预算条…）
│   ├── src/store           # Pinia（用户 / 行程单一数据源）
│   └── src/composables     # SSE 订阅 / 乐观操作 / 图片降级 / 发现排入（useDiscoverAdd）
├── sql/                    # 数据种子与采集管线；archive/ 为 Flyway 之前的增量脚本留档
└── docs/                   # 项目文档
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
