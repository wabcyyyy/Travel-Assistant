"""分天流式生成：上下文一次构建，单日按需生成（供 Java 逐日编排）。

知识库城市走候选约束路径；未知城市/省份自动进入开放模式（LLM 知识 + 高德落坐标）。
"""

import json
import logging
from datetime import date

import httpx

from app.agent import tools
from app.agent.generators import (
    _parse_json,
    fallback_generate,
    llm_generate,
    _pick_hotels,
)
from app.agent.tools import search_attractions, search_foods, search_hotels
from app.common.config import settings
from app.common.llm_client import get_llm_client
from app.common.season import season_factor, season_label
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


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _llm_open_day(req: GenerateDayRequest, used: set[str]) -> dict:
    """开放模式：LLM 凭自身知识为任意城市/省份安排一天行程。"""
    client = get_llm_client()
    if req.chosen_hotel:
        hotel_hint = f"酒店固定为「{req.chosen_hotel}」，不得更换。"
    else:
        hotel_hint = "选一家当地知名舒适型酒店。"
    system = (
        "你是资深当地导游。基于你的目的地知识为用户安排一天行程，只输出 JSON："
        '{"note":"当天主题","items":[{"item_type":"attraction|food|hotel","poi_name":"真实存在的地点名称",'
        '"start_time":"HH:mm","end_time":"HH:mm","duration_min":数字,"cost":人均人民币估算数字,"tag":"标签",'
        '"remark":"参考价"}]}。'
        "硬性要求：poi_name 必须是简洁的正式地点名（≤10 字，如「龙门石窟」「开封府」），"
        "禁止写成描述性句子；安排 3 个景点+1 家餐饮+1 家酒店；"
        f"{hotel_hint}"
        f"避开已去过的地点：{json.dumps(sorted(used), ensure_ascii=False)}。"
        "免费景点 cost 写 0；其余 cost 为合理人民币估算，不要写 0。"
    )
    raw = client.complete(
        f"目的地：{req.city}（第 {req.day_no} 天，{req.persons} 人）",
        system_prompt=system,
        temperature=0.4,
        max_tokens=2000,
    )
    plan = _parse_json(raw)
    plan.setdefault("items", [])
    return plan


def _amap_ground(item: dict, city: str, cache: dict) -> None:
    """高德 POI 检索落坐标/地址（省份等模糊 city 自动降级重试）。"""
    if not settings.amap_web_key or item.get("latitude") is not None:
        return
    key = f"{city}:{item.get('poi_name')}"
    if key in cache:
        hit = cache[key]
        if hit:
            item["latitude"] = hit["lat"]
            item["longitude"] = hit["lng"]
            item["address"] = hit.get("address")
        return
    try:
        def _search(params):
            r = httpx.get("https://restapi.amap.com/v3/place/text",
                          params=params, timeout=10)
            return r.json().get("pois") or []

        base = {"keywords": (item.get("poi_name") or "")[:12], "offset": 1,
                "key": settings.amap_web_key}
        pois = _search({**base, "city": city, "citylimit": "true"})
        if not pois:
            pois = _search({**base, "city": city})
        if not pois:
            pois = _search(base)
        if pois:
            loc = (pois[0].get("location") or "").split(",")
            if len(loc) == 2:
                item["longitude"] = float(loc[0])
                item["latitude"] = float(loc[1])
                item["address"] = pois[0].get("address") or None
                cost = pois[0].get("cost")
                if cost and not item.get("cost"):
                    try:
                        item["cost"] = float(cost)
                    except (TypeError, ValueError):
                        pass
                cache[key] = {"lat": item["latitude"], "lng": item["longitude"],
                              "address": item.get("address")}
                return
        cache[key] = None
    except Exception as e:  # noqa: BLE001
        logger.warning("amap ground failed: %s", e)
        cache[key] = None


def run_generate_day(req: GenerateDayRequest) -> DailyPlan:
    ctx = req.context or {}
    candidates = _filter_used(ctx.get("candidates") or [], set(req.used_names))
    foods = _filter_used(ctx.get("foods") or [], set(req.used_names))
    hotels = _pick_hotels(ctx.get("hotels") or [], req.hotel_tier, 3)
    consumption = ctx.get("consumption")

    feedback = ""
    if req.chosen_hotel:
        feedback = f"酒店必须沿用「{req.chosen_hotel}」，不得更换。"

    if not candidates:
        # 开放模式：知识库无该城市，LLM 凭自身知识安排，坐标由高德落点
        plan = _llm_open_day(req, set(req.used_names))
        source = "open"
    elif settings.llm_api_key:
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
    for poi in (candidates or []) + (foods or []):
        if poi.get("name"):
            lookup[poi["name"]] = poi

    trip_date = _parse_date(req.start_date)
    factor = season_factor(trip_date)
    label = season_label(trip_date)
    ground_cache: dict = {}

    items: list[TripItem] = []
    for item in plan.get("items") or []:
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
        if source == "open":
            _amap_ground(item, req.city, ground_cache)

        def _norm(t):
            return t.replace("24:", "00:") if isinstance(t, str) else t

        item["start_time"] = _norm(item.get("start_time"))
        item["end_time"] = _norm(item.get("end_time"))

        if item.get("item_type") == "hotel" and factor != 1.0 and item.get("cost"):
            base = float(item["cost"])
            item["cost"] = round(base * factor, 2)
            remark = f"{label}估算：系数×{factor}（基准价￥{base:g}）"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
        items.append(TripItem(**item))

    note = plan.get("note") or f"第 {req.day_no} 天行程"
    if source == "open":
        note = (note + "（开放模式，价格供参考）").strip()
    return DailyPlan(day_no=req.day_no, note=note, items=items)
