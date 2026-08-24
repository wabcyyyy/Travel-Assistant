import logging
from datetime import date
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent import tools
from app.agent.generators import fallback_generate, llm_generate
from app.agent.reflect import build_feedback, validate_plans
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


def search_pois(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    candidates = tools.search_attractions(req.city, req.preferences)
    foods = tools.search_foods(req.city)
    hotels = search_hotels(req.city)
    consumption = tools.get_consumption(req.city)
    return {"candidates": candidates, "foods": foods, "hotels": hotels,
            "consumption": consumption}


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
                feedback=feedback, hotels=state.get("hotels"),
            )
            return {"daily_plans": plans, "budget_estimate": budget, "error": None}
        except Exception as e:
            logger.warning("llm generate failed (attempt %s): %s", attempts + 1, e)
            if attempts + 1 >= MAX_FIX_ATTEMPTS:
                logger.info("LLM 连续失败，降级为确定性兜底生成")
                plans, budget = fallback_generate(req.city, req.days, req.persons,
                                                  req.preferences, state.get("hotels"))
                return {"daily_plans": plans, "budget_estimate": budget, "error": None}
            return {"error": str(e), "attempts": attempts + 1}
    plans, budget = fallback_generate(req.city, req.days, req.persons,
                                      req.preferences, state.get("hotels"))
    return {"daily_plans": plans, "budget_estimate": budget, "error": None}


def reflect(state: AgentState) -> dict:
    plans = state.get("daily_plans") or []
    issues: list[str] = []
    log: list[str] = []
    if state.get("error"):
        log.append("生成失败，跳过校验")
        return {"validation_issues": issues, "validation_log": log, "fix_count": state.get("fix_count", 0)}
    if plans:
        issues, log = validate_plans(plans)
    return {
        "validation_issues": issues,
        "validation_log": log,
        "feedback": build_feedback(issues),
        "fix_count": state.get("fix_count", 0) + (1 if issues else 0),
    }


def needs_fix(state: AgentState) -> str:
    if state.get("error") and state.get("attempts", 0) < MAX_FIX_ATTEMPTS:
        return "fix"
    if state.get("validation_issues") and state.get("fix_count", 0) <= MAX_FIX_ATTEMPTS:
        return "fix"
    return "pass"


def format_output(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    lookup: dict[str, dict] = {}
    for poi in (state.get("candidates") or []) + (state.get("foods") or []):
        name = poi.get("name")
        if name and name not in lookup:
            lookup[name] = poi
    daily_plans = []
    trip_date: date | None = None
    if req.start_date:
        try:
            trip_date = date.fromisoformat(req.start_date)
        except ValueError:
            trip_date = None
    factor = season_factor(trip_date)
    label = season_label(trip_date)
    for plan in state["daily_plans"]:
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
                if item.get("cost") is None and poi.get("ticket_price") is not None:
                    item["cost"] = float(poi["ticket_price"])
            if item.get("item_type") == "hotel" and factor != 1.0 and item.get("cost"):
                base = float(item["cost"])
                item["cost"] = round(base * factor, 2)
                remark = f"{label}价格系数×{factor}（基准价￥{base:g}）"
                item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
            items.append(TripItem(**item))
        daily_plans.append(DailyPlan(day_no=plan["day_no"], note=plan.get("note"), items=items))
    budget_estimate = dict(state["budget_estimate"] or {})
    if factor != 1.0 and budget_estimate.get("酒店"):
        budget_estimate["酒店"] = round(float(budget_estimate["酒店"]) * factor, 2)
    price_note = f"酒店已按{label}系数×{factor}调整（基于出行日期 {req.start_date}）" \
        if factor != 1.0 else None
    result = GenerateResponse(
        city=req.city,
        days=req.days,
        title=f"{req.city}{req.days}日游",
        daily_plans=daily_plans,
        budget_estimate=budget_estimate,
        validation_log=state.get("validation_log") or [],
        price_note=price_note,
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