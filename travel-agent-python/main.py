"""FastAPI 应用入口。

职责：
- 组装 FastAPI 应用、挂载 CORS 与路由、定义启动生命周期。

实现要点：
- 启动时通过 lifespan 预热 RAG 索引（warmup_rag）并导出 openapi.json；
- 生成任务的自动续跑扫描与两个有界池的优雅关闭也挂在同一个 lifespan 上；
- 按 settings.agent_cors_origins 配置跨域来源；
- 把 app.api.agent.router 挂载到 /api/agent 前缀；
- 本地以 uvicorn 运行 main:app（端口 8000，支持热重载）。

依赖：
- fastapi/uvicorn；app.api.agent；app.rag.store；app.common.config；
  app.services.generation_recovery / itinerary_generation。
"""

import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.observability import use_scene
from app.agent.usage_store import usage_store
from app.api import agent
from app.api.business import business_routers
from app.common.config import BASE_DIR, settings
from app.common.envelope import install_exception_handlers
from app.db import migrate as db_migrate
from app.rag.store import warmup_rag
from app.services import export_service, generation_recovery, itinerary_chat, itinerary_generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 安全 fail-fast：generate/adjust 等端点每次调用消耗真实 LLM token。
    # 绑定非回环地址却不配置内部令牌，等于匿名烧钱接口；启动即拒绝，
    # 避免"默认空 token 静默放行"在部署改 host 后裸奔。
    if settings.agent_host not in _LOCAL_HOSTS and not settings.agent_internal_token:
        raise RuntimeError(
            "AGENT_HOST 绑定非回环地址但未配置 AGENT_INTERNAL_TOKEN，"
            "生成类端点将匿名暴露并消耗 LLM 配额；请设置令牌或改回 127.0.0.1")
    # 会话签名密钥（切流量后本服务自己签发 TA_AUTH）：等价 Java `JwtProperties` 的
    # @NotBlank @Size(min=32)。默认空串必须拦下——那等于任何人都能伪造登录票。
    if len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET 未配置或短于 32 字符：本服务负责签发会话票，弱密钥可被伪造登录；"
            "请在 .env 里配置与（双跑期）Java 侧一致的密钥")
    warmup_rag()
    # 清理保留期之外的 LLM 用量明细（默认保留 90 天）。
    try:
        removed = usage_store.cleanup(90 * 86400)
        if removed:
            logging.getLogger(__name__).info("[usage] cleaned %d rows older than 90d", removed)
    except Exception as exc:
        logging.getLogger(__name__).warning("[usage] cleanup failed: %s", exc)
    with (BASE_DIR / "openapi.json").open("w", encoding="utf-8") as f:
        json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
    # 生成任务的自动续跑扫描（僵尸 GENERATING / 可续跑的 FAILED）
    generation_recovery.start_loop()
    try:
        yield
    finally:
        # 滚动发布时不先把在跑的生成切掉：先停扫描，再等在跑的任务收尾（上限 30s，同 Java
        # 的 awaitTerminationSeconds），最后才关池。
        generation_recovery.stop_loop()
        for pool in (itinerary_generation.generation_pool, itinerary_generation.enricher_pool,
                     export_service.export_pool, itinerary_chat.chat_pool):
            try:
                pool.shutdown()
            except Exception as exc:  # noqa: BLE001 - 关闭阶段的失败不该掩盖退出原因
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

app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
# 迁移自 Java 的业务域：router 自带完整 /api/... 前缀，便于按路径前缀灰度切流
for business_router in business_routers:
    app.include_router(business_router)


if __name__ == "__main__":
    # 启动即迁移（等价 Java 侧 Flyway）：空库建表、既有库只打点。放在这里而不是 lifespan，
    # 是为了让测试与 import 永不触发真库连接；失败即拒绝启动，避免服务"起来了但表是空的"。
    try:
        db_migrate.ensure_schema()
    except Exception as exc:  # noqa: BLE001 - 启动期的迁移失败必须让人看见
        logging.getLogger(__name__).error("schema migration failed: %s", exc)
        raise
    uvicorn.run("main:app", host=settings.agent_host, port=8000, reload=settings.agent_reload)
