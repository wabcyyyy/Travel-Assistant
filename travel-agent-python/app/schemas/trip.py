from pydantic import Field

from app.schemas.common import WireModel


class GenerateRequest(WireModel):
    city: str = Field(min_length=1, max_length=64)
    days: int = Field(default=1, ge=1, le=14)
    persons: int = Field(default=1, ge=1, le=20)
    budget: float | None = None
    start_date: str | None = None
    preferences: list[str] = Field(default_factory=list)


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