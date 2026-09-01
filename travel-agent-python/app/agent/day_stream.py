"""分天流式生成：上下文一次构建，单日按需生成（供 Java 逐日编排）。

知识库城市走候选约束路径；未知城市/省份自动进入开放模式（LLM 知识 + 高德落坐标）。
"""

import json
import logging
from datetime import date

from app.agent import tools
from app.agent.generators import (
    _parse_json,
    fallback_generate,
    llm_generate,
    _pick_hotels,
)
from app.agent.tools import (
    attach_poi_images,
    search_attractions,
    search_foods,
    search_hotels,
)
from app.common.config import settings
from app.common.llm_client import get_llm_client
from app.common.season import season_factor, season_label
from app.agent.trace import traced
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


@traced("llm", "llm.open_day")
def _llm_open_day(req: GenerateDayRequest, used: set[str]) -> dict:
    """开放模式：LLM 凭自身知识为任意城市/省份安排一天行程。"""
    client = get_llm_client()
    total_days = req.days or 1
    if total_days <= 3:
        pace = "可安排 2-3 个景点"
    else:
        pace = "安排 1-2 个景点（长途慢节奏，避免赶场）"
    if req.chosen_hotel:
        hotel_hint = f"酒店必须沿用「{req.chosen_hotel}」，不得更换。"
    elif req.needs_hotel:
        hotel_hint = "选一家当地知名舒适型酒店。"
    else:
        hotel_hint = ""
    hotel_clause = "安排 1 家酒店；" if req.needs_hotel else "今日无需安排酒店；"
    system = (
        "你是资深当地导游。基于你的目的地知识为用户安排一天行程，只输出 JSON："
        '{"note":"当天主题","items":[{"item_type":"attraction|food|hotel","poi_name":"真实存在的地点名称",'
        '"start_time":"HH:mm","end_time":"HH:mm","duration_min":数字,"cost":人均人民币估算数字,"tag":"标签",'
        '"remark":"参考价"}]}。'
        "硬性要求：poi_name 必须是简洁的正式地点名（≤10 字，如「龙门石窟」「开封府」），"
        f"禁止写成描述性句子；{pace}（依景点游玩时长与地理位置远近灵活调整，不赶场）+1 家餐饮+{hotel_clause}"
        f"{hotel_hint}"
        f"避开已去过的地点：{json.dumps(sorted(used), ensure_ascii=False)}。"
        "免费景点 cost 写 0；其余 cost 为合理人民币估算，不要写 0。"
    )
    if req.feedback:
        system += f"上一轮确定性校验发现以下问题，本轮必须修正：{req.feedback}"
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
    """通过高德 MCP/兼容适配器检索 POI，落坐标与地址。"""
    if item.get("latitude") is not None:
        return
    key = f"{city}:{item.get('poi_name')}"
    if key in cache:
        hit = cache[key]
        if hit:
            item["latitude"] = hit["lat"]
            item["longitude"] = hit["lng"]
            item["address"] = hit.get("address")
            if hit.get("photo"):
                item["image"] = hit["photo"]
        return
    try:
        pois = tools.search_amap_poi(city, item.get("poi_name") or "")
        if pois:
            hit = pois[0]
            if hit.get("longitude") is not None and hit.get("latitude") is not None:
                item["longitude"] = float(hit["longitude"])
                item["latitude"] = float(hit["latitude"])
                item["address"] = hit.get("address") or None
                if hit.get("ticket_price") is not None and not item.get("cost"):
                    item["cost"] = float(hit["ticket_price"])
                if hit.get("image"):
                    item["image"] = hit["image"]
                cache[key] = {"lat": item["latitude"], "lng": item["longitude"],
                              "address": item.get("address"), "photo": hit.get("image")}
                return
        cache[key] = None
    except Exception as e:  # noqa: BLE001
        logger.warning("amap ground failed: %s", e)
        cache[key] = None


