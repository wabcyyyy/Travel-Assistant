from app.agent import day_stream
from pydantic import ValidationError

from app.schemas.trip import GenerateDayRequest, GenerateRequest


def test_generate_request_rejects_more_than_one_week():
    try:
        GenerateRequest(city="苏州", days=8)
    except ValidationError as exc:
        assert "less than or equal to 7" in str(exc)
    else:
        raise AssertionError("行程生成请求不应允许超过 7 天")


def test_open_city_can_generate_after_workflow_enters_fallback(monkeypatch):
    """没有本地候选的城市也不能因某一天重试而中止整段行程。"""
    monkeypatch.setattr(day_stream, "_llm_open_day", lambda req, used: {
        "note": "苏州第2天行程",
        "items": [{
            "item_type": "attraction",
            "poi_name": "拙政园",
            "start_time": "09:00",
            "end_time": "11:00",
            "duration_min": 120,
            "cost": 0,
        }],
    })

    plan, source = day_stream._generate_day_once(
        GenerateDayRequest(
            city="苏州",
            day_no=2,
            days=4,
            used_names=["留园"],
            context={"candidates": [], "foods": [], "hotels": []},
        ),
        force_fallback=True,
    )

    assert source == "open"
    assert [item.poi_name for item in plan.items] == ["拙政园"]
