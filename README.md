# Travel Assistant 智能旅行助手

基于 **AI Agent（LangGraph）+ 多 Agent 研究 + RAG 权威知识库 + 高德地图** 的三端分离旅行规划系统。输入城市、天数、偏好与一句话旅行意图，Agent 生成带事实溯源的每日行程：知识库条目标注来源与更新时间，模型自选点显式标记「出发前复核」；生成过程通过 SSE 实时推送进度，支持地图可视化、拖拽编辑、自然语言改行程、附近推荐、预算看板与 PDF 导出。

## 功能特性

- **AI 行程生成（SSE 实时进度）**：LangGraph 编排 `parse → research → generate → reflect → format`，反思节点校验时间冲突 / 路线可达 / 单日饱和度 / 景点存在性，不达标自动回喂修复；生成进度（研究 → 逐日 → 管家讲解）经 Redis pub/sub + SSE 实时推送到前端，逐日点亮，断线自动降级回轮询
- **意图优先**：一句话旅行意图（如「京都 3 日《千恋万花》圣地巡礼，住柏悦」）作为最高优先级生成信号，驱动主题提炼、研究检索词补池与选点；行程输出主题标题、每日叙事、拍照机位、可执行提示、天气备选与方案分叉
- **多 Agent 研究编排**：酒店 / 景点 / 美食三个研究 Agent 并行收集证据（LLM 规划检索策略、评估充分性、不足补查一轮），Supervisor 汇总生成并按校验反馈定向补查；证据规模 / 轮次 / 降级 / 补查全部写入 trace 与 metrics
- **事实溯源**：行程项携带 `source`（知识库 / 高德 / 模型）、更新时间与核验状态；开放模式生成的地点标注「参考估算 / 待确认」，前端可见
- **国外目的地支持**：高德（仅中国）空结果自动切 Google Places / OSM Nominatim 落真实坐标，路线兜底 Google Routes / 坐标估算；前端国外自动切 Leaflet + OSM 免 key 地图；知识库可免 key 采集海外城市（Nominatim + Wikivoyage 原文）
- **对话式编辑**：自然语言修改已生成行程（换酒店、调节奏、加减天数），SSE 流式返回草稿卡片，确认后应用并联动预算重算
- **地图可视化**：高德 JSAPI（国内）/ Leaflet + OSM（国外）与行程列表双向联动；附近推荐只用真实坐标
- **预算看板**：门票按实际选中票价、餐饮按选中餐厅人均、酒店走「联网实时价 → 基准价 × 季节系数」定价链，编辑后实时重算（ECharts）
- **行程管理**：拖拽排序、增删改、酒店档位替换、备选池采纳、版本快照与回滚
- **异步 PDF 导出**：任务表 + Spring `@Async` + Thymeleaf 模板（含叙事字段），完成后经事件通道通知下载
- **可观测**：`X-Agent-Run-ID` 关联全链路脱敏 Trace（检索路由 / 缓存命中 / 工具调用 / 降级事件 / 流式事件），`/v1/metrics` 暴露成功 / 降级 / 失败、token 分场景统计、缓存命中与路由分布，支持 Prometheus 文本格式

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
                                   └──────┬───────┘   │ 引用式生成落地 → 近邻图 → 遥测     │
                                          │           └──────────────────────────────────┘
                                   ┌──────▼───────┐
                                   │ Redis        │ 缓存/限速/日锁/SSE 事件通道/会话吊销
                                   └──────────────┘