def _canonicalize_known_plan(
    plan: dict,
    candidates: list[dict],
    foods: list[dict],
    hotels: list[dict],
) -> dict:
    """验证已知城市的模型结果，并用候选数据覆盖事实字段。

    Prompt 只能降低幻觉概率，不能成为安全边界。这里把名称作为引用键，
    不在候选池中的非交通项目直接拒绝；价格、坐标和营业时间不接受模型自填。
    """
    authority: dict[str, dict] = {}
    for poi in candidates + foods + hotels:
        name = str(poi.get("name") or "").strip()
        if name and name not in authority:
            authority[name] = poi

    normalized_items: list[dict] = []
    for raw_item in plan.get("items") or []:
        if not isinstance(raw_item, dict) or not str(raw_item.get("poi_name") or "").strip():
            raise ValueError("LLM 返回了缺少地点名称的行程项")
        item = dict(raw_item)
        name = str(item["poi_name"]).strip()
        item["poi_name"] = name
        if item.get("item_type") == "transport":
            # 交通是行程中的合成项，不要求对应 POI，但仍保留结构化时间字段。
            normalized_items.append(item)
            continue
        poi = authority.get(name)
        if poi is None:
            raise ValueError(f"行程项「{name}」不在候选 POI 白名单中")
        item["item_type"] = poi.get("category") or item.get("item_type") or "attraction"
        item["poi_id"] = str(poi.get("id") or "") or None
        item["address"] = poi.get("address")
        item["latitude"] = poi.get("latitude")
        item["longitude"] = poi.get("longitude")
        item["duration_min"] = poi.get("duration_min")
        item["open_time"] = poi.get("open_time")
        item["tag"] = poi.get("tags")
        if poi.get("ticket_price") is not None:
            item["cost"] = float(poi["ticket_price"])
        elif item["item_type"] in {"attraction", "food"}:
            # 知识库 NULL 表示暂无门票/餐饮单价，不能让模型偷偷写入价格。
            item["cost"] = 0.0
            item["remark"] = "知识库未提供价格，按0计，实际以现场为准"
        else:
            item["cost"] = 0.0
            item["remark"] = "知识库未提供房价，需现场核实"
        normalized_items.append(item)
    normalized = dict(plan)
    normalized["items"] = normalized_items
    return normalized


def _generate_day_once(req: GenerateDayRequest, *, force_fallback: bool = False) -> tuple[DailyPlan, str]:
    """执行一次单日生成。

    该函数只负责一次候选生成和确定性补水，反思/重试由 day_workflow 统一编排，
    避免 Java 逐日调用时绕过 Agent 的质量闭环。
    """
    ctx = req.context or {}
    candidates = _filter_used(ctx.get("candidates") or [], set(req.used_names))
    foods = _filter_used(ctx.get("foods") or [], set(req.used_names))
    hotels = _pick_hotels(ctx.get("hotels") or [], req.hotel_tier, 3)
    consumption = ctx.get("consumption")

    feedback = req.feedback or ""
    if req.chosen_hotel:
        hotel_feedback = f"酒店必须沿用「{req.chosen_hotel}」，不得更换。"
        feedback = f"{feedback}；{hotel_feedback}" if feedback else hotel_feedback

    if not candidates:
        # 开放模式没有本地权威候选，无法使用 generators.fallback_generate 的
        # 确定性路线。即使工作流已经进入 force_fallback，也要继续走开放模式的
        # LLM 生成，否则某一天的校验失败会把整个多日行程直接打成失败。
        # 坐标和地址仍由后面的高德落点逻辑补齐；这是开放城市唯一可用的降级源。
        plan = _llm_open_day(req, set(req.used_names))
        source = "open"
    elif settings.llm_api_key and not force_fallback:
        try:
            plans, _budget = llm_generate(
                req.city, 1, req.persons, [],
                candidates, foods, consumption,
                feedback=feedback, hotels=hotels or None,
                pace_days=req.days,
            )
            plan = _canonicalize_known_plan(plans[0], candidates, foods, hotels)
            source = "llm"
        except Exception as e:  # noqa: BLE001
            logger.warning("day %s llm failed: %s", req.day_no, e)
            plans, _budget = fallback_generate(
                req.city, 1, req.persons, [], hotels or None, req.hotel_tier,
                attractions=candidates, foods=foods, consumption=consumption,
                pace_days=req.days,
            )
            plan = plans[0]
            source = "fallback"
    else:
        plans, _budget = fallback_generate(
            req.city, 1, req.persons, [], hotels or None, req.hotel_tier,
            attractions=candidates, foods=foods, consumption=consumption,
            pace_days=req.days,
        )
        plan = plans[0]
        source = "fallback"

    if source != "open":
        attach_poi_images([plan], req.city)

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
            if item.get("open_time") is None:
                item["open_time"] = poi.get("open_time")
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
    return DailyPlan(day_no=req.day_no, note=note, items=items), source


def run_generate_day(req: GenerateDayRequest) -> DailyPlan:
    """通过 LangGraph 执行单日生成闭环，保持原有 HTTP 契约不变。"""
    # 延迟导入是为了让 day_workflow 复用本模块的单次执行函数时不形成循环导入。
    from app.agent.day_workflow import run_day_agent

    return run_day_agent(req)
