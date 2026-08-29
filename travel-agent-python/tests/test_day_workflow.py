from app.agent import day_workflow
from app.schemas.trip import DailyPlan, GenerateDayRequest, TripItem


def _plan(start: str = "09:00", end: str = "11:00") -> DailyPlan:
    return DailyPlan(
        day_no=1,
        items=[
            TripItem(
                item_type="attraction",
                poi_name="测试景点",
                start_time=start,
                end_time=end,
                duration_min=120,
            )
        ],
    )


def test_day_graph_retries_after_reflection(monkeypatch):
    calls = []

    def fake_once(req, *, force_fallback=False):
        calls.append((req.feedback, force_fallback))
        if len(calls) == 1:
            return DailyPlan(
                day_no=1,
                items=[
                    TripItem(item_type="attraction", poi_name="A", start_time="09:00", end_time="12:00"),
                    TripItem(item_type="food", poi_name="B", start_time="11:00", end_time="12:30"),
                ],
            ), "llm"
        return _plan(), "llm"

    monkeypatch.setattr(day_workflow, "_generate_day_once", fake_once)
    result = day_workflow.run_day_agent(GenerateDayRequest(city="杭州"))

    assert result.items[0].poi_name == "测试景点"
    assert len(calls) == 2
    assert "时间冲突" in calls[1][0]
    assert calls[1][1] is False


def test_day_graph_uses_deterministic_fallback_after_second_failure(monkeypatch):
    calls = []

    def fake_once(req, *, force_fallback=False):
        calls.append(force_fallback)
        bad = DailyPlan(
            day_no=1,
            items=[
                TripItem(item_type="attraction", poi_name="A", start_time="09:00", end_time="12:00"),
                TripItem(item_type="food", poi_name="B", start_time="11:00", end_time="12:30"),
            ],
        )
        return bad, "fallback" if force_fallback else "llm"

    monkeypatch.setattr(day_workflow, "_generate_day_once", fake_once)
    result = day_workflow.run_day_agent(GenerateDayRequest(city="杭州"))

    assert result.day_no == 1
    assert calls == [False, False, True]


def test_day_graph_retries_when_route_gap_is_too_short(monkeypatch):
    calls = []

    def fake_once(req, *, force_fallback=False):
        calls.append(req.feedback)
        if len(calls) == 1:
            return DailyPlan(day_no=1, items=[
                TripItem(item_type="attraction", poi_name="远点A", start_time="09:00", end_time="10:00",
                         latitude=30.0, longitude=120.0),
                TripItem(item_type="attraction", poi_name="远点B", start_time="10:30", end_time="12:00",
                         latitude=30.2, longitude=120.0),
            ]), "llm"
        return _plan(), "llm"

    monkeypatch.setattr(day_workflow, "_generate_day_once", fake_once)
    result = day_workflow.run_day_agent(GenerateDayRequest(city="杭州"))

    assert result.items[0].poi_name == "测试景点"
    assert len(calls) == 2
    assert "路线时间不足" in calls[1]