```

**三端分工**：前端只做展示与交互；Java 负责认证、行程状态机、缓存、异步 PDF 导出与 SSE 网关，并把生成请求转发给 Agent；Python Agent 负责 LLM 编排、多 Agent 研究、事实落地与质量校验，是唯一决定「行程内容从哪来」的一层。知识库永远只作证据：检索结果以编号参考资料注入 Prompt 引导模型选点，命中项落地权威字段与溯源；系统不存在「用知识库候选直接拼装行程」的路径，LLM 失败时如实返回待研究草案。

## 快速开始

### 前置条件

- Docker（MySQL 8 + Redis）或本地同版本服务
- JDK 17、Node.js 18+、Python 3.12 + [uv](https://docs.astral.sh/uv/)
- 高德开放平台 Web/JS Key（地图与 POI）；LLM API Key（阿里云百炼等 OpenAI 兼容端点）

### 1. 初始化数据库与基础设施

```bash
docker compose up -d mysql redis
mysql -uroot -p < sql/schema.sql                     # 完整表结构
mysql -uroot -p < sql/seed_data.sql                  # 兜底种子（可被真实数据覆盖）
```

### 2. 启动后端（travel-backend-java）

```bash
cd travel-backend-java
cp .env.example .env        # 必填 MYSQL_PASSWORD、JWT_SECRET（≥32 位）、AGENT_INTERNAL_TOKEN
mvn spring-boot:run
```

### 3. 启动 Agent（travel-agent-python）

```bash
cd travel-agent-python
cp .env.example .env        # 填入 LLM_API_KEY、DB_PASSWORD、AGENT_INTERNAL_TOKEN（与 Java 一致）
uv sync
uv run python main.py       # 127.0.0.1:8000；启动时预热并增量同步 RAG 索引
```

### 4. 启动前端（travel-frontend-vue）

```bash
cd travel-frontend-vue
cp .env.example .env        # 填入 VITE_AMAP_JS_KEY / VITE_AMAP_SECURITY_CODE
npm install
npm run dev                 # http://localhost:5173
```

> Windows 也可用根目录 `start-all.cmd` 一键拉起全部进程（`stop-all.cmd` 全停）。
> 未配置 `LLM_API_KEY` 时 Agent 如实返回待研究草案（不会用知识库拼装行程冒充结果）。

### 可选：灌入真实 POI 数据

种子数据仅为兜底；生产质量的数据由采集管线生成（默认零 LLM：高德 + Wikivoyage，每城约 1-3 分钟）：

```bash
mysql -uroot -p travel_assistant < sql/add_poi_avg_cost_and_unique.sql   # 先建 avg_cost 列与唯一键（建议备份）
cd travel-agent-python
uv run python ../sql/enrich_pois.py            # 国内 6 城；--cities 巴黎 采集海外城市
uv run python ../sql/enrich_pois.py --with-llm # 可选：LLM 翻译/补齐（约 30-60 分钟）
```

## 测试与评测

| 套件 | 命令 | 说明 |
| --- | --- | --- |
| 离线单测 | `uv run pytest tests/ --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval -q`（travel-agent-python 下） | **367 passed**，零外部依赖；覆盖契约对齐 / 事件发布 / 叙事契约 / 引用落地 / 反思 / 多 Agent / 海外守卫等 |
| Java 单测 | `mvn test`（travel-backend-java 下） | **106 passed**：编排状态机 / 幂等三层 / SSE 网关 / 事件发布器 / 契约反序列化 |
| Agent 离线评测 | `uv run python tests/agent_eval/eval_agent.py` | POI 权威率 / 字段引用 / 冲突 / 重复 / 预算 / 轨迹完整率 |
| 多 Agent 研究评测 | `uv run python tests/agent_eval/eval_research.py` | 按域证据质量 + Supervisor 补查有效率 |
| RAG 检索评测 | `uv run python tests/agent_eval/eval_retrieval.py` | Recall@k、MRR、NDCG、权威引用率 |
| 真实 LLM 评测 | `uv run python tests/agent_eval/llm_eval.py` | 固定模型 / temperature / Prompt 版本；`--cases tests/agent_eval/themed_cases.json` 跑三套同题主题评测 |
| 前端 | `npm run build`（travel-frontend-vue 下） | vue-tsc strict + vite 构建门禁 |
| 性能压测 | `uv run python tests/perf/load_test.py --endpoint all` | 并发 QPS / p50 / p95 / p99 |

## 目录结构

```
Travel-Assistant/
├── travel-backend-java/    # Spring Boot 3.2：认证 / 行程状态机 / SSE 网关 / 缓存 / 异步 PDF / Agent 转发
├── travel-agent-python/    # FastAPI + LangGraph：LLM 生成 / 多 Agent 研究 / 事实落地 / RAG / 评测 / 可观测
│   ├── app/agent/          # 编排图 / 研究 Agents / 生成器 / 反思 / 事件发布
│   ├── app/rag/            # retriever(混合检索+路由+精排) store(同步+缓存+近邻图)
│   ├── app/prompts/        # Prompt 模板（版本化）
│   └── tests/              # 离线单测 + agent_eval(评测集与报告) + perf
├── travel-frontend-vue/    # Vue3：生成 / 详情(叙事手册) / 列表 / 地图 / 管理端
│   ├── src/components/trip # 详情页子组件（逐日卡/叙事区/聊天编辑/备选池/导出…）
│   ├── src/store           # Pinia（用户 / 行程单一数据源）
│   └── src/composables     # SSE 订阅 / 乐观操作 / 图片降级
├── sql/                    # 建表 + 幂等增量迁移 + 数据管线
└── docs/                   # 项目文档
```

## 安全说明

- 真实密钥只存 `.env`（已 gitignore），仓库仅跟踪 `.env.example`；**公开 / 部署前必须 rotate** 全部第三方 Key 与本地 `JWT_SECRET`、`AGENT_INTERNAL_TOKEN`、MySQL 口令
- Java 启动强制校验 `JWT_SECRET`（非空且 ≥32 字符）；`AGENT_INTERNAL_TOKEN` 双端一致，Agent 绑定非回环地址且未配置 token 时启动 fail-fast
- **会话凭据**为 HttpOnly Cookie（`SameSite=Lax`），登录响应不回传 JWT；支持服务端吊销（`/api/auth/logout` 将 token 写入 Redis 黑名单）与多端登出；写请求校验 Origin 白名单（CSRF 缓解）
- 登录 / 注册按「IP + 用户名」滑动窗口限速，限速 / 日锁 / 续跑标记统一走 Redis，故障自动降级进程内
- 生成 / 编辑类接口的错误响应只回通用文案，内部异常原文完整记日志不外泄；Trace 落盘前对 URL key 与 Bearer 令牌集中脱敏
- 第三方合规：Wikivoyage 内容为 CC BY-SA（`source` 字段标注来源）；Nominatim UA 含联系方式；本项目定位**本地演示 / 学习项目**，未做生产级合规审计

## 已知局限

| 局限 | 说明 |
| --- | --- |
| 非生产系统 | 单机演示；无集群、无真正多实例限流 / 会话吊销集群方案 |
| 酒店价格 | 联网实时价与基准价估算都**不是 OTA 实时成交价** |
| 开放模式行程 | LLM 自选点标注「待确认 / 参考估算」，校验时间与路线可达，**不保证店铺仍营业** |
| 海外坐标 | 未配置 Google key 且 Nominatim 关闭时，海外地点坐标如实留空（前端提示配置 key 后恢复地图） |
| 评测口径 | 离线单测与真实 LLM 评测分开报告；小样本评测结果不能外推全量 |
