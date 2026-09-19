from pydantic import ValidationError

from app.agent import day_stream
from app.agent.grounding_evidence import issue_evidence
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

    def _no_ground(item, city):
        return None

    monkeypatch.setattr(day_stream, "local_ground", _no_ground)
    monkeypatch.setattr(
        day_stream,
        "llm_open_day",
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

    plan, source = day_stream.generate_day_once(
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


def test_resolved_item_is_endorsed_with_the_provider_that_ran(monkeypatch):
    """点名解析真跑过时，来源就是那个 provider，并且拿到 observed 背书。

    与 test_grounding_labels 的口径同源：项上的 source 只可能由服务端解析器写
    （模型自报的在 LLM 输出边界已剥），所以它可以作为背书的凭据。
    """
    monkeypatch.setattr(day_stream.settings, "llm_api_key", "configured")

    def _ground(item, city):
        item["latitude"] = 31.32
        item["longitude"] = 120.62
        item["address"] = "苏州市姑苏区东北街178号"
        item["source"] = "nominatim"
        # 真实 local_ground 解析成功时同步签发证据票；背书认票不认字符串
        issue_evidence({**item, "name": item["poi_name"], "city": city})

    monkeypatch.setattr(day_stream, "local_ground", _ground)
    monkeypatch.setattr(
        day_stream,
        "llm_open_day",
        lambda req, used: {
            "note": "苏州第2天行程",
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

    plan, _source = day_stream.generate_day_once(
        GenerateDayRequest(city="苏州", day_no=2, days=4, context={"candidates": [], "foods": [], "hotels": []}),
        force_fallback=True,
    )

    item = plan.items[0]
    assert item.source == "nominatim"
    assert item.verification_status == "partially_verified"
    assert item.value_kind == "observed"
    assert item.fact_evidence["identity"].provider == "nominatim"


def test_duration_min_follows_scheduled_window(monkeypatch):
    """库内典型时长（如 480）不得覆盖已排时间窗（09:00-11:30 → 150）。"""
    monkeypatch.setattr(day_stream.settings, "llm_api_key", "configured")
    monkeypatch.setattr(
        day_stream,
        "llm_open_day",
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
    plan, _ = day_stream.generate_day_once(
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
