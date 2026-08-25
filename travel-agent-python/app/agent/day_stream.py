"""分天流式生成：上下文一次构建，单日按需生成（供 Java 逐日编排）。"""

import logging
from datetime import date

from app.agent import tools
from app.agent.generators import fallback_generate, llm_generate, _pick_hotels
from app.agent.tools import search_attractions, search_foods, search_hotels
from app.common.season import season_factor, season_label
from app.common.config import settings
from app.schemas.trip import DailyPlan, GenerateDayRequest, TripItem

logger = logging.getLogger(__name__)


def run_plan_context(city: str, preferences: list[str]) -> dict:
    return {
        "candidates": search_attractions(city, preferences),
        "foods": search_foods(city),
        "hotels": search_hotels(city),
        "consumption": tools.get_consumption(city),
    }


def _filter_used(items: list[dict], used: set[str]) -> list[dict]:
    kept = [i for i in items if i.get("name") not in used]
    return kept or items


def run_generate_day(req: GenerateDayRequest) -> DailyPlan:
    ctx = req.context or {}
    candidates = _filter_used(ctx.get("candidates") or [], set(req.used_names))
    if not candidates and not req.used_names:
        raise ValueError(
            f"知识库暂无 {req.city} 的景点数据，请选择已支持的城市"
            "（北京/上海/杭州/成都/西安/三亚）"
        )
    foods = _filter_used(ctx.get("foods") or [], set(req.used_names))
    hotels = _pick_hotels(ctx.get("hotels") or [], req.hotel_tier, 3)
    consumption = ctx.get("consumption")

    feedback = ""
    if req.chosen_hotel:
        feedback = f"酒店必须沿用「{req.chosen_hotel}」，不得更换。"
    if settings.llm_api_key:
        try:
            plans, _budget = llm_generate(
                req.city, 1, req.persons, [],
                candidates, foods, consumption,
                feedback=feedback, hotels=hotels or None,
            )
            plan = plans[0]
            source = "llm"
        except Exception as e:  # noqa: BLE001
            logger.warning("day %s llm failed: %s", req.day_no, e)
            plans, _budget = fallback_generate(
                req.city, 1, req.persons, [], hotels or None, req.hotel_tier,
                attractions=candidates, foods=foods, consumption=consumption,
            )
            plan = plans[0]
            source = "fallback"
    else:
        plans, _budget = fallback_generate(
            req.city, 1, req.persons, [], hotels or None, req.hotel_tier,
            attractions=candidates, foods=foods, consumption=consumption,
        )
        plan = plans[0]
        source = "fallback"

    lookup: dict[str, dict] = {}
    for poi in (candidates or []) + (foods or []) + (hotels or []):
        if poi.get("name"):
            lookup[poi["name"]] = poi

    raw_items = list(plan.get("items") or [])
    if not req.needs_hotel:
        raw_items = [item for item in raw_items if item.get("item_type") != "hotel"]
    elif not any(item.get("item_type") == "hotel" for item in raw_items) and hotels:
        selected = next((hotel for hotel in hotels if hotel.get("name") == req.chosen_hotel), hotels[0])
        raw_items.append({
            "item_type": "hotel",
            "poi_name": selected.get("name"),
            "poi_id": str(selected.get("id") or ""),
            "address": selected.get("address"),
            "latitude": selected.get("latitude"),
            "longitude": selected.get("longitude"),
            "start_time": "20:00",
            "duration_min": 30,
            "cost": float(selected.get("ticket_price") or 0),
            "tag": selected.get("tags"),
            "remark": "系统补全当晚住宿",
        })

    factor = season_factor(_parse_date(req.start_date))
    label = season_label(_parse_date(req.start_date))

    def _norm(t):
        return t.replace("24:", "00:") if isinstance(t, str) else t

    items: list[TripItem] = []
    for item in raw_items:
        poi = lookup.get(item.get("poi_name"))
        if poi:
            if item.get("latitude") is None and poi.get("latitude") is not None:
                item["latitude"] = float(poi["latitude"])
            if item.get("longitude") is None and poi.get("longitude") is not None:
                item["longitude"] = float(poi["longitude"])
            if not item.get("poi_id"):
                item["poi_id"] = str(poi.get("id") or "")
            if item.get("cost") is None and poi.get("ticket_price") is not None:
                item["cost"] = float(poi["ticket_price"])
        if item.get("item_type") == "hotel" and factor != 1.0 and item.get("cost"):
            base = float(item["cost"])
            item["cost"] = round(base * factor, 2)
            remark = f"{label}估算：系数×{factor}（基准价￥{base:g}）"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
        items.append(TripItem(**item))

    note = plan.get("note") or f"第 {req.day_no} 天行程"
    if source == "fallback":
        note = (note + "（兜底生成）").strip()
    return DailyPlan(day_no=req.day_no, note=note, items=items)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None
