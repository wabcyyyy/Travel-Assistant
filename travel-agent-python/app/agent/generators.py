"""行程内容的生成器：同时提供 LLM 生成与确定性兜底两条路线。

职责：
- llm_generate：调用 LLM 按 JSON Schema 生成每日计划与预算，带结构校验与解析修复；
- fallback_generate：LLM 不可用时的确定性兜底，按时间槽 + 最近邻顺序排布景点/餐饮/酒店；
- dedupe_daily_plans：去除跨天重复景点/餐饮（优先用候选池替换，酒店不动）；
- 预算估算与 LLM 输出 JSON 解析等工具函数。

实现要点：
- LLM 只能从候选列表里选 POI，价格取候选原值或城市消费系数估算，严禁编造；
- fallback_generate 用 geo.nearest_neighbor_order 串路线，生成后统一走 dedupe_daily_plans；
- 两条路线对外返回相同的 (daily_plans, budget) 结构，供 workflow 统一消费。

依赖：tools（检索候选）、geo（最近邻排序）、llm_client。
"""

import decimal
import json
import logging
from math import ceil

from app.agent import tools
from app.agent.geo import nearest_neighbor_order
from app.agent.trace import traced
from app.common.config import settings
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    return str(o)

TIME_SLOTS = [
    ("09:00", "11:30"),
    ("13:30", "16:00"),
    ("19:00", "20:30"),
]
THREE_ATTRACTION_SLOTS = [
    ("09:00", "11:00"),
    ("13:30", "15:30"),
    ("16:00", "18:00"),
]


def _daily_attraction_target(days: int) -> int:
    """确定性兜底的每日景点数：总天数越长，每日安排越精简、节奏越舒适。"""
    # 两个景点能为跨城移动和用餐保留足够缓冲；短途也不以堆景点换取数量。
    return 2


def _pace_guidance(days: int) -> tuple[str, str]:
    """根据总行程天数给 LLM 的每日景点数量节奏建议：行程越长越慢。

    返回 (每日景点数量建议, 节奏说明)。短途可紧凑多打卡，长途以舒适慢节奏为主，
    具体数量仍由模型结合景点时长与距离灵活调整。
    """
    if days <= 2:
        return "3 个景点", "短途行程可紧凑多打卡"
    if days <= 4:
        return "2-3 个景点", "中等节奏"
    if days <= 7:
        return "2 个景点", "放缓节奏，留出用餐与休息"
    return "1-2 个景点", "长途旅行以舒适慢节奏为主，避免赶场"


_TIER_KEYWORDS = {
    "经济型": ("经济",),
    "舒适型": ("舒适", "中端"),
    "高档型": ("高端", "高档"),
    "豪华型": ("高端", "五星", "国宾", "地标"),
    "奢华型": ("国宾", "地标", "五星", "百年"),
}


def _pick_hotels(hotels: list[dict] | None, tier: str | None, count: int) -> list[dict]:
    """按档次关键词优先挑选（tier 可为「经济型、豪华型」多选拼接），凑不满则用其余补齐。"""
    if not hotels:
        return []
    keywords: tuple[str, ...] = ()
    for part in (tier or "").replace("，", "、").split("、"):
        if not part:
            continue
        if part in _TIER_KEYWORDS:
            keywords = keywords + _TIER_KEYWORDS[part]
        else:
            keywords = keywords + (part,)
    matched = [h for h in hotels
               if any(k in (h.get("description") or "") + (h.get("tags") or "") for k in keywords)]
    picked = matched + [h for h in hotels if h not in matched]
    return picked[:count]


