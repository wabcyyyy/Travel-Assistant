"""行程相关业务模型（请求/响应 Schema）。

职责：
- 定义生成、调整、澄清、编辑、对话、酒店等接口的入参与返回结构。

实现要点：
- 全部继承 WireModel，自动支持 camelCase 序列化；
- GenerateRequest/GenerateResponse 描述整段行程生成；
  ChatTurnRequest/ChatTurnResponse 承载对话式草稿编辑；
  EditOp 描述结构化编辑操作（delete/add/update_time/move_day/upgrade_hotel）；
- HotelOption/HotelRoomOption 封装酒店候选与预算判定结果。

依赖：
- app.schemas.common.WireModel。
"""

from typing import Literal

from pydantic import Field

from app.schemas.common import WireModel

MAX_TRIP_DAYS = 7


class FactEvidence(WireModel):
    """单个事实字段的来源与时效信息。

    状态按字段记录，避免把坐标已核实误解成价格、营业时间也已核实。
    """

    source_ref: str | None = None
    source_url: str | None = None
    provider: str | None = None
    retrieved_at: str | None = None
    expires_at: str | None = None
    verification_status: Literal["verified", "partially_verified", "unverified"] = "unverified"
    value_kind: Literal["observed", "estimated", "generated"] = "generated"
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    review_requirement: Literal["none", "before_departure"] = "before_departure"


class SourceRecord(WireModel):
    """可追溯来源记录；storage_source 不等同于原始发布者。"""

    source_id: str
    storage_source: str | None = None
    provider: str | None = None
    publisher: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    published_at: str | None = None
    expires_at: str | None = None


class QualityIssue(WireModel):
    code: str
    path: str | None = None
    message: str


class QualityReport(WireModel):
    quality_status: Literal["DRAFT", "READY_WITH_WARNINGS", "READY", "BLOCKED", "STALE"] = "DRAFT"
    quality_rule_version: str = "travel-quality-1.0"
    validated_at: str | None = None
    blocking_issues: list[QualityIssue] = Field(default_factory=list)
    warnings: list[QualityIssue] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class GenerateRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(default=1, ge=1, le=MAX_TRIP_DAYS)
    persons: int = Field(default=1, ge=1, le=20)
    budget: float | None = None
    start_date: str | None = None
    preferences: list[str] = Field(default_factory=list)
    hotel_tier: str | None = Field(default=None)  # 经济型/舒适型/高档型/豪华型/奢华型
    requirements: str | None = Field(default=None, max_length=2000)  # 客户额外要求（自然语言）
    # 用户最初输入的省/区域提示（如"云南"→city 已解析为"丽江"）。此前 Java
    # 会发送但 pydantic 默认 ignore extra 直接丢弃；保留以便开放模式提示模型
    # 目的地所属区域，并为管家讲解提供上下文。
    region_hint: str | None = Field(default=None, max_length=64)


class TripItem(WireModel):
    item_type: str = Field(default="attraction", pattern="^(attraction|food|hotel|transport)$")
    poi_name: str
    poi_id: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_min: int | None = None
    open_time: str | None = None
    cost: float | None = None
    tag: str | None = None
    remark: str | None = None
    image: str | None = None  # POI 图片 URL（高德检索，可选）
    source: str | None = None
    source_updated_at: str | None = None
    verification_status: Literal["verified", "partially_verified", "unverified"] = "unverified"
    value_kind: Literal["observed", "estimated", "generated"] = "generated"
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    review_requirement: Literal["none", "before_departure"] = "before_departure"
    fact_evidence: dict[str, FactEvidence] = Field(default_factory=dict)

class Suggestion(WireModel):
    """备选池条目：生成时未排入行程、可在「发现更多」一键加入的候选点位。

    候选池保底链路中条目必须来自候选池（代码侧兜底校验）；开放模式
    （open_research）下允许池外模型建议，坐标留空由前端经高德补齐。
    """

    poi_id: str | None = None
    name: str
    category: Literal["attraction", "activity", "food", "hotel", "souvenir"] = "attraction"
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    intro: str | None = None
    need_reservation: bool = False
    estimated_cost: float | None = None
    used: bool = False


class DailyPlan(WireModel):
    day_no: int
    note: str | None = None
    items: list[TripItem] = Field(default_factory=list)
    theme: str | None = None
    mini_route: dict = Field(default_factory=dict)
    backup_plan: list[dict] = Field(default_factory=list)
    photo_spots: list[dict] = Field(default_factory=list)
    practical_notes: list[str] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)


class GenerateResponse(WireModel):
    schema_version: str = "1.0"
    city: str
    days: int
    title: str
    daily_plans: list[DailyPlan]
    budget_estimate: dict[str, float] = Field(default_factory=dict)
    suggestions: list[Suggestion] = Field(default_factory=list)
    validation_log: list[str] = Field(default_factory=list)
    price_note: str | None = None
    schedule_report: dict = Field(default_factory=dict)
    critic_report: dict = Field(default_factory=dict)
    destination_status: Literal["knowledge_backed", "researched", "draft_only"] = "knowledge_backed"
    sources: list[SourceRecord] = Field(default_factory=list)
    quality_report: QualityReport = Field(default_factory=QualityReport)
    status: Literal["success", "degraded", "failed"] = "success"
    status_reason: str | None = None


class AdjustRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    item_type: str = Field(default="attraction", pattern="^(attraction|food|hotel|transport)$")
    poi_name: str = Field(min_length=1, max_length=128)
    preferences: list[str] = Field(default_factory=list)


class PoiOption(WireModel):
    poi_id: int | None = None
    name: str
    category: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    ticket_price: float | None = None
    duration_min: int | None = None
    open_time: str | None = None
    tags: str | None = None
    rating: float | None = None
    description: str | None = None


class AdjustResponse(WireModel):
    city: str
    current: str
    recommendations: list[PoiOption] = Field(default_factory=list)


class ClarifyRequest(WireModel):
    message: str = Field(min_length=1)
    slots: dict = Field(default_factory=dict)


class ClarifyResponse(WireModel):
    slots: dict = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    question: str | None = None
    ready: bool = False


class EditOpRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(ge=1, le=MAX_TRIP_DAYS)
    plans: list[dict] = Field(default_factory=list, max_length=MAX_TRIP_DAYS)
    instruction: str = Field(min_length=1, max_length=2000)


class EditOp(WireModel):
    action: str  # delete / add / update_time / move_day / upgrade_hotel
    day_no: int | None = None
    poi_name: str | None = None
    start_time: str | None = None
    tier: str | None = None  # upgrade_hotel 用的档次


class PlanContextRequest(WireModel):
    city: str = Field(min_length=1)
    preferences: list[str] = Field(default_factory=list)


class GenerateDayRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    persons: int = 1
    budget: float | None = None
    start_date: str | None = None
    day_no: int = Field(default=1, ge=1, le=MAX_TRIP_DAYS)
    days: int | None = None  # 整个行程总天数，用于按总时长调整当日节奏；不传则按单日处理
    # used_names/context 会整体进 prompt 并被 ReferencePool 展开；无上限时
    # 超大 body 直接吃内存与 token。context 由服务端 plan-context 生成，
    # 条目数受参考资料池上限约束，这里给宽松但有限的边界。
    used_names: list[str] = Field(default_factory=list, max_length=200)
    hotel_tier: str | None = None
    chosen_hotel: str | None = None
    needs_hotel: bool = True
    requirements: str | None = Field(default=None, max_length=2000)  # 客户额外要求（自然语言）
    region_hint: str | None = Field(default=None, max_length=64)  # 用户最初输入的省/区域
    feedback: str = Field(default="", max_length=4000)
    context: dict = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=128)
    action_id: str | None = Field(default=None, max_length=128)


class LocalReplanRequest(WireModel):
    """只对受影响日期做重规划的显式输入契约。"""
    city: str = Field(min_length=1, max_length=64)
    affected_day_nos: list[int] = Field(min_length=1, max_length=MAX_TRIP_DAYS)
    locked_names: list[str] = Field(default_factory=list, max_length=100)
    candidate_names: list[str] = Field(default_factory=list, max_length=100)
    failure_reasons: list[str] = Field(default_factory=list, max_length=20)
    plans: list[dict] = Field(default_factory=list, max_length=MAX_TRIP_DAYS)
    budget: float | None = None
    request_id: str | None = Field(default=None, max_length=128)
    action_id: str | None = Field(default=None, max_length=128)


class ChatTurnRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(ge=1, le=MAX_TRIP_DAYS)
    persons: int = Field(default=1, ge=1, le=20)
    budget: float | None = None
    current_total: float | None = None
    current_hotel_total: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    preferences: list[str] = Field(default_factory=list, max_length=20)
    hotel_tier: str | None = None
    plans: list[dict] = Field(default_factory=list, max_length=MAX_TRIP_DAYS)
    history: list[dict] = Field(default_factory=list, max_length=20)
    message: str = Field(min_length=1, max_length=2000)


class HotelRoomOption(WireModel):
    id: str
    room_name: str
    base_price: float
    nightly_price: float
    nights: int
    rooms: int
    total_price: float
    price_delta: float | None = None
    projected_hotel_total: float | None = None
    within_budget: bool
    budget_overage: float = 0
    capacity: int = 2
    bed_type: str | None = None
    breakfast: str | None = None
    description: str | None = None
    is_default: bool = False
    nightly_breakdown: list[dict] = Field(default_factory=list)


class HotelOption(WireModel):
    id: str
    hotel_name: str
    tier: str
    address: str | None = None
    rating: float | None = None
    base_price: float
    season_factor: float
    season_label: str
    nightly_price: float
    nights: int
    rooms: int
    total_price: float
    price_delta: float | None = None
    within_budget: bool
    budget_capacity: float | None = None
    budget_overage: float = 0
    is_current: bool = False
    reason: str
    requested_nights: int = 1
    requested_day_nos: list[int] = Field(default_factory=list)
    available_day_nos: list[int] = Field(default_factory=list)
    room_types: list[HotelRoomOption] = Field(default_factory=list)


class ChatTurnResponse(WireModel):
    reply: str
    plans: list[dict] = Field(default_factory=list)
    changed: bool = False
    hotel_options: list[HotelOption] = Field(default_factory=list)
    requires_confirmation: bool = False
    plan_document: dict | None = None
    operations: list[dict] = Field(default_factory=list)
    pending_action: dict | None = None
