import decimal
import json
import logging
from math import ceil

from app.agent import tools
from app.agent.geo import nearest_neighbor_order
from app.common.config import settings
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    return str(o)

ATTRACTIONS_PER_DAY = 3
TIME_SLOTS = [
    ("09:00", "11:30"),
    ("13:30", "16:00"),
    ("19:00", "20:30"),
]


def fallback_generate(city: str, days: int, persons: int, preferences: list[str],
                      hotels: list[dict] | None = None) -> tuple[list[dict], dict]:
    attractions = tools.search_attractions(city, preferences)
    foods = tools.search_foods(city)
    consumption = tools.get_consumption(city)

    daily_plans: list[dict] = []
    cursor = 0
    ordered = nearest_neighbor_order(attractions)
    if not ordered:
        ordered = attractions
    for day_no in range(1, days + 1):
        items: list[dict] = []
        for slot_index in range(ATTRACTIONS_PER_DAY):
            poi = ordered[cursor % len(ordered)] if ordered else None
            cursor += 1
            if poi is None:
                continue
            start, end = TIME_SLOTS[slot_index]
            items.append(_to_item(poi, start, end))
        if foods:
            food = foods[day_no % len(foods)]
            items.append(_to_item(food, "18:00", "19:00"))
        items.append(_hotel_item(city, consumption, (hotels or []), day_no))
        daily_plans.append({"day_no": day_no, "note": f"{city}第{day_no}天行程", "items": items})

    budget = _estimate_budget(attractions, foods, consumption, days, persons)
    return daily_plans, budget


def llm_generate(city: str, days: int, persons: int, preferences: list[str],
                 candidates: list[dict], foods: list[dict], consumption: dict | None,
                 feedback: str = "", hotels: list[dict] | None = None) -> tuple[list[dict], dict]:
    client = get_llm_client()
    system_prompt = (
        "你是资深旅行规划师。只输出 JSON，不要输出任何其他文字，不要用 markdown 代码块。"
        "景点和酒店必须从候选列表中选择，不得编造。每天安排 3 个景点、1 家餐饮、1 家酒店（同一酒店可多晚连住）。"
        "每个行程项的 cost 必须直接取候选数据中的 ticket_price 字段原值（单人单价；酒店为每晚单间基准价），"
        "候选里没有对应字段时用城市消费系数估算，严禁自行编造价格。"
        "必须严格遵守如下 JSON Schema（字段名、类型、嵌套结构完全一致）："
        '{"type":"object","properties":{"daily_plans":{"type":"array","items":{"type":"object",'
        '"properties":{"day_no":{"type":"integer"},"note":{"type":["string","null"]},'
        '"items":{"type":"array","items":{"type":"object","properties":{'
        '"item_type":{"type":"string","enum":["attraction","food","hotel","transport"]},'
        '"poi_name":{"type":"string"},"start_time":{"type":"string","pattern":"HH:mm"},'
        '"end_time":{"type":"string","pattern":"HH:mm"},"duration_min":{"type":"integer"},'
        '"cost":{"type":"number"},"tag":{"type":["string","null"]},"remark":{"type":["string","null"]}},'
        '"required":["item_type","poi_name"]}}}},'
        '"required":["day_no","items"]}}},'
        '"budget_estimate":{"type":"object","additionalProperties":{"type":"number"}}},"required":["daily_plans","budget_estimate"]}'
        " 每天行程需避免相邻项时间重叠，景点开始时间需在其开放时间内。"
    )
    user_prompt = (
        f"目的地：{city}，共 {days} 天，{persons} 人出行，偏好：{'、'.join(preferences) or '无'}\n"
        f"候选景点：{json.dumps(candidates, ensure_ascii=False, default=_json_default)}\n"
        f"候选餐饮：{json.dumps(foods, ensure_ascii=False, default=_json_default)}\n"
        f"候选酒店：{json.dumps(hotels or [], ensure_ascii=False, default=_json_default)}\n"
        f"城市消费系数：{json.dumps(consumption, ensure_ascii=False, default=_json_default)}\n"
        "预算按人数估算：门票=景点票价×人数，餐饮=人均每餐×2×天数×人数，"
        "交通=人均日交通×天数×人数，酒店=所选酒店每晚基准价×ceil(人数/2)×天数。"
    )
    if feedback:
        user_prompt += f"\n上一轮校验反馈（必须修正）：{feedback}"
    raw = client.complete(user_prompt, system_prompt=system_prompt, temperature=0.3)
    try:
        data = _parse_json(raw)
    except Exception:
        logger.warning("LLM JSON 解析失败，原始输出片段：%s", raw[:300])
        raise
    try:
        daily_plans = _validate_plans(data.get("daily_plans"), days)
    except Exception:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        logger.warning("LLM 行程结构无效，顶层内容：%s", keys)
        raise
    budget = _normalize_budget(data.get("budget_estimate"))
    if not budget:
        budget = _estimate_budget(candidates, foods, consumption, days, persons)
    return daily_plans, budget


