"""统一生成图冒烟：day / trip 两种 mode 均可从同一张图进入。"""

from app.agent.trip_graph import (
    MODE_DAY,
    MODE_TRIP,
    empty_day_state,
    empty_trip_state,
    run_day,
    run_trip,
    unified_agent_graph,
)
from app.schemas.trip import GenerateDayRequest, GenerateRequest


def test_unified_graph_exists():
    assert unified_agent_graph is not None


def test_day_state_mode(monkeypatch):
    from app.agent import day_workflow

    def fake_once(req, *, force_fallback=False):
        from app.schemas.trip import DailyPlan, TripItem
        return DailyPlan(day_no=1, items=[
            TripItem(item_type="attraction", poi_name="A", start_time="09:00",
                     end_time="12:00", duration_min=180, latitude=30.0, longitude=120.0),
            TripItem(item_type="food", poi_name="B", start_time="12:20",
                     end_time="13:20", duration_min=60, latitude=30.01, longitude=120.01),
            TripItem(item_type="attraction", poi_name="C", start_time="13:50",
                     end_time="16:50", duration_min=180, latitude=30.02, longitude=120.02),
        ]), "llm"

    monkeypatch.setattr(day_workflow, "_generate_day_once", fake_once)
    plan = run_day(GenerateDayRequest(city="杭州"))
    assert plan.items[0].poi_name == "A"


def test_empty_states_carry_mode():
    assert empty_day_state(GenerateDayRequest(city="杭州"))["mode"] == MODE_DAY
    assert empty_trip_state(GenerateRequest(city="杭州", days=1))["mode"] == MODE_TRIP
