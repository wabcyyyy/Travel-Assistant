"""初次行程生成的工作流编排（LangGraph：生成 → 校验 → 修复 循环）。

职责：
- run_generate：用 StateGraph 串起 parse → search → generate → reflect → format；
- generate_itinerary：优先 LLM 生成，失败或不达标降级 fallback_generate（最多 MAX_FIX_ATTEMPTS 次）；
- reflect：调用 reflect.validate_plans 校验并产出修复反馈；
- format_output：补水坐标/价格（联网实时价或季节系数）并组装 GenerateResponse；
- run_adjust：为“替换某景点”提供候选。

实现要点：
- 基于 langgraph 的状态图，reflect 不通过则带 feedback 回到 generate 重试；
- 与 chat_draft 的“对话编辑”链路不同，本模块负责从零生成首版行程；
- 酒店定价链：联网实时价 → 知识库基准价 × 季节系数（season_factor）估算。

依赖：generators、reflect、tools、pricing、season、schemas.trip。
"""

import logging
from datetime import date
from math import ceil
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent import tools
from app.agent.generators import dedupe_daily_plans, fallback_generate, llm_generate
from app.agent.day_stream import _canonicalize_known_plan
from app.agent.pricing import query_live_price
from app.agent.reflect import build_feedback, validate_plans
from app.agent.trace import record_event, traced
from app.agent.tools import search_attractions, search_foods, search_hotels
from app.common.config import settings
from app.common.season import season_factor, season_label
from app.schemas.trip import AdjustRequest, AdjustResponse, DailyPlan, GenerateRequest, GenerateResponse, PoiOption, TripItem

logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = 2


class AgentState(TypedDict):
    request: GenerateRequest
    requirements: dict
    candidates: list[dict]
    foods: list[dict]
    hotels: list[dict]
    consumption: dict | None
    daily_plans: list[dict]
    budget_estimate: dict
    result: GenerateResponse
    attempts: int
    fix_count: int
    error: str | None
    feedback: str
    validation_issues: list[str]
    validation_log: list[str]
    degraded_reason: str | None


