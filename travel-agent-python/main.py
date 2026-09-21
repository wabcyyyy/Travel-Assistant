"""FastAPI 应用入口。

职责：
- 组装 FastAPI 应用、挂载 CORS 与路由、定义启动生命周期。

实现要点：
- OpenAPI 只有一个生产者：`scripts/export_contracts.py` 导出 `contracts/openapi.json`
  （启动期不再落第二份，否则根目录产物与入仓产物会各说一套）；
- 生成任务的自动续跑扫描与两个有界池的优雅关闭也挂在同一个 lifespan 上；
- 按 settings.agent_cors_origins 配置跨域来源；
- 把 app.api.agent.router 挂载到 /api/agent 前缀；
- 本地以 uvicorn 运行 main:app（端口 8000，支持热重载）。

依赖：
- fastapi/uvicorn；app.api.agent；app.common.config；
  app.services.generation_recovery / itinerary_generation。
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.usage_store import usage_store
from app.api import agent, mcp
from app.api.business import business_routers
from app.api.security_headers import SecurityHeadersMiddleware
from app.common import cron
from app.common.config import settings
from app.common.envelope import install_exception_handlers
from app.db import migrate as db_migrate
from app.services import export_service, generation_recovery, itinerary_chat, itinerary_generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

logger = logging.getLogger(__name__)


def _cleanup_usage() -> None:
    """清理保留期之外的 LLM 用量明细（默认保留 90 天）；失败只告警（cron 会记）。"""
    removed = usage_store.cleanup(90 * 86400)
    if removed:
        logger.info("[usage] cleaned %d rows older than 90d", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动期配置校验（G-1.5）：安全 fail-fast（非回环绑定必须配内部令牌、
    # JWT 密钥强度）收拢在 Settings.validate_boot；坏配置 RuntimeError →
    # uvicorn 以非 0 退出，避免"起来了但配置是坏的"。
    settings.validate_boot()
    # 周期任务统一登记（G-3.3）：usage 清理每天一次、生成续跑 60s 一轮。
    # 两个任务都经 app.common.cron——pytest 环境自动 no-op，不再各写各的线程。
    cron.register("usage-cleanup", 86400, _cleanup_usage)
    generation_recovery.register_loop()
    cron.start_all()
    try:
        yield
    finally:
        # 滚动发布时不先把在跑的生成切掉：先停周期任务，再等在跑的任务收尾（上限 30s），
        # 最后才关池。
        cron.stop_all()
        for pool in (
            itinerary_generation.generation_pool,
            itinerary_generation.enricher_pool,
            export_service.export_pool,
            itinerary_chat.chat_pool,
        ):
            try:
                # `SlotExecutor.shutdown()` 是无超时的 `wait=True`，且会等在跑的 LLM
                # 调用（`llm_timeout=240s`）。直接 await 会冻住事件循环：健康检查失败 →
                # 容器被 SIGKILL → 留下成批 GENERATING 行等续跑。放到线程里并限时 30s，
                # 超时如实记日志继续关（旧注释写的"上限 30s"此前只是愿望，没有实现）。
                await asyncio.wait_for(asyncio.to_thread(pool.shutdown), timeout=30)
            except TimeoutError:
                logging.getLogger(__name__).warning("executor shutdown exceeded 30s; abandoning drain")
            except Exception as exc:
                logging.getLogger(__name__).warning("executor shutdown failed: %s", exc)


app = FastAPI(title="travel-agent-python", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.agent_cors_origins.split(",") if origin.strip()],
    # 业务接口以 HttpOnly Cookie(TA_AUTH) 为主凭据，跨源时必须允许携带凭据，
    # 否则浏览器不会带上 Cookie（Java 侧 CorsConfiguration 亦为 allowCredentials=true）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_exception_handlers(app)
# 全站安全响应头（R1-3）：纯 ASGI 包装，只补头、不缓冲 SSE
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(agent.router, prefix="/api/agent", tags=["agent"])

# MCP 只读工具出口（G-3.6）：addon 门控（默认关）+ AGENT_INTERNAL_TOKEN 鉴权，
# 两者都在 McpGate 里按请求实时判定——addon 关闭时整个前缀 404。
app.mount("/mcp", mcp.mcp_asgi_app())
# 迁移自 Java 的业务域：router 自带完整 /api/... 前缀，便于按路径前缀灰度切流
for business_router in business_routers:
    app.include_router(business_router)


if __name__ == "__main__":
    # 启动即迁移（等价 Java 侧 Flyway）：空库建表、既有库只打点。放在这里而不是 lifespan，
    # 是为了让测试与 import 永不触发真库连接；失败即拒绝启动，避免服务"起来了但表是空的"。
    try:
        db_migrate.ensure_schema()
    except Exception as exc:
        logging.getLogger(__name__).error("schema migration failed: %s", exc)
        raise
    uvicorn.run("main:app", host=settings.agent_host, port=8000, reload=settings.agent_reload)
