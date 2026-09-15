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


def _default_font_path() -> str:
    """印刷字体（simhei）已随「Java 退役」git mv 进本仓，全仓唯一一份。"""
    return str(BASE_DIR / "app" / "resources" / "fonts" / "simhei.ttf")


class Settings:
    agent_host: str = _get("AGENT_HOST", "127.0.0.1")
    agent_reload: bool = _get_bool("AGENT_RELOAD", False)
    agent_cors_origins: str = _get("AGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    llm_base_url: str = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = _get("LLM_API_KEY", "")
    llm_model: str = _get("LLM_MODEL", "qwen-plus")
    # 内容生成（行程/介绍/研究/对话决策）统一走低延迟模型；可留空以复用主模型。
    # qwen-turbo 省钱但对篇幅类软约束遵循差，默认 qwen-plus。
    llm_fast_model: str = _get("LLM_FAST_MODEL", "qwen-plus")
    llm_timeout: float = float(_get("LLM_TIMEOUT", "240"))
    # httpx 连接池：限制对 LLM 网关的并发 TCP 连接，避免无界握手
    llm_pool_max_connections: int = int(_get("LLM_POOL_MAX_CONNECTIONS", "20"))
    llm_pool_max_keepalive: int = int(_get("LLM_POOL_MAX_KEEPALIVE", "10"))
    llm_connect_timeout: float = float(_get("LLM_CONNECT_TIMEOUT", "5"))
    agent_internal_token: str = _get("AGENT_INTERNAL_TOKEN", "")
    # 实时酒店价格会额外触发联网搜索/模型调用，默认开启以核实价格；
    # 需要更快出首版行程可显式设置 LIVE_PRICE_SEARCH=false，并限制查询数量。
    live_price_search: bool = _get("LIVE_PRICE_SEARCH", "true").lower() in ("1", "true", "yes")
    max_live_queries: int = int(_get("MAX_LIVE_QUERIES", "3"))
    # 餐饮实时价（百炼联网）：与酒店实时价独立开关，同样受 max_live_queries 约束
    live_food_price_search: bool = _get("LIVE_FOOD_PRICE_SEARCH", "true").lower() in ("1", "true", "yes")
    max_live_food_queries: int = int(_get("MAX_LIVE_FOOD_QUERIES", "4"))
    # 研究/备选池证据不足时用联网搜索补候选（百炼 enable_search）
    web_search_enabled: bool = _get("WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes")
    max_web_search_queries: int = int(_get("MAX_WEB_SEARCH_QUERIES", "6"))
    # 主行程生成 Prompt 是否开 enable_search（更准但更慢，默认关；研究阶段已联网补池）
    llm_generation_web_search: bool = _get("LLM_GENERATION_WEB_SEARCH", "false").lower() in ("1", "true", "yes")
    # 生成后按估算总价是否触发超支修复（reflect 反馈重排）
    budget_hard_constraint: bool = _get("BUDGET_HARD_CONSTRAINT", "true").lower() in ("1", "true", "yes")
    # 超过预算多少比例才触发修复（避免贴近预算反复重试）
    budget_overage_ratio: float = float(_get("BUDGET_OVERAGE_RATIO", "0.08"))
    # 餐饮单价相对城市人均餐价的钳制倍数（硬顶/软顶）
    meal_price_hard_cap_ratio: float = float(_get("MEAL_PRICE_HARD_CAP_RATIO", "8"))
    meal_price_soft_cap_ratio: float = float(_get("MEAL_PRICE_SOFT_CAP_RATIO", "4"))
    # 路线矩阵校验：用**本地坐标估算**（haversine × 道路系数）产出路线矩阵，
    # 供排程校验与打分使用。默认关闭以保持既有生成结果不变；开启不产生任何
    # 外部调用（高德/Google 路线源已于 2026-09-15 随「去高德」移除）。
    route_service_enabled: bool = _get_bool("ROUTE_SERVICE_ENABLED", False)
    route_mode: str = _get("ROUTE_MODE", "walking")
    route_cache_ttl: float = float(_get("ROUTE_CACHE_TTL", "900"))
    route_peak_factor: float = float(_get("ROUTE_PEAK_FACTOR", "1.25"))
    route_max_calls: int = int(_get("ROUTE_MAX_CALLS", "64"))
    # 每次 Agent 请求允许的工具调用总数；单工具上限由 Tool Registry 控制。
    tool_max_calls: int = int(_get("TOOL_MAX_CALLS", "32"))
    agent_deadline_seconds: float = float(_get("AGENT_DEADLINE_SECONDS", "90"))
    # 研究三域（plan/evaluate×2 轮）+ 联网补池 + 整段生成 + 修复重试：
    # 旧默认 8 次会在研究阶段就耗尽，导致「开放研究重试耗尽」草案。
    max_llm_calls: int = int(_get("MAX_LLM_CALLS", "32"))
    max_token_budget: int = int(_get("MAX_TOKEN_BUDGET", "80000"))
    # 单次 run 内检索/证据类调用上限（研究补查、RAG、外部 POI）
    max_retrievals: int = int(_get("MAX_RETRIEVALS", "48"))
    max_replans: int = int(_get("MAX_REPLANS", "3"))
    no_progress_limit: int = int(_get("NO_PROGRESS_LIMIT", "2"))
    trace_storage_enabled: bool = _get_bool("TRACE_STORAGE_ENABLED", True)
    trace_storage_path: str = _get("TRACE_STORAGE_PATH", str(BASE_DIR / "data" / "agent_traces.jsonl"))
    usage_db_path: str = _get("USAGE_DB_PATH", str(BASE_DIR / "data" / "llm_usage.db"))
    # PDF 导出（M6）。字体全仓只有一份 9.7MB 的 simhei.ttf：今天在 Java 模块的 resources 下，
    # Java 退役后搬到 app/resources/fonts/——下面的解析顺序让**搬迁不需要改代码**。
    # 部署可用 EXPORT_DIR / EXPORT_FONT_FILE 覆盖。
    export_dir: str = _get("EXPORT_DIR", str(BASE_DIR / "data" / "export"))
    export_font_file: str = _get("EXPORT_FONT_FILE", _default_font_path())
    # 封面/上传图落盘根目录（SPEC v2.3 §6.1）：provider 快照与用户上传都写这里，
    # DB 只存 /api/uploads/... 应用路径；静态访问路由见 app/api/business/uploads.py。
    uploads_dir: str = _get("UPLOADS_DIR", str(BASE_DIR / "data" / "uploads"))
    # 封面上传大小上限（SPEC v2.3 §6.3 / S0-3）：FastAPI 不限制 multipart 体积，
    # 入口在 cover_service.read_upload_capped 里流式截断，超限 413。
    cover_upload_max_bytes: int = int(_get("COVER_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))
    # 分享匿名访问限流（SPEC v2.3 §6.6 / E14）：按 IP 滑动窗口，每分钟上限
    share_rate_limit_per_minute: int = int(_get("SHARE_RATE_LIMIT_PER_MINUTE", "60"))
    schedule_optimizer_enabled: bool = _get_bool("SCHEDULE_OPTIMIZER_ENABLED", True)
    unsplash_access_key: str = _get("UNSPLASH_ACCESS_KEY", "")
    # 图片多源解析的最后一级兜底图库（Java 侧 app.pexels.access-key 的等价项）。
    # Pexels 对中文查询几乎无命中，poi_photo 会先尝试把名称解析成英文再检索。
    pexels_access_key: str = _get("PEXELS_API_KEY", "")
    poi_image_wiki: bool = _get("POI_IMAGE_WIKI", "true").lower() in ("1", "true", "yes")
    default_budget: float = float(_get("DEFAULT_BUDGET", "1000"))
    # RAG 检索配置。默认 semantic：本地 bge-small-zh-v1.5 真语义向量
    # （需先跑 scripts/fetch_rag_model.py 预置模型；服务不隐式联网下载）。
    # 依赖或模型不可用时由检索层降级到 hashed 哈希向量，并记录 fallback 遥测
    # 与显式告警（不静默）。
    rag_embedding_provider: str = _get("RAG_EMBEDDING_PROVIDER", "semantic")
    rag_embedding_model: str = _get("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    # 语义模型本地缓存目录（fetch_rag_model.py 下载到此；相对路径按进程 cwd 解析）
    rag_model_cache_dir: str = _get("RAG_MODEL_CACHE_DIR", str(BASE_DIR / "models"))
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
    # 向量库（Qdrant）：url 非空走独立服务（生产共享/多实例可读）；默认本地
    # 嵌入式持久化模式（数据可随时由 MySQL 全量重建，持久化只为加速启动）。
    qdrant_url: str = _get("QDRANT_URL", "")
    qdrant_path: str = _get("QDRANT_PATH", str(BASE_DIR / "data" / "qdrant"))
    qdrant_collection: str = _get("QDRANT_COLLECTION", "poi_knowledge")
    qdrant_timeout: float = float(_get("QDRANT_TIMEOUT", "10"))
    db_host: str = _get("DB_HOST", "localhost")
    db_port: int = int(_get("DB_PORT", "3306"))
    db_user: str = _get("DB_USER", "root")
    db_password: str = _get("DB_PASSWORD", "")
    db_name: str = _get("DB_NAME", "travel_assistant")
    # MySQL 连接池上限（Agent 侧只读知识库；管线写库共用同一池）
    db_pool_max: int = int(_get("DB_POOL_MAX", "10"))
    # Redis Pub/Sub（AD2 SSE）：Python 节点向 gen:events:{itineraryId} 发布
    # 进度事件，由 Java SSE 网关订阅转发前端；事件是尽力而为通知，连不上只降级。
    # 地址与 Java 侧同口径：显式 REDIS_URL 优先，否则由 REDIS_HOST/REDIS_PORT 派生。
    # 默认 6380 对齐 start-all.ps1 起的本机 Redis（compose 内由 environment 传 6379）。
    redis_url: str = _get(
        "REDIS_URL",
        "redis://{}:{}/0".format(_get("REDIS_HOST", "localhost"), _get("REDIS_PORT", "6380")),
    )

    # 双跑期鉴权互认（PLAN v3.0 §1.1）：与 Java 服务共用同一 JWT_SECRET 与同一 Cookie，
    # 用户切域不需重登、灰度可回滚。变量名沿用 Java 侧 application.yml 既有约定。
    # 注意：DB 凭据两侧不同源——Java 读 MYSQL_*，本服务读 DB_*（见 compose environment）。
    # token 的 exp 写在 claims 里，两侧过期时钟不同也不会互判失效；差异只体现在
    # Cookie 的 Max-Age 上（无害），故本项可与 Java 的 expire-hours 独立设置。
    jwt_secret: str = _get("JWT_SECRET", "")
    jwt_expire_hours: int = int(_get("JWT_EXPIRE_HOURS", "24"))
    auth_cookie_secure: bool = _get_bool("AUTH_COOKIE_SECURE", False)
    jwt_revocation_prefer_redis: bool = _get_bool("APP_JWT_REVOKE_PREFER_REDIS", True)
    # 仅当对端地址命中该列表时才信任 X-Forwarded-For：否则伪造该头即可绕过按 IP
    # 的登录/注册限速（与 Java app.security.trusted-proxies 同口径）
    trusted_proxies: str = _get("TRUSTED_PROXIES", "127.0.0.1,0:0:0:0:0:0:0:1,::1")


settings = Settings()
