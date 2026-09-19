"""全局运行配置（pydantic-settings 字段定义式，G-1.5）。

职责：
- 从环境变量（.env）读取服务运行所需的全部配置项，集中暴露为单例 settings；
- 启动期配置校验（Settings.validate_boot）：坏配置在 boot 期报清晰错误退出。

实现要点：
- 加载顺序保持既有语义：先 load_dotenv 仓库根 .env、再本模块 .env
  （load_dotenv 默认不覆盖已存在变量，故真实环境变量 > 根 .env > 包 .env），
  BaseSettings 只读 os.environ，不重复解析 env_file；
- 全部 82 个键名与语义不变：字段名小写与环境变量大小写不敏感对应
  （agent_host <-> AGENT_HOST）；唯一例外 jwt_revocation_prefer_redis 用
  validation_alias 映射 APP_JWT_REVOKE_PREFER_REDIS（沿用 Java 侧约定）；
- 默认值用 default_factory 的（路径/派生 URL）在 factory 内读 env 仍属本
  文件（INV-7：环境变量只准在 config.py 读取）；
- 实例可变（非 frozen）：测试 monkeypatch.setattr(settings, ...) 兼容；
- validate_boot 由 main.py lifespan 调用，坏配置 RuntimeError -> 进程退出
  码非 0；不放在 import 期，保证测试与脚本 import 不受真实密钥约束。

依赖：
- python-dotenv、pydantic-settings；无内部依赖。
"""

import ipaddress
import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 先加载仓库根目录共享 .env，再加载本模块 .env（同名变量后者优先）
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})