_BUDGET_KEY_MAP = {
    "attractions": "门票",
    "tickets": "门票",
    "meals": "餐饮",
    "food": "餐饮",
    "transport": "交通",
    "hotels": "酒店",
    "hotel": "酒店",
    "accommodation": "酒店",
    "total": None,
}


def _normalize_budget(budget) -> dict:
    if not isinstance(budget, dict):
        return {}
    if isinstance(budget.get("breakdown"), dict):
        budget = budget["breakdown"]
    normalized: dict = {}
    for k, v in budget.items():
        if not isinstance(v, (int, float)):
            continue
        key = _BUDGET_KEY_MAP.get(str(k).lower())
        if key is None and str(k).lower() in _BUDGET_KEY_MAP.values():
            key = str(k)
        if key:
            normalized[key] = float(v)
    return normalized


def _validate_plans(plans: list | None, days: int) -> list[dict]:
    if not isinstance(plans, list) or not plans:
        raise ValueError("LLM 返回的行程结构无效")
    valid: list[dict] = []
    for plan in plans:
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            continue
        day_no = int(plan.get("day_no", len(valid) + 1))
        valid.append(
            {
                "day_no": day_no,
                "note": plan.get("note"),
                "items": [i for i in items if isinstance(i, dict) and i.get("poi_name")],
            }
        )
    if len(valid) < days:
        raise ValueError("LLM 返回的天数不足")
    return valid[:days]


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 输出中未找到 JSON")
    return json.loads(text[start : end + 1])


def _to_item(poi: dict, start: str, end: str) -> dict:
    return {
        "item_type": poi.get("category", "attraction"),
        "poi_name": poi.get("name", ""),
        "poi_id": str(poi.get("id") or ""),
        "address": poi.get("address"),
        "latitude": poi.get("latitude"),
        "longitude": poi.get("longitude"),
        "start_time": start,
        "end_time": end,
        "duration_min": poi.get("duration_min"),
        "cost": poi.get("ticket_price"),
        "tag": poi.get("tags"),
        "remark": None,
    }


def _hotel_item(city: str, consumption: dict | None, hotels: list[dict] | None = None,
                day_no: int = 1) -> dict:
    if hotels:
        poi = hotels[(day_no - 1) % len(hotels)]
        return {
            "item_type": "hotel",
            "poi_name": poi.get("name", ""),
            "poi_id": str(poi.get("id") or ""),
            "address": poi.get("address"),
            "latitude": None,
            "longitude": None,
            "start_time": "21:00",
            "end_time": "08:00",
            "duration_min": 660,
            "cost": float(poi.get("ticket_price") or 0),
            "tag": "住宿",
            "remark": poi.get("description") or "知识库酒店基准价",
        }
    price = consumption.get("hotel_price", 300.0) if consumption else 300.0
    return {
        "item_type": "hotel",
        "poi_name": f"{city}市区舒适酒店",
        "poi_id": None,
        "address": f"{city}市中心商圈",
        "latitude": None,
        "longitude": None,
        "start_time": "21:00",
        "end_time": "08:00",
        "duration_min": 660,
        "cost": round(float(price), 2),
        "tag": "酒店",
        "remark": "按单间计费",
    }


def _estimate_budget(attractions: list[dict], foods: list[dict], consumption: dict | None,
                     days: int, persons: int) -> dict:
    ticket = sum(float(a.get("ticket_price") or 0) for a in attractions) / max(len(attractions), 1) * 3
    meal = float(consumption.get("meal_price", 60.0) if consumption else 60.0) * 2
    transport = float(consumption.get("transport_price", 35.0) if consumption else 35.0)
    hotel = float(consumption.get("hotel_price", 300.0) if consumption else 300.0)
    rooms = ceil(persons / 2)
    return {
        "门票": round(ticket * persons, 2),
        "餐饮": round(meal * days * persons, 2),
        "交通": round(transport * days * persons, 2),
        "酒店": round(hotel * rooms * days, 2),
    }