"""全局运行配置。

职责：
- 从环境变量（.env）读取服务运行所需的全部配置项，集中暴露为单例 settings。

实现要点：
- 启动时解析 BASE_DIR 并加载根目录 .env；
- Settings 用类属性默认值 + _get 辅助读取，缺失时使用安全默认值；
- 敏感项（LLM_API_KEY、DB_PASSWORD、AGENT_INTERNAL_TOKEN）仅来自环境变量，不落库。

依赖：
- python-dotenv；无内部依赖。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 先加载仓库根目录共享 .env，再加载本模块 .env（同名变量后者优先）
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str) -> str:
    return os.getenv(name, default)


def _get_bool(name: str, default: bool = False) -> bool:
    return _get(name, str(default)).lower() in ("1", "true", "yes")


class Settings:
    agent_host: str = _get("AGENT_HOST", "127.0.0.1")
    agent_reload: bool = _get_bool("AGENT_RELOAD", False)
    agent_cors_origins: str = _get("AGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    llm_base_url: str = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = _get("LLM_API_KEY", "")
    llm_model: str = _get("LLM_MODEL", "qwen-plus")
    # 结构化意图识别/行程草稿编辑优先使用低延迟模型；可留空以复用主模型。
    llm_fast_model: str = _get("LLM_FAST_MODEL", "qwen-turbo")
    llm_timeout: float = float(_get("LLM_TIMEOUT", "60"))
    agent_internal_token: str = _get("AGENT_INTERNAL_TOKEN", "")
    live_price_search: bool = _get("LIVE_PRICE_SEARCH", "true").lower() in ("1", "true", "yes")
    max_live_queries: int = int(_get("MAX_LIVE_QUERIES", "3"))
    amap_web_key: str = _get("AMAP_WEB_KEY", "")
    # 高德官方 MCP Server（推荐 Agent 侧使用）。URL 可填完整的
    # https://mcp.amap.com/mcp?key=...，也可单独配置 AMAP_MCP_KEY。
    amap_mcp_enabled: bool = _get("AMAP_MCP_ENABLED", "false").lower() in ("1", "true", "yes")
    amap_mcp_url: str = _get("AMAP_MCP_URL", "https://mcp.amap.com/mcp")
    amap_mcp_key: str = _get("AMAP_MCP_KEY", "")
    amap_mcp_timeout: float = float(_get("AMAP_MCP_TIMEOUT", "15"))
    unsplash_access_key: str = _get("UNSPLASH_ACCESS_KEY", "")
    poi_image_wiki: bool = _get("POI_IMAGE_WIKI", "true").lower() in ("1", "true", "yes")
    default_budget: float = float(_get("DEFAULT_BUDGET", "1000"))
    # RAG 检索配置。hashed 是零外部依赖的离线默认值；semantic 使用可选的
    # sentence-transformers，本地模型不可用时由检索层自动降级到 hashed。
    rag_embedding_provider: str = _get("RAG_EMBEDDING_PROVIDER", "hashed")
    rag_embedding_model: str = _get("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    rag_top_k: int = int(_get("RAG_TOP_K", "20"))
    rag_rrf_k: int = int(_get("RAG_RRF_K", "60"))
    rag_document_version: str = _get("RAG_DOCUMENT_VERSION", "poi-fields-v2")
    db_host: str = _get("DB_HOST", "localhost")
    db_port: int = int(_get("DB_PORT", "3306"))
    db_user: str = _get("DB_USER", "root")
    db_password: str = _get("DB_PASSWORD", "")
    db_name: str = _get("DB_NAME", "travel_assistant")


settings = Settings()
