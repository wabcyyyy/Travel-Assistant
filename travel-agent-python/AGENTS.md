# AGENTS.md — travel-agent-python

单 FastAPI 进程：业务面（`app/api/business/` + `app/services/`）与 Agent 面（`app/agent/`）同进程。先读根 `../AGENTS.md`。

## 硬不变量（INV-1 ~ INV-10）

- **INV-1** 门禁只升不降；任何豁免必须留注释与期限。
- **INV-2** 行为类重构不得改变输出：以快照测试与 eval 指标为判据，下降即 revert。
- **INV-3** 数据库迁移 append-only，禁止修改/重排既有迁移文件（SQL 真相源在 `app/db/migrations/sql/`）。
- **INV-4** 图节点不得抛异常，一律路由到 fallback 节点。
- **INV-5** SSE 事件信封固定 5 键 camelCase `{type, itineraryId, seq, ts, data}`，seq 单调。
- **INV-6** 新增 env 键必须同步 `.env.example` 与 `tests/test_env_example_alignment.py`。
- **INV-7** 环境变量只准在 `app/common/config.py` 读取，业务代码禁裸读 `os.environ`。
- **INV-8** 后台任务禁裸 `asyncio.create_task`/`threading.Thread`，必须走 `app/common/task_pool.py`。
- **INV-9** 工具默认只读本地知识库；任何外部网络调用必须带超时与响应上限。
- **INV-10** 新增依赖必须在 commit message 中给出理由。

## 参考实现（新代码先抄谁）

- **业务面**（路由 + 服务 + 信封）：抄 `app/services/itinerary_query.py` 配合 `app/api/business/` 的路由写法——瘦路由、逻辑进 service、返回走 Result 信封。
- **Agent 面**（研究编排 + 工具 + 降级）：抄 `app/agent/research/`——子任务并行、证据包汇聚、失败响亮降级、全程 trace 事件。
- **生成链路**（行程内容组装）：先读 `app/agent/README.md` 的模块蓝图——它定义每模块职责、依赖方向（`stream → workflow → generators → generation_core`，禁反向）与"新增生成能力先抄谁"。

## 双轨错误边界（何时用哪个）

- **Agent 面**：LLM/检索/解析失败是**预期路径**。函数抛 `ValueError`（或返回降级标记），由图/流式层捕获后路由到 fallback（INV-4），对用户如实降级（待研究草案 / degraded 标记），绝不冒充成功。
- **业务面**：违反业务规则是**异常路径**。抛 `app/common/envelope.py` 的 `ApiError(status, message)`——status 既作 HTTP 状态码也作 body.code，由全局 handler 统一包成 `Result{code,message,data}` 信封。业务路由里不要 try/except 吞成 200。
- 判据：这条失败**有没有替代产出**？有（降级草案、缓存回退）→ agent 轨；没有（权限、校验、不存在）→ 业务轨。

## 边界（门禁机检，违反即红）

- **分层**：`app.api → app.services → app.agent`，禁反向与跨层（import-linter 契约 1）。
- **agent 门面**：api/services 只准 `from app.agent import X` 用 `app/agent/__init__.py` 的导出面；深路径 import agent 子模块即红（契约 2）。新增对外能力 = 在 `__init__.py` 登记 re-export + `__all__`。
- **跨模块共用符号**：agent 层内多模块共用的内部函数由所属模块去下划线提级为「跨模块 API」并在模块 docstring 登记（见 generators/day_stream/tools/workflow）；不搞第二份实现，也不靠门面转发内部符号。
- **工具面**：全部工具经 `app/agent/tool_registry.py` 注册表派发（预算/参数校验/审计全覆盖），禁 `getattr(tools, name)` 字符串派发。注册 handler 一律调用期读 `tools` 模块属性（晚绑定），保 `patch.object(tools, ...)` 可 mock。

## 数据访问选址（新增读写先选对门）

- **业务写**（行程/用户状态的写路径）→ `app/services/`（版本快照、缓存失效在 service 层做）。
- **agent 读**（POI/知识证据查询）→ `app/agent/poi_repository.py`，只读列白名单。
- **用户域** → `app/common/user_repository.py`。
- **缓存**（Redis / 进程内）→ `app/services/cache_store.py`（键命名与 TTL 对齐既有约定）。
- 不在路由、图节点、生成器里裸写 SQL。

## 命令

根目录 `just check` 等价于下面第一条（justfile 的配方只做委托，不重复步骤）。

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1  # 一键门禁（= CI preflight + 离线测试）
# 单项（check.ps1 的组成，同序）：ruff check . / ruff format --check . /
#   python scripts/typecheck.py（pyright 基线 ratchet，--update 只减不增）/
#   lint-imports（分层与门面边界）/ secret scan / 离线 pytest / 契约导出漂移
uv run pytest tests/ -q --ignore=tests/api --ignore=tests/perf --ignore=tests/agent_eval  # 离线测试
uv run python scripts/export_contracts.py        # 改 schemas 后导出契约（产物入仓）
uv run python tests/agent_eval/eval_agent.py     # 离线评测（行为改动后对比）
uv run pytest tests/api -q                       # 活栈契约（需先起服务）
```

行为防线（G-2.0，CI 的 `agent-eval` job 同款）：

- **流式快照**：`uv run pytest tests/test_stream_snapshot.py`——trip/day 两条链路的
  事件序列/DailyPlan 与 `tests/golden/stream_*.json` 逐字节比对。有意改口径：
  `GOLDEN_REGENERATE=1 uv run pytest tests/test_stream_snapshot.py`，**人工复核 diff 后**入库。
- **eval ratchet**：跑 `eval_agent.py` + `eval_research.py` 后
  `git diff --exit-code tests/agent_eval/report/`。离线护栏（实时价/联网入口哨兵）保证
  报告确定可复现，故报告字节即基线；指标口径见 `report/report.md`。
- 改 P2 拆分时先跑这两条：单测断言单点字段，它们断言**端到端行为与事件序列**。

配置：`app/common/config.py` 是 **pydantic-settings 字段定义式**（键名小写即环境变量名，如 `agent_host` ↔ `AGENT_HOST`）；新增键 = 加字段 + 同 PR 更新 `.env.example`（`tests/test_env_example_alignment.py` 会验）。启动校验在 `Settings.validate_boot()`（main.py lifespan 调）；依赖运行语境的安全检查（密钥强度、绑定地址）只放这里，不放 import 期。
