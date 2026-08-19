from app.agent.reflect import build_feedback, parse_time, validate_plans
from app.rag.embeddings import embed


def test_parse_time():
    assert parse_time("09:00") == 540
    assert parse_time("23:59") == 1439
    assert parse_time("") is None
    assert parse_time(None) is None
    assert parse_time("abc") is None


def test_validate_ok():
    plans = [
        {
            "day_no": 1,
            "items": [
                {"item_type": "attraction", "poi_name": "A", "start_time": "09:00", "end_time": "11:30"},
                {"item_type": "attraction", "poi_name": "B", "start_time": "13:30", "end_time": "16:00"},
                {"item_type": "food", "poi_name": "C", "start_time": "18:00", "end_time": "19:00"},
                {"item_type": "hotel", "poi_name": "酒店", "start_time": "21:00", "end_time": "08:00"},
            ],
        }
    ]
    issues, log = validate_plans(plans)
    assert issues == []
    assert len(log) == 1


def test_validate_conflict_and_open_time():
    plans = [
        {
            "day_no": 1,
            "items": [
                {"item_type": "attraction", "poi_name": "A", "start_time": "09:00", "end_time": "12:00"},
                {"item_type": "attraction", "poi_name": "B", "start_time": "11:00", "end_time": "13:00"},
                {"item_type": "attraction", "poi_name": "C", "start_time": "19:00", "end_time": "20:00",
                 "open_time": "08:00-17:00"},
            ],
        }
    ]
    issues, _ = validate_plans(plans)
    assert any("时间冲突" in i for i in issues)
    assert any("开放时间不符" in i for i in issues)


def test_validate_saturation_hotel_excluded():
    plans = [
        {
            "day_no": 1,
            "items": [
                {"item_type": "attraction", "poi_name": "A", "start_time": "09:00", "end_time": "11:30"},
                {"item_type": "attraction", "poi_name": "B", "start_time": "13:30", "end_time": "16:00"},
                {"item_type": "attraction", "poi_name": "C", "start_time": "19:00", "end_time": "20:30"},
                {"item_type": "food", "poi_name": "D", "start_time": "18:00", "end_time": "19:00"},
                {"item_type": "hotel", "poi_name": "酒店", "start_time": "21:00", "end_time": "08:00", "duration_min": 660},
            ],
        }
    ]
    issues, _ = validate_plans(plans)
    assert issues == []


def test_embed_deterministic_and_normalized():
    v1 = embed("北京 故宫 人文")
    v2 = embed("北京 故宫 人文")
    assert v1 == v2
    assert len(v1) == 256
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_build_feedback():
    issues = ["第 1 天时间冲突：A 与 B 重叠", "第 1 天行程过满"]
    feedback = build_feedback(issues)
    assert "A 与 B" in feedback and "行程过满" in feedback