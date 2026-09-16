# AGENTS.md — Travel-Assistant

## 项目是什么（3 句话）

AI 旅行规划 Agent：输入城市/天数/偏好/一句话意图，LangGraph 工作流（parse→research→generate→reflect→format）生成带事实溯源的每日行程，SSE 实时推送进度。
后端是**单一 FastAPI 进程**（`travel-agent-python/`，Python 3.12 + uv）：业务面 `/api/**` 与 Agent 面 `/api/agent/v1/**` 同进程直调；POI 证据来自本地 MySQL 权威库 + Qdrant 向量召回，**运行时除 LLM 外零第三方 API**。
前端是 Vue3 + Vite + TS（`travel-frontend-vue/`），MapLibre + OpenFreeMap 免 key 底图。

## 命令（在指明的目录下执行）

```bash
# 一键门禁（改任何 Python 代码后跑这个）：ruff check → ruff format --check →
# pyright 基线 ratchet → secret scan → 离线测试；与 CI preflight 同序同果
cd travel-agent-python && powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1

# 契约导出（改了 app/schemas/ 后必须跑，产物入仓，CI 校验漂移）
cd travel-agent-python && uv run python scripts/export_contracts.py

# 离线评测（mock 驱动，无需 LLM key；行为类改动后对比指标）
cd travel-agent-python && uv run python tests/agent_eval/eval_agent.py
cd travel-agent-python && uv run python tests/agent_eval/eval_research.py

# 前端构建与门禁
cd travel-frontend-vue && npm run build && npm run theme:lint && npm run ep:lint
```

## 跨仓约定

- **契约单一源**：跨端线级模型全部定义在 `travel-agent-python/app/schemas/**`（登记表 `app/schemas/contracts.py` 的 CONTRACT_GROUPS：agent_api + business_api；事件在 `stream_events.py`），`scripts/export_contracts.py` 据此导出 `contracts/*.schema.json` + `contracts/openapi.json` + 前端生成类型 `travel-frontend-vue/src/types/generated/contracts.ts`（前端契约类型只准引它）。改 schema → 重新导出 → 产物随同一 commit 入仓；CI 与本地 check.ps1 都有 drift 门禁，手改 `contracts/` 或生成类型必红。
- **Java 已退役**：`travel-backend-java/` 已删除，FastAPI 是唯一后端。不要以任何形式复活第二份后端实现；历史与恢复步骤只看 `ARCHIVED.md`。业务端点的行为基准是 `tests/api` 契约与 `tests/test_cutover_contract.py`。
- **数据库迁移 append-only**：SQL 真相源是 `travel-agent-python/app/db/migrations/sql/V*.sql`，已入库的迁移文件禁止修改/重排，新变更只能追加新版本。

## 哲学（违反任何一条的 PR 请先停下来说明）

1. **单一真源**：每类事实只有一份权威定义（schema 在 app/schemas、SQL 在 db/migrations、env 键在 app/common/config.py + .env.example）。副本必然漂移，不允许出现第二份。
2. **门禁只升不降**：静态检查、测试、eval 基线只许收紧。放宽门禁的改动需要在本文件留注释与期限。
3. **代码赢过文档**：文档与代码冲突时，先修文档使其对齐代码事实；描述"将要做的重构"的文档不放仓库。
4. **接缝就地迁移，不加包装层**：改接口签名时直接迁移全部调用方，不保留兼容 shim/re-export 包装层。
5. **AI 写的必须有人读懂**：不引入没人能解释清楚的代码；新增依赖必须在 commit message 里给出理由。

## 分层细则

- Python 包：看 `travel-agent-python/AGENTS.md`（不变量、错误边界、数据访问选址）。
- 前端：看 `travel-frontend-vue/AGENTS.md`（外观门禁、组件拆分）。