def parse_trusted_proxy(item: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """把 `TRUSTED_PROXIES` 的一项解析成网段：裸地址按单主机（/32 或 /128）。

    同一个解析器同时供启动期校验（validate_boot）与请求期归因（app.common.client_ip）
    使用——两边各写一份的话，"配置里写错的代理"会在一边报错、另一边静默不信任。
    """
    text = item.strip()
    if "/" not in text:
        text = f"{text}/32" if ":" not in text else f"{text}/128"
    return ipaddress.ip_network(text)


def _proxy_ok(item: str) -> bool:
    try:
        parse_trusted_proxy(item)
    except ValueError:
        return False
    return True


logger = logging.getLogger(__name__)


def _get(name: str, default: str) -> str:
    """仅供本模块 default_factory 派生默认值使用（INV-7 边界内的环境读取）。"""
    return os.getenv(name, default)


def _default_font_path() -> str:
    """印刷字体（simhei）已随「Java 退役」git mv 进本仓，全仓唯一一份。"""
    return str(BASE_DIR / "app" / "resources" / "fonts" / "simhei.ttf")


def _default_redis_url() -> str:
    """显式 REDIS_URL 优先，否则由 REDIS_HOST/REDIS_PORT/REDIS_PASSWORD 派生（Java 侧同口径）。

    口令走 URL 而不是 redis-py 参数：`redis_client` 只认 `from_url(...)` 一条路，
    两处各配一份迟早会漂。空口令时派生结果与历史完全一致（不多一个 `@`）。
    """
    host = _get("REDIS_HOST", "localhost")
    port = _get("REDIS_PORT", "6380")
    password = _get("REDIS_PASSWORD", "")
    auth = f":{quote_plus(password)}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # ---- 服务面 ----
    agent_host: str = "127.0.0.1"
    agent_reload: bool = False
    agent_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    agent_internal_token: str = ""
    agent_deadline_seconds: float = 90
    trusted_proxies: str = "127.0.0.1,0:0:0:0:0:0:0:1,::1"

    # ---- LLM ----
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"
    # 内容生成（行程/介绍/研究/对话决策）统一走低延迟模型；可留空以复用主模型。
    # qwen-turbo 省钱但对篇幅类软约束遵循差，默认 qwen-plus。
    llm_fast_model: str = "qwen-plus"
    llm_timeout: float = 240
    # httpx 连接池：限制对 LLM 网关的并发 TCP 连接，避免无界握手
    llm_pool_max_connections: int = 20
    llm_pool_max_keepalive: int = 10
    llm_connect_timeout: float = 5
    llm_generation_web_search: bool = False

    # ---- 实时信息与联网搜索 ----
    # 实时酒店价格会额外触发联网搜索/模型调用，默认开启以核实价格；
    # 需要更快出首版行程可显式设置 LIVE_PRICE_SEARCH=false，并限制查询数量。
    live_price_search: bool = True
    max_live_queries: int = 3
    # 餐饮实时价（百炼联网）：与酒店实时价独立开关，同样受 max_live_queries 约束
    live_food_price_search: bool = True
    max_live_food_queries: int = 4
    # 研究/备选池证据不足时用联网搜索补候选（百炼 enable_search）。
    # 量上限只有一个真源：run_limits 的 max_retrievals（原 max_web_search_queries
    # 声明后无人读取，2026-09-18 R2-5 删除；再加回"第二个旋钮"之前先想清楚谁读它）。
    web_search_enabled: bool = True

    # ---- 预算与生成后处理 ----
    # 生成后按估算总价是否触发超支修复（reflect 反馈重排）
    budget_hard_constraint: bool = True
    # 超过预算多少比例才触发修复（避免贴近预算反复重试）
    budget_overage_ratio: float = 0.08
    # 餐饮单价相对城市人均餐价的钳制倍数（硬顶/软顶）
    meal_price_hard_cap_ratio: float = 8
    meal_price_soft_cap_ratio: float = 4

    # ---- 路线 ----
    # 路线矩阵校验：用**本地坐标估算**（haversine × 道路系数）产出路线矩阵，
    # 供排程校验与打分使用。默认关闭以保持既有生成结果不变；开启不产生任何
    # 外部调用（高德/Google 路线源已于 2026-09-15 随「去高德」移除）。
    route_service_enabled: bool = False
    route_mode: str = "walking"
    route_cache_ttl: float = 900
    route_peak_factor: float = 1.25
    route_max_calls: int = 64

    # ---- Agent 运行预算 ----
    # 每次 Agent 请求允许的工具调用总数；单工具上限由 Tool Registry 控制。
    tool_max_calls: int = 32
    # 研究三域（plan/evaluate×2 轮）+ 联网补池 + 整段生成 + 修复重试：
    # 旧默认 8 次会在研究阶段就耗尽，导致「开放研究重试耗尽」草案。
    max_llm_calls: int = 32
    max_token_budget: int = 80000
    # 按用户的 LLM 花费闸门（R1-9）：上面两份预算是"按次"的，单用户循环调用
    # 拿到的就是 N 份按次预算 → 无上限。这两项才是按 principal 的顶。
    user_llm_runs_per_minute: int = 6
    user_daily_llm_runs: int = 100
    # 单次 run 内检索/证据类调用上限（研究补查、联网搜索、外部点位 API）
    max_retrievals: int = 48
    max_replans: int = 3
    no_progress_limit: int = 2

    # ---- 轨迹与用量 ----
    trace_storage_enabled: bool = True
    trace_storage_path: str = Field(default_factory=lambda: str(BASE_DIR / "data" / "agent_traces.jsonl"))
    usage_db_path: str = Field(default_factory=lambda: str(BASE_DIR / "data" / "llm_usage.db"))

    # ---- 导出与上传 ----
    # PDF 导出（M6）。字体全仓只有一份 9.7MB 的 simhei.ttf：今天在 Java 模块的 resources 下，
    # Java 退役后搬到 app/resources/fonts/——下面的解析顺序让**搬迁不需要改代码**。
    # 部署可用 EXPORT_DIR / EXPORT_FONT_FILE 覆盖。
    export_dir: str = Field(default_factory=lambda: str(BASE_DIR / "data" / "export"))
    export_font_file: str = Field(default_factory=_default_font_path)
    # 封面/上传图落盘根目录（SPEC v2.3 §6.1）：provider 快照与用户上传都写这里，
    # DB 只存 /api/uploads/... 应用路径；静态访问路由见 app/api/business/uploads.py。
    uploads_dir: str = Field(default_factory=lambda: str(BASE_DIR / "data" / "uploads"))
    # 封面上传大小上限（SPEC v2.3 §6.3 / S0-3）：FastAPI 不限制 multipart 体积，
    # 入口在 cover_service.read_upload_capped 里流式截断，超限 413。
    cover_upload_max_bytes: int = 5 * 1024 * 1024

    # ---- 分享与调度 ----
    # 分享匿名访问限流（SPEC v2.3 §6.6 / E14）：按 IP 滑动窗口，每分钟上限
    share_rate_limit_per_minute: int = 60
    # 匿名图片端点（/api/image-proxy、/api/poi-photo）按 IP 每分钟上限（R1-4）：
    # 这两个端点在 PUBLIC_PATHS 里，未命中时各自要打 1~6 次外网，没有闸门就是
    # 一个脚本能耗尽出网配额与 worker。归因地址口径见 app/common/client_ip.py。
    public_rate_limit_per_minute: int = 60
    schedule_optimizer_enabled: bool = True
    # MCP 出口（G-3.6）：默认关闭，管理员在后台开启后 /mcp 才可用
    mcp_enabled: bool = False
    # MCP 行程写入（C3.3）：默认关闭——查行程/重排一天/记账写工具单独显式打开
    mcp_write_enabled: bool = False
    # 模板广场（C2.4）：默认关闭，自托管私有部署不默认开放社区面
    template_community_enabled: bool = False
    # 条目对/错反馈（C3.5）：默认关闭——增强能力由管理员显式打开（与 mcp_write 同模式）
    item_feedback_enabled: bool = False

    # ---- 图片源 ----
    unsplash_access_key: str = ""
    # 图片多源解析的最后一级兜底图库（Java 侧 app.pexels.access-key 的等价项）。
    # Pexels 对中文查询几乎无命中，poi_photo 会先尝试把名称解析成英文再检索。
    pexels_access_key: str = ""
    poi_image_wiki: bool = True

    # ---- 外部地点层（POI 权威库退役后的坐标/分类/图片来源） ----
    # OpenTripMap（OSM+Wikidata 加工的旅游切片）：景点半径检索与详情；免费 key
    # 在 https://opentripmap.io 注册。仅 en/ru 语言，返回名称为英文，中文名由
    # LLM 对齐。key 为空时整层禁用，生成链路降级为纯 LLM + 联网搜索。
    otm_api_key: str = ""
    # 景点半径检索范围与上限（城市尺度）
    otm_radius_m: int = 12000
    otm_limit: int = 40
    # OTM/Nominatim 单次调用超时（秒）；数据源失败一律静默降级，不阻断生成
    places_timeout_seconds: float = 8.0
    # Nominatim（OSM 官方地理编码）兜底：OTM 无法按"点名"解析，缺坐标的
    # LLM 自选点位经它补真实坐标；公共实例政策 1 rps。
    nominatim_enabled: bool = True
    # Open-Meteo 免 key 天气（C3.1）：研究证据与行程页逐日预报；失败静默，
    # 关掉即整体停用（与 Nominatim 同类的免费数据源，走 env 开关不入 addon）。
    weather_enabled: bool = True

    # ---- 存在性判定（PLAN-A1 G2；判"这个名字指的地点真的存在吗"） ----
    # 解析顺序（逗号分隔）：otm=OpenTripMap 池名匹配（只能正向证实）、
    # nominatim=点名地理编码、amap/google_places=收费源留白（无 key 不发请求）。
    existence_provider_order: str = "otm,nominatim"
    # 单次生成 run 的存在性解析上限；耗尽后一律 UNKNOWN（绝不当成"不存在"）。
    # 实测一天行程约 30 个唯一点位名，24 覆盖主行程并给备选池留余量。
    existence_resolve_limit: int = 24
    # 位置一致性硬闸：解析命中的点离目的地中心超过这个半径，就判"与本次行程
    # 矛盾"（out_of_area）。实测挡住的是「西安方所书店→安徽」这类跨城误配。
    existence_area_radius_m: int = 80000
    # 同一实体判定的字符重叠率下限（与固定最少共享字符数 4 配套）。
    # 0.55 是 2026-09-18 量测口径：降到 0.5 会放进「明婷小馆→报名大厅」。
    entity_name_similarity_min: float = 0.55
    # 备选池批量后验证的独立预算（后台富化，与主行程生成互不抢占额度）。
    # 一次产出的 suggestions 是 24-40 条，实测 40 条按 Nominatim 1 rps 约 45s。
    suggestion_resolve_limit: int = 40
    # 收费源留白（当前无 key）：配置后 existence_provider_order 里加上它们即可，
    # 两者的空结果带 authoritative_negative=True，"证伪即删"随之自动生效。
    amap_web_key: str = ""
    google_places_api_key: str = ""

    # ---- MySQL ----
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "travel_assistant"
    # MySQL 连接池上限（Agent 侧只读知识库；管线写库共用同一池）
    db_pool_max: int = 10

    # ---- Redis ----
    # Redis Pub/Sub（AD2 SSE）：进度事件发布通道；事件是尽力而为通知，
    # 连不上只降级。地址与 Java 侧同口径：显式 REDIS_URL 优先，否则由
    # REDIS_HOST/REDIS_PORT 派生。默认 6380 对齐 start-all.ps1 起的本机
    # Redis（compose 内由 environment 传 6379）。
    redis_url: str = Field(default_factory=_default_redis_url)
    # 只在未显式给 REDIS_URL 时参与派生（compose 里 Redis 发布到宿主机端口，
    # 无口令等于把 JWT 吊销黑名单与登录锁桶交给整个局域网，见 R1-7）。
    redis_password: str = ""

    # ---- 双跑期鉴权互认（PLAN v3.0 §1.1） ----
    # 与 Java 服务共用同一 JWT_SECRET 与同一 Cookie，用户切域不需重登、
    # 灰度可回滚。变量名沿用 Java 侧 application.yml 既有约定。
    # 注意：DB 凭据两侧不同源——Java 读 MYSQL_*，本服务读 DB_*（见 compose environment）。
    # token 的 exp 写在 claims 里，两侧过期时钟不同也不会互判失效；差异只体现在
    # Cookie 的 Max-Age 上（无害），故本项可与 Java 的 expire-hours 独立设置。
    jwt_secret: str = ""
    jwt_expire_hours: int = 24
    # 默认安全：会话票是唯一的凭据载体，明文链路上等于可被同网段摘取。
    # 本地明文 http 与 compose（nginx 只 listen 80）在 .env / compose env_file 里显式设
    # false，并让 validate_boot 为非回环绑定的情况把关（见下）。
    auth_cookie_secure: bool = True
    jwt_revocation_prefer_redis: bool = Field(default=True, validation_alias="APP_JWT_REVOKE_PREFER_REDIS")

    @model_validator(mode="after")
    def _static_validation(self) -> "Settings":
        """配置静态自洽（数值/范围）：任何实例化都生效（含测试 import 期）。

        只做「配置自身自洽」的检查，且所有默认值必须能通过——依赖运行语境的
        安全检查（真实密钥、绑定地址）**不在这里**，它们在 validate_boot()，
        由 main.py lifespan 调用，坏配置 RuntimeError -> 进程退出码非 0；
        放在 import 期会炸掉测试与脚本。
        """
        bad = [
            f"{key}={getattr(self, key)} {requirement}"
            for key, requirement, _low, _high in _NUMERIC_RULES
            if not _numeric_ok(key, getattr(self, key))
        ]
        if bad:
            raise ValueError("配置项取值非法：" + "；".join(bad))
        return self

    def validate_boot(self) -> None:
        """main.py lifespan 的启动校验入口：坏配置 boot 期报清晰错误退出。

        原有 fail-fast 两条语义与文案保持不变，从 main.py 就地收拢到配置层；
        不放在 import 期，保证测试与脚本 import 不受真实密钥约束。
        """
        # 安全 fail-fast：generate/adjust 等端点每次调用消耗真实 LLM token。
        # 绑定非回环地址却不配置内部令牌，等于匿名烧钱接口；启动即拒绝，
        # 避免"默认空 token 静默放行"在部署改 host 后裸奔。
        if self.agent_host not in _LOCAL_HOSTS and not self.agent_internal_token:
            raise RuntimeError(
                "AGENT_HOST 绑定非回环地址但未配置 AGENT_INTERNAL_TOKEN，"
                "生成类端点将匿名暴露并消耗 LLM 配额；请设置令牌或改回 127.0.0.1"
            )
        # 会话签名密钥：等价 Java `JwtProperties` 的 @NotBlank @Size(min=32)。
        # 默认空串必须拦下——那等于任何人都能伪造登录票。
        if len(self.jwt_secret) < 32:
            raise RuntimeError(
                "JWT_SECRET 未配置或短于 32 字符：本服务负责签发会话票，弱密钥可被伪造登录；"
                "请在 .env 里配置与（双跑期）Java 侧一致的密钥"
            )
        # R1-5：TRUSTED_PROXIES 里任何一项写错，都会让 app.common.client_ip 静默不信任
        # 那台代理——症状是"所有访客共用代理 IP 一个限速桶"，从症状倒不回配置，所以启动即拒。
        unparsable = [item.strip() for item in self.trusted_proxies.split(",") if item.strip() and not _proxy_ok(item)]
        if unparsable:
            raise RuntimeError(f"TRUSTED_PROXIES 含无法解析的条目：{unparsable}（支持 IP 或 CIDR，如 172.16.0.0/12）")
        # 明文链路上的会话票会被同网段摘取。compose 的 nginx 目前只 listen 80，
        # 所以这里不 fail-fast，只把风险写在启动日志里（改成 TLS 后请删掉显式 false）。
        if not self.auth_cookie_secure and self.agent_host not in _LOCAL_HOSTS:
            logger.warning(
                "AUTH_COOKIE_SECURE=false 且绑定 %s：会话票将以明文 Cookie 传输，"
                "仅可接受于本地/内网可信链路；对外提供请上 TLS 并置 true",
                self.agent_host,
            )


# 数值范围规则：(键, 人话要求, 下界(开区间), 上界(闭区间))；默认值必须全部通过。
# max_replans 下界 -1 表示允许 0（显式关闭重规划）。
_NUMERIC_RULES: tuple[tuple[str, str, float, float], ...] = (
    ("llm_timeout", "必须 > 0", 0, float("inf")),
    ("llm_connect_timeout", "必须 > 0", 0, float("inf")),
    ("agent_deadline_seconds", "必须 > 0", 0, float("inf")),
    ("db_port", "必须在 1-65535 之间", 0, 65535),
    ("db_pool_max", "必须 >= 1", 0, float("inf")),
    ("tool_max_calls", "必须 >= 1", 0, float("inf")),
    ("max_llm_calls", "必须 >= 1", 0, float("inf")),
    ("user_llm_runs_per_minute", "必须 >= 1", 0, float("inf")),
    ("user_daily_llm_runs", "必须 >= 1", 0, float("inf")),
    ("max_retrievals", "必须 >= 1", 0, float("inf")),
    ("max_replans", "必须 >= 0", -1, float("inf")),
    ("jwt_expire_hours", "必须 >= 1", 0, float("inf")),
    ("cover_upload_max_bytes", "必须 > 0", 0, float("inf")),
    ("otm_radius_m", "必须 > 0", 0, float("inf")),
    ("otm_limit", "必须 >= 1", 0, float("inf")),
    ("places_timeout_seconds", "必须 > 0", 0, float("inf")),
    ("existence_resolve_limit", "必须 >= 1", 0, float("inf")),
    ("existence_area_radius_m", "必须 > 0", 0, float("inf")),
    ("entity_name_similarity_min", "必须在 0-1 之间", 0, 1),
    ("suggestion_resolve_limit", "必须 >= 1", 0, float("inf")),
    ("share_rate_limit_per_minute", "必须 >= 1", 0, float("inf")),
    ("public_rate_limit_per_minute", "必须 >= 1", 0, float("inf")),
)
_RANGES = {key: (low, high) for key, _req, low, high in _NUMERIC_RULES}


def _numeric_ok(key: str, value: float) -> bool:
    low, high = _RANGES[key]
    return low < value <= high


settings = Settings()