def fallback_generate(city: str, days: int, persons: int, preferences: list[str],
                      hotels: list[dict] | None = None,
                      hotel_tier: str | None = None,
                      attractions: list[dict] | None = None,
                      foods: list[dict] | None = None,
                      consumption: dict | None = None,
                      pace_days: int | None = None) -> tuple[list[dict], dict]:
    attractions = attractions if attractions is not None else tools.search_attractions(city, preferences)
    foods = foods if foods is not None else tools.search_foods(city)
    consumption = consumption if consumption is not None else tools.get_consumption(city)

    daily_plans: list[dict] = []
    cursor = 0
    ordered = nearest_neighbor_order(attractions)
    if not ordered:
        ordered = attractions
    for day_no in range(1, days + 1):
        items: list[dict] = []
        for slot_index in range(_daily_attraction_target(pace_days or days)):
            poi = ordered[cursor % len(ordered)] if ordered else None
            cursor += 1
            if poi is None:
                continue
            slots = THREE_ATTRACTION_SLOTS if _daily_attraction_target(pace_days or days) >= 3 else TIME_SLOTS
            start, end = slots[slot_index]
            items.append(_to_item(poi, start, end))
        if foods:
            food = foods[day_no % len(foods)]
            # 三景点日的 19:00 槽已经是最后一个景点，晚餐若紧接其后会
            # 没有任何换乘余量；放到午间空档，给下午/晚间景点留出路线缓冲。
            meal_start, meal_end = ("11:30", "12:30") if len(items) >= 3 else ("18:00", "19:00")
            items.append(_to_item(food, meal_start, meal_end))
        tier_hotels = _pick_hotels(hotels, hotel_tier, 2)
        items.append(_hotel_item(city, consumption, tier_hotels or hotels, day_no))
        daily_plans.append({"day_no": day_no, "note": f"{city}第{day_no}天行程", "items": items})

    budget = _estimate_budget(attractions, foods, consumption, days, persons)
    return daily_plans, budget


@traced("llm", "llm.generate")
def llm_generate(city: str, days: int, persons: int, preferences: list[str],
                 candidates: list[dict], foods: list[dict], consumption: dict | None,
                 feedback: str = "", hotels: list[dict] | None = None,
                 hotel_tier: str | None = None,
                 pace_days: int | None = None) -> tuple[list[dict], dict]:
    client = get_llm_client()
    pace_days = pace_days or days
    pace_target, pace_note = _pace_guidance(pace_days)
    pace_clause = (
        f"每天景点数量不固定为 3 个：整体行程共 {pace_days} 天，建议每天安排 {pace_target}（{pace_note}）。"
        "具体数量请结合候选景点的游玩时长（duration_min）与相邻景点间的距离（候选含经纬度）灵活调整："
        "单点耗时较长或景点间距离较远时，适当减少当日景点数，保证不赶场。"
    )
    system_prompt = (
        "你是资深旅行规划师。只输出 JSON，不要输出任何其他文字，不要用 markdown 代码块。"
        "景点和酒店必须从候选列表中选择，不得编造。"
        + pace_clause +
        "每天仍需安排 1 家餐饮、1 家酒店（同一酒店可多晚连住）。"
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
    if hotel_tier:
        user_prompt += f"\n酒店档次要求：{hotel_tier}，请从候选酒店中选择符合该档次的酒店。"
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


def dedupe_daily_plans(plans: list[dict], candidates: list[dict] | None = None,
                       foods: list[dict] | None = None) -> list[dict]:
    """去除整个行程中跨天重复的景点/餐饮。

    重复项优先用候选池里尚未使用的同名类型 POI 替换，保持每日密度；候选用尽时直接丢弃。
    酒店不被去重，避免破坏住宿安排。
    """
    if not plans:
        return plans
    used: set[str] = set()
    attr_pool = [c for c in (candidates or []) if c.get("name")]
    food_pool = [f for f in (foods or []) if f.get("name")]

    def _take(pool: list[dict], idx: int):
        while idx < len(pool):
            cand = pool[idx]
            idx += 1
            if cand.get("name") not in used:
                return cand, idx
        return None, idx

    attr_idx = food_idx = 0
    for plan in plans:
        kept: list[dict] = []
        for item in plan.get("items") or []:
            name = item.get("poi_name")
            itype = item.get("item_type")
            if itype in ("attraction", "food") and name:
                if name in used:
                    if itype == "attraction":
                        repl, attr_idx = _take(attr_pool, attr_idx)
                    else:
                        repl, food_idx = _take(food_pool, food_idx)
                    if repl:
                        used.add(repl.get("name"))
                        kept.append(_to_item(repl, item.get("start_time"), item.get("end_time")))
                    continue
                used.add(name)
            kept.append(item)
        plan["items"] = kept
    return plans


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
        "open_time": poi.get("open_time"),
        "cost": poi.get("ticket_price"),
        "tag": poi.get("tags"),
        "remark": None,
        "image": poi.get("image"),
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
