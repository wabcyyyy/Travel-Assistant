"""FastAPI 应用入口。

职责：
- 组装 FastAPI 应用、挂载 CORS 与路由、定义启动生命周期。

实现要点：
- 启动时通过 lifespan 预热 RAG 索引（warmup_rag）并导出 openapi.json；
- 按 settings.agent_cors_origins 配置跨域来源；
- 把 app.api.agent.router 挂载到 /api/agent 前缀；
- 本地以 uvicorn 运行 main:app（端口 8000，支持热重载）。

依赖：
- fastapi/uvicorn；app.api.agent；app.rag.store；app.common.config。
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
from app.common.config import BASE_DIR, settings
from app.rag.store import warmup_rag

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
    yield


app = FastAPI(title="travel-agent-python", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.agent_cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router, prefix="/api/agent", tags=["agent"])


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.agent_host, port=8000, reload=settings.agent_reload)
