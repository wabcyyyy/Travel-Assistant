from pydantic import ValidationError

from app.agent import day_stream
from app.schemas.trip import BackupRule, GenerateDayRequest, GenerateRequest, PhotoSpot


def test_generate_request_rejects_more_than_one_week():
    try:
        GenerateRequest(city="苏州", days=8)
    except ValidationError as exc:
        assert "less than or equal to 7" in str(exc)
    else:
        raise AssertionError("行程生成请求不应允许超过 7 天")


def test_open_city_can_generate_after_workflow_enters_fallback(monkeypatch):
    """没有本地候选的城市也不能因某一天重试而中止整段行程。"""
    monkeypatch.setattr(day_stream.settings, "llm_api_key", "configured")
    monkeypatch.setattr(
        day_stream,
        "_llm_open_day",
        lambda req, used: {
            "note": "苏州第2天行程",
            "theme": "园林慢游",
            "mini_route": {"mode": "walking"},
            "backup_plan": [{"name": "狮子林"}],
            "photo_spots": [{"name": "拙政园入口"}],
            "practical_notes": ["提前预约"],
            "items": [
                {
                    "item_type": "attraction",
                    "poi_name": "拙政园",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "duration_min": 120,
                    "cost": 0,
                }
            ],
        },
    )

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
    assert plan.theme == "园林慢游"
    assert plan.mini_route == {"mode": "walking"}
    # M3-① 叙事层：backup_plan/photo_spots 升级为结构化子模型，
    # 旧 dict（{"name": ...}）经 BackupRule 前向兼容归一（缺 key 补空串）。
    assert plan.backup_plan == [BackupRule.model_validate({"name": "狮子林"})]
    assert plan.photo_spots == [PhotoSpot(name="拙政园入口")]
    assert plan.practical_notes == ["提前预约"]
    assert plan.items[0].source == "llm.open_day"
    assert plan.items[0].review_requirement == "before_departure"
    assert "identity" in plan.items[0].fact_evidence


def test_duration_min_follows_scheduled_window(monkeypatch):
    """库内典型时长（如 480）不得覆盖已排时间窗（09:00-11:30 → 150）。"""
    monkeypatch.setattr(day_stream.settings, "llm_api_key", "configured")
    monkeypatch.setattr(
        day_stream,
        "_llm_open_day",
        lambda req, used: {
            "note": "杭州第1天",
            "items": [
                {
                    "item_type": "attraction",
                    "poi_name": "西湖",
                    "start_time": "09:00",
                    "end_time": "11:30",
                    "duration_min": 480,
                    "cost": 0,
                }
            ],
        },
    )
    plan, _ = day_stream._generate_day_once(
        GenerateDayRequest(
            city="杭州",
            day_no=1,
            days=2,
            used_names=[],
            context={"candidates": [], "foods": [], "hotels": []},
        ),
        force_fallback=True,
    )
    assert plan.items[0].duration_min == 150
    assert plan.items[0].start_time == "09:00"
    assert plan.items[0].end_time == "11:30"
