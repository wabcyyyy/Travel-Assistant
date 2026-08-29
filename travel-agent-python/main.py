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

from app.api import agent
from app.common.config import BASE_DIR, settings
from app.rag.store import warmup_rag

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup_rag()
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
