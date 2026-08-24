from pydantic import Field

from app.schemas.common import WireModel


class GenerateRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(default=1, ge=1, le=14)
    persons: int = Field(default=1, ge=1, le=20)
    budget: float | None = None
    start_date: str | None = None
    preferences: list[str] = Field(default_factory=list)
    hotel_tier: str | None = Field(default=None)  # 经济型/舒适型/高档型/豪华型/奢华型


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
    cost: float | None = None
    tag: str | None = None
    remark: str | None = None


class DailyPlan(WireModel):
    day_no: int
    note: str | None = None
    items: list[TripItem] = Field(default_factory=list)


class GenerateResponse(WireModel):
    city: str
    days: int
    title: str
    daily_plans: list[DailyPlan]
    budget_estimate: dict[str, float] = Field(default_factory=dict)
    validation_log: list[str] = Field(default_factory=list)
    price_note: str | None = None


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
    days: int = Field(ge=1, le=14)
    plans: list[dict] = Field(default_factory=list, max_length=14)
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
    city: str
    persons: int = 1
    budget: float | None = None
    start_date: str | None = None
    day_no: int = 1
    used_names: list[str] = Field(default_factory=list)
    hotel_tier: str | None = None
    chosen_hotel: str | None = None
    needs_hotel: bool = True
    context: dict = Field(default_factory=dict)


class ChatTurnRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(ge=1, le=14)
    persons: int = Field(default=1, ge=1, le=20)
    budget: float | None = None
    current_total: float | None = None
    current_hotel_total: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    preferences: list[str] = Field(default_factory=list, max_length=20)
    hotel_tier: str | None = None
    plans: list[dict] = Field(default_factory=list, max_length=14)
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
