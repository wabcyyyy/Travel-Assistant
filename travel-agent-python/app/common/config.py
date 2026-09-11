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
    # 行程 JSON 生成默认走低延迟模型；如需更高质量可显式指定主模型。
    llm_generation_model: str = _get("LLM_GENERATION_MODEL", "")
    llm_timeout: float = float(_get("LLM_TIMEOUT", "60"))
    # httpx 连接池：限制对 LLM 网关的并发 TCP 连接，避免无界握手
    llm_pool_max_connections: int = int(_get("LLM_POOL_MAX_CONNECTIONS", "20"))
    llm_pool_max_keepalive: int = int(_get("LLM_POOL_MAX_KEEPALIVE", "10"))
    llm_connect_timeout: float = float(_get("LLM_CONNECT_TIMEOUT", "5"))
    agent_internal_token: str = _get("AGENT_INTERNAL_TOKEN", "")
    # 实时酒店价格会额外触发联网搜索/模型调用，默认关闭以保证行程先快速可用；
    # 需要价格核实时可显式设置 LIVE_PRICE_SEARCH=true，并限制查询数量。
    live_price_search: bool = _get("LIVE_PRICE_SEARCH", "false").lower() in ("1", "true", "yes")
    max_live_queries: int = int(_get("MAX_LIVE_QUERIES", "1"))
    amap_web_key: str = _get("AMAP_WEB_KEY", "")
    # 高德官方 MCP Server（推荐 Agent 侧使用）。URL 可填完整的
    # https://mcp.amap.com/mcp?key=...，也可单独配置 AMAP_MCP_KEY。
    amap_mcp_enabled: bool = _get("AMAP_MCP_ENABLED", "false").lower() in ("1", "true", "yes")
    amap_mcp_url: str = _get("AMAP_MCP_URL", "https://mcp.amap.com/mcp")
    amap_mcp_key: str = _get("AMAP_MCP_KEY", "")
    amap_mcp_timeout: float = float(_get("AMAP_MCP_TIMEOUT", "15"))
    # 国外目的地兜底提供商（provider chain: 高德 → Google）。配置 key 后，
    # 高德无结果的检索/路线自动切 Google Places/Routes；未配置则保持现状。
    google_maps_api_key: str = _get("GOOGLE_MAPS_API_KEY", "")
    google_maps_timeout: float = float(_get("GOOGLE_MAPS_TIMEOUT", "10"))
    # OSM Nominatim 免 key 兜底：国内网络经常超时，默认关闭以免拖垮 Agent
    # Deadline。需要海外坐标且无 Google key 时可显式打开（已有熔断）。
    nominatim_enabled: bool = _get_bool("NOMINATIM_ENABLED", False)
    # 路线服务默认关闭真实联网查询，保证本地/测试环境仍可离线运行；开启后
    # 优先调用高德路线 API，失败自动回退坐标估算并标记 degraded。
    route_service_enabled: bool = _get_bool("ROUTE_SERVICE_ENABLED", False)
    route_mode: str = _get("ROUTE_MODE", "walking")
    route_timeout: float = float(_get("ROUTE_TIMEOUT", "8"))
    route_cache_ttl: float = float(_get("ROUTE_CACHE_TTL", "900"))
    route_peak_factor: float = float(_get("ROUTE_PEAK_FACTOR", "1.25"))
    route_max_calls: int = int(_get("ROUTE_MAX_CALLS", "64"))
    # 每次 Agent 请求允许的工具调用总数；单工具上限由 Tool Registry 控制。
    tool_max_calls: int = int(_get("TOOL_MAX_CALLS", "32"))
    agent_deadline_seconds: float = float(_get("AGENT_DEADLINE_SECONDS", "90"))
    max_llm_calls: int = int(_get("MAX_LLM_CALLS", "8"))
    max_token_budget: int = int(_get("MAX_TOKEN_BUDGET", "12000"))
    # 单次 run 内检索/证据类调用上限（研究补查、RAG、外部 POI）
    max_retrievals: int = int(_get("MAX_RETRIEVALS", "48"))
    max_replans: int = int(_get("MAX_REPLANS", "3"))
    no_progress_limit: int = int(_get("NO_PROGRESS_LIMIT", "2"))
    trace_storage_enabled: bool = _get_bool("TRACE_STORAGE_ENABLED", True)
    trace_storage_path: str = _get("TRACE_STORAGE_PATH", str(BASE_DIR / "data" / "agent_traces.jsonl"))
    usage_db_path: str = _get("USAGE_DB_PATH", str(BASE_DIR / "data" / "llm_usage.db"))
    schedule_optimizer_enabled: bool = _get_bool("SCHEDULE_OPTIMIZER_ENABLED", True)
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
    # 精排（P0②）：cross-encoder 对融合候选做语义精排；默认 none 保持零依赖，
    # 部署时通过 .env 开启；模型不可用时检索层自动降级为仅融合排序。
    rag_rerank_provider: str = _get("RAG_RERANK_PROVIDER", "none")
    rag_rerank_model: str = _get("RAG_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    rag_rerank_candidates: int = int(_get("RAG_RERANK_CANDIDATES", "24"))
    # 查询路由（P2）：仅含城市/品类泛词的查询走评分枚举、精确地名走词法直查，
    # 减少无意图查询的向量与精排开销；路由只改执行路径，不改变权威数据边界。
    rag_router_enabled: bool = _get_bool("RAG_ROUTER_ENABLED", True)
    # 语义缓存（P2）：检索结果按精确键与语义近似键复用；降级结果与空结果不缓存。
    rag_cache_enabled: bool = _get_bool("RAG_CACHE_ENABLED", True)
    rag_cache_ttl_seconds: int = int(_get("RAG_CACHE_TTL_SECONDS", "300"))
    rag_cache_max_entries: int = int(_get("RAG_CACHE_MAX_ENTRIES", "512"))
    rag_cache_similarity: float = float(_get("RAG_CACHE_SIMILARITY", "0.95"))
    # 轻量 GraphRAG（P2）：同城坐标网格近邻 + 标签相邻，支撑“附近推荐”类查询。
    rag_graph_radius_m: int = int(_get("RAG_GRAPH_RADIUS_M", "2000"))
    rag_graph_nearby_limit: int = int(_get("RAG_GRAPH_NEARBY_LIMIT", "5"))
    # 索引新鲜度：加载后超过该秒数，下一次检索请求会惰性触发一次增量同步
    # （指纹比对，未变化的行不重新 embedding）。0 表示关闭、仅启动/force 时同步。
    # 解决"数据管线跑完后必须重启服务"的运维缺口。
    rag_refresh_seconds: int = int(_get("RAG_REFRESH_SECONDS", "60"))
    db_host: str = _get("DB_HOST", "localhost")
    db_port: int = int(_get("DB_PORT", "3306"))
    db_user: str = _get("DB_USER", "root")
    db_password: str = _get("DB_PASSWORD", "")
    db_name: str = _get("DB_NAME", "travel_assistant")
    # MySQL 连接池上限（Agent 侧只读知识库；管线写库共用同一池）
    db_pool_max: int = int(_get("DB_POOL_MAX", "10"))


settings = Settings()
