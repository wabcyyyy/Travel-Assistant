"""预算硬约束、餐饮钳制、餐次与备选池补全的回归测试。"""

from app.agent.generation_core import (
    estimate_plans_total,
    has_double_lunch,
    meal_slot_of,
)
from app.agent.generators import clamp_meal_cost, fill_suggestion_gaps
from app.agent.reflect import validate_plans


def _plan(day_no=1, items=None):
    return {"day_no": day_no, "note": f"d{day_no}", "items": items or []}


def _food(name, start, end, cost):
    return {
        "item_type": "food",
        "poi_name": name,
        "start_time": start,
        "end_time": end,
        "cost": cost,
    }


def _hotel(name, cost, day_no=1):
    return {
        "item_type": "hotel",
        "poi_name": name,
        "start_time": "21:00",
        "end_time": "08:00",
        "cost": cost,
    }


def _attraction(name, start, end, cost=0):
    return {
        "item_type": "attraction",
        "poi_name": name,
        "start_time": start,
        "end_time": end,
        "cost": cost,
    }


def test_meal_slot_windows():
    assert meal_slot_of("12:00") == "lunch"
    assert meal_slot_of("18:30") == "dinner"
    assert meal_slot_of("08:00") == "breakfast"
    assert meal_slot_of("15:00") == "other"
    assert meal_slot_of(None) is None


def test_has_double_lunch():
    foods = [
        _food("A", "11:30", "12:30", 80),
        _food("B", "13:00", "14:00", 90),
    ]
    assert has_double_lunch(foods)
    ok = [
        _food("A", "12:00", "13:00", 80),
        _food("B", "19:00", "20:00", 90),
    ]
    assert not has_double_lunch(ok)


def test_validate_plans_flags_double_lunch():
    plans = [
        _plan(
            items=[
                _attraction("景", "09:00", "11:00"),
                _food("午1", "11:30", "12:30", 80),
                _food("午2", "13:00", "14:00", 90),
            ]
        )
    ]
    issues, _ = validate_plans(plans)
    assert any("两顿午餐" in i for i in issues)


def test_validate_plans_budget_overage():
    plans = [
        _plan(
            items=[
                _attraction("景", "09:00", "11:00", cost=100),
                _food("餐", "12:00", "13:00", cost=200),
                _hotel("店", cost=2000),
            ]
        )
    ]
    # 2人：门票200 + 餐400 + 酒店2000*1 + 交通35*2 = 2670 > 1000
    issues, _ = validate_plans(plans, budget=1000, persons=2, consumption={"transport_price": 35})
    assert any("超出预算" in i for i in issues)


def test_validate_plans_within_budget():
    plans = [
        _plan(
            items=[
                _attraction("景", "09:00", "11:00", cost=0),
                _food("餐", "12:00", "13:00", cost=40),
            ]
        )
    ]
    issues, _ = validate_plans(plans, budget=5000, persons=1, consumption={"transport_price": 35})
    assert not any("超出预算" in i for i in issues)


def test_clamp_meal_cost_hard_cap():
    new_cost, note = clamp_meal_cost(1200, 80, hard_ratio=8, soft_ratio=4)
    assert new_cost == 320  # soft = 80*4
    assert note and "钳制" in note


def test_clamp_meal_cost_soft_cap():
    new_cost, note = clamp_meal_cost(400, 80, hard_ratio=8, soft_ratio=4)
    assert new_cost == 240  # soft*0.75
    assert note


def test_clamp_meal_cost_normal_passthrough():
    new_cost, note = clamp_meal_cost(60, 80, hard_ratio=8, soft_ratio=4)
    assert new_cost == 60
    assert note is None


def test_estimate_plans_total_hotel_rooms():
    plans = [
        _plan(1, [_attraction("A", "09:00", "11:00", 50), _food("F", "12:00", "13:00", 40), _hotel("H", 300)]),
        _plan(2, [_attraction("B", "09:00", "11:00", 0)]),
    ]
    est = estimate_plans_total(plans, persons=2, days=2, consumption={"transport_price": 35})
    # 门票 50*2，餐 40*2，酒店 300*1（N-1晚），交通 35*2*2
    assert est["门票"] == 100
    assert est["餐饮"] == 80
    assert est["酒店"] == 300
    assert est["交通"] == 140
    assert est["合计"] == 620


def test_fill_suggestion_gaps_noop_when_web_disabled(monkeypatch):
    from app.common.config import settings

    monkeypatch.setattr(settings, "web_search_enabled", False)
    rows = [{"name": "X", "category": "hotel"}]
    assert fill_suggestion_gaps(rows, "东京") is rows or fill_suggestion_gaps(rows, "东京") == rows


def test_fill_suggestion_gaps_adds_missing_categories(monkeypatch):
    from app.common.config import settings

    monkeypatch.setattr(settings, "web_search_enabled", True)

    def fake_search(city, category, limit=4, budget_tier=None):
        return [
            {"name": f"{city}-{category}-{i}", "category": category, "intro": None, "estimated_cost": None}
            for i in range(limit)
        ]

    monkeypatch.setattr("app.agent.web_search.search_places_via_web", fake_search)
    monkeypatch.setattr("app.agent.web_search.web_search_enabled", lambda: True)
    # fill_suggestion_gaps 内部 import 的是模块函数，需 patch 到 generators 的引用路径
    import app.agent.web_search as ws

    monkeypatch.setattr(ws, "search_places_via_web", fake_search)
    monkeypatch.setattr(ws, "web_search_enabled", lambda: True)

    filled = fill_suggestion_gaps([{"name": "已有景点", "category": "attraction"}], "东京")
    cats = {s["category"] for s in filled}
    assert "hotel" in cats
    assert "activity" in cats
    assert "food" in cats