@traced("node", "parse")
def parse_requirements(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    requirements = {
        "city": req.city,
        "days": req.days,
        "persons": req.persons,
        "budget": req.budget,
        "preferences": req.preferences,
        "start_date": req.start_date,
    }
    return {"request": req, "requirements": requirements}


@traced("node", "search")
def search_pois(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    candidates = tools.search_attractions(req.city, req.preferences)
    foods = tools.search_foods(req.city)
    hotels = search_hotels(req.city)
    consumption = tools.get_consumption(req.city)
    return {"candidates": candidates, "foods": foods, "hotels": hotels,
            "consumption": consumption}


@traced("node", "generate")
def generate_itinerary(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    if not state.get("candidates"):
        raise ValueError(
            f"知识库暂无 {req.city} 的景点数据，请选择已支持的城市"
            "（北京/上海/杭州/成都/西安/三亚）"
        )
    attempts = state.get("attempts", 0)
    feedback = state.get("feedback", "")
    if settings.llm_api_key and attempts < MAX_FIX_ATTEMPTS:
        try:
            plans, budget = llm_generate(
                req.city, req.days, req.persons, req.preferences,
                state["candidates"], state["foods"], state["consumption"],
                feedback=feedback, hotels=state.get("hotels"), hotel_tier=req.hotel_tier,
            )
            plans = [
                _canonicalize_known_plan(plan, state["candidates"], state["foods"], state.get("hotels") or [])
                for plan in plans
            ]
            plans, budget = dedupe_daily_plans(
                plans, state.get("candidates"), state.get("foods")
            ), budget
            return {"daily_plans": plans, "budget_estimate": budget, "error": None}
        except Exception as e:
            logger.warning("llm generate failed (attempt %s): %s", attempts + 1, e)
            if attempts + 1 >= MAX_FIX_ATTEMPTS:
                logger.info("LLM 连续失败，降级为确定性兜底生成")
                record_event("route", "fallback", metadata={"reason": "llm_error"})
                plans, budget = fallback_generate(
                    req.city, req.days, req.persons, req.preferences, state.get("hotels"),
                    req.hotel_tier, attractions=state.get("candidates"),
                    foods=state.get("foods"), consumption=state.get("consumption"),
                )
                plans = dedupe_daily_plans(plans, state.get("candidates"), state.get("foods"))
                return {
                    "daily_plans": plans,
                    "budget_estimate": budget,
                    "error": None,
                    "degraded_reason": "LLM 连续失败，已使用确定性 fallback",
                }
            return {"error": str(e), "attempts": attempts + 1}
    plans, budget = fallback_generate(
        req.city, req.days, req.persons, req.preferences, state.get("hotels"),
        req.hotel_tier, attractions=state.get("candidates"),
        foods=state.get("foods"), consumption=state.get("consumption"),
    )
    record_event("route", "fallback", metadata={"reason": "llm_disabled"})
    plans = dedupe_daily_plans(plans, state.get("candidates"), state.get("foods"))
    return {
        "daily_plans": plans,
        "budget_estimate": budget,
        "error": None,
        "degraded_reason": "未配置 LLM，使用确定性 fallback",
    }


@traced("node", "reflect")
def reflect(state: AgentState) -> dict:
    plans = state.get("daily_plans") or []
    issues: list[str] = []
    log: list[str] = []
    if state.get("error"):
        log.append("生成失败，跳过校验")
        return {"validation_issues": issues, "validation_log": log, "fix_count": state.get("fix_count", 0)}
    if plans:
        issues, log = validate_plans(plans)
    record_event("decision", "reflect_result", metadata={
        "issue_count": len(issues), "needs_fix": bool(issues),
    })
    return {
        "validation_issues": issues,
        "validation_log": log,
        "feedback": build_feedback(issues),
        "fix_count": state.get("fix_count", 0) + (1 if issues else 0),
    }


def needs_fix(state: AgentState) -> str:
    if state.get("error") and state.get("attempts", 0) < MAX_FIX_ATTEMPTS:
        route = "fix"
        record_event("route", route, metadata={"reason": "generation_error"})
        return route
    if state.get("validation_issues") and state.get("fix_count", 0) <= MAX_FIX_ATTEMPTS:
        route = "fix"
        record_event("route", route, metadata={"reason": "validation_issue"})
        return route
    record_event("route", "pass", metadata={"reason": "validation_pass"})
    return "pass"


@traced("node", "format")
def format_output(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    raw_plans = state["daily_plans"]
    budget_source = state["budget_estimate"]
    quality_fallback_reason: str | None = None
    if state.get("validation_issues") and state.get("fix_count", 0) > MAX_FIX_ATTEMPTS:
        # LLM 修复耗尽后不把已知的坏路线直接交给用户，切换到可解释的确定性方案。
        raw_plans, budget_source = fallback_generate(
            req.city,
            req.days,
            req.persons,
            req.preferences,
            state.get("hotels"),
            req.hotel_tier,
            attractions=state.get("candidates"),
            foods=state.get("foods"),
            consumption=state.get("consumption"),
        )
        raw_plans = dedupe_daily_plans(raw_plans, state.get("candidates"), state.get("foods"))
        quality_fallback_reason = (
            "LLM 结果未通过约束校验，已使用确定性 fallback；"
            "达到重试上限后仍存在行程约束问题"
        )
        record_event("route", "fallback", metadata={"reason": "validation_retry_exhausted"})
    lookup: dict[str, dict] = {}
    for poi in (state.get("candidates") or []) + (state.get("foods") or []):
        name = poi.get("name")
        if name and name not in lookup:
            lookup[name] = poi
    daily_plans = []
    tools.attach_poi_images(raw_plans, req.city)
    trip_date: date | None = None
    if req.start_date:
        try:
            trip_date = date.fromisoformat(req.start_date)
        except ValueError:
            trip_date = None
    factor = season_factor(trip_date)
    label = season_label(trip_date)

    # 酒店定价链：联网实时价 → 知识库基准价×季节系数（估算）
    live_cache: dict[str, dict | None] = {}
    remaining = {"n": settings.max_live_queries if settings.live_price_search else 0}

    def price_hotel(item: dict) -> None:
        name = item.get("poi_name") or ""
        if name not in live_cache:
            if remaining["n"] > 0 and settings.llm_api_key:
                remaining["n"] -= 1
                live_cache[name] = query_live_price(req.city, name, req.start_date)
            else:
                live_cache[name] = None
        live = live_cache.get(name)
        if item.get("item_type") != "hotel" or not item.get("cost"):
            return
        base = float(item["cost"])
        if live:
            # 联网拿到的是"当前挂牌价"，未来日期的季节差异再叠系数
            adjusted = live["price"] * factor
            item["cost"] = round(adjusted, 2)
            remark = f"联网实时价￥{live['price']:g}：{live['note']}"
            if factor != 1.0:
                remark += f"；按{label}系数×{factor}调整"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
        elif factor != 1.0:
            item["cost"] = round(base * factor, 2)
            remark = f"{label}估算：系数×{factor}（知识库基准价￥{base:g}）"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark

    hotel_total = 0.0
    attraction_total = 0.0
    for plan in raw_plans:
        items = []
        for item in plan["items"]:
            poi = lookup.get(item.get("poi_name"))
            if poi:
                if item.get("latitude") is None and poi.get("latitude") is not None:
                    item["latitude"] = float(poi["latitude"])
                if item.get("longitude") is None and poi.get("longitude") is not None:
                    item["longitude"] = float(poi["longitude"])
                if not item.get("poi_id"):
                    item["poi_id"] = str(poi.get("id") or "")
                if not item.get("cost") and poi.get("ticket_price") is not None:
                    item["cost"] = float(poi["ticket_price"])
                if item.get("open_time") is None:
                    item["open_time"] = poi.get("open_time")
            if item.get("item_type") == "hotel":
                price_hotel(item)
                hotel_total += float(item.get("cost") or 0)
            elif item.get("item_type") == "attraction":
                attraction_total += float(item.get("cost") or 0)
            items.append(TripItem(**item))
        daily_plans.append(DailyPlan(day_no=plan["day_no"], note=plan.get("note"), items=items))

    # 预算只把 LLM/候选池预算当作初始估计，最终按本次实际选中的 POI 重算，
    # 避免“候选平均票价”与用户看到的具体景点不一致。
    budget_estimate = dict(budget_source or {})
    budget_estimate["门票"] = round(attraction_total * req.persons, 2)
    meal_price = float((state.get("consumption") or {}).get("meal_price", 60.0))
    transport_price = float((state.get("consumption") or {}).get("transport_price", 35.0))
    budget_estimate["餐饮"] = round(meal_price * 2 * len(daily_plans) * req.persons, 2)
    budget_estimate["交通"] = round(transport_price * len(daily_plans) * req.persons, 2)
    rooms = ceil(max(req.persons, 1) / 2)
    if hotel_total > 0:
        budget_estimate["酒店"] = round(hotel_total * rooms, 2)
    sources = [v["note"] for v in live_cache.values() if v]
    price_note = (
        "酒店价格来源：" + "；".join(dict.fromkeys(sources))
        if sources else
        (f"酒店为{label}估算（系数×{factor}），未获取到联网实时价" if factor != 1.0 else None)
    )

    # 最终校验必须针对已经补齐坐标、价格、营业时间和图片字段的输出，
    # 防止格式化阶段的字段变化绕过反思层。
    final_raw_plans = [
        {
            "day_no": plan.day_no,
            "items": [item.model_dump() for item in plan.items],
        }
        for plan in daily_plans
    ]
    final_issues, final_log = validate_plans(final_raw_plans)
    validation_log = list(state.get("validation_log") or [])
    validation_log.extend(final_log)
    degraded_reasons: list[str] = []
    if state.get("degraded_reason"):
        degraded_reasons.append(state["degraded_reason"] or "")
    if quality_fallback_reason:
        degraded_reasons.append(quality_fallback_reason)
    if final_issues:
        validation_log.extend(final_issues)
        degraded_reasons.append("达到重试上限后仍存在行程约束问题")
    degraded_reasons = list(dict.fromkeys(reason for reason in degraded_reasons if reason))
    status = "degraded" if degraded_reasons else "success"
    record_event("decision", "run_status", metadata={
        "status": status,
        "final_issue_count": len(final_issues),
    })
    result = GenerateResponse(
        city=req.city,
        days=req.days,
        title=f"{req.city}{req.days}日游",
        daily_plans=daily_plans,
        budget_estimate=budget_estimate,
        validation_log=validation_log,
        price_note=price_note,
        status=status,
        status_reason="；".join(degraded_reasons) or None,
    )
    return {"result": result}


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_requirements)
    graph.add_node("search", search_pois)
    graph.add_node("generate", generate_itinerary)
    graph.add_node("reflect", reflect)
    graph.add_node("format", format_output)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "search")
    graph.add_edge("search", "generate")
    graph.add_edge("generate", "reflect")
    graph.add_conditional_edges("reflect", needs_fix, {"fix": "generate", "pass": "format"})
    graph.add_edge("format", END)
    return graph


agent_graph = build_graph().compile()


def run_generate(req: GenerateRequest) -> GenerateResponse:
    state: AgentState = {
        "request": req,
        "requirements": {},
        "candidates": [],
        "foods": [],
        "hotels": [],
        "consumption": None,
        "daily_plans": [],
        "budget_estimate": {},
        "attempts": 0,
        "fix_count": 0,
        "error": None,
        "feedback": "",
        "validation_issues": [],
        "validation_log": [],
        "degraded_reason": None,
    }
    result = agent_graph.invoke(state)
    return result["result"]


def run_adjust(req: AdjustRequest) -> AdjustResponse:
    if req.item_type == "attraction":
        candidates = search_attractions(req.city, req.preferences)
    else:
        candidates = search_foods(req.city)
    seen = set()
    recommendations: list[PoiOption] = []
    for poi in candidates:
        name = poi.get("name")
        if not name or name == req.poi_name or name in seen:
            continue
        seen.add(name)
        recommendations.append(PoiOption(**poi))
        if len(recommendations) >= 5:
            break
    return AdjustResponse(city=req.city, current=req.poi_name, recommendations=recommendations)
