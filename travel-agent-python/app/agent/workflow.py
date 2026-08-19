import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent import tools
from app.agent.generators import fallback_generate, llm_generate
from app.agent.reflect import build_feedback, validate_plans
from app.agent.tools import search_attractions, search_foods
from app.common.config import settings
from app.schemas.trip import AdjustRequest, AdjustResponse, DailyPlan, GenerateRequest, GenerateResponse, PoiOption, TripItem

logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = 2


class AgentState(TypedDict):
    request: GenerateRequest
    requirements: dict
    candidates: list[dict]
    foods: list[dict]
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
    consumption = tools.get_consumption(req.city)
    return {"candidates": candidates, "foods": foods, "consumption": consumption}


def generate_itinerary(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    attempts = state.get("attempts", 0)
    feedback = state.get("feedback", "")
    if settings.llm_api_key and attempts < MAX_FIX_ATTEMPTS:
        try:
            plans, budget = llm_generate(
                req.city, req.days, req.persons, req.preferences,
                state["candidates"], state["foods"], state["consumption"],
                feedback=feedback,
            )
            return {"daily_plans": plans, "budget_estimate": budget, "error": None}
        except Exception as e:
            logger.warning("llm generate failed (attempt %s): %s", attempts + 1, e)
            return {"error": str(e), "attempts": attempts + 1}
    plans, budget = fallback_generate(req.city, req.days, req.persons, req.preferences)
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
    daily_plans = [
        DailyPlan(
            day_no=plan["day_no"],
            note=plan.get("note"),
            items=[TripItem(**item) for item in plan["items"]],
        )
        for plan in state["daily_plans"]
    ]
    result = GenerateResponse(
        city=req.city,
        days=req.days,
        title=f"{req.city}{req.days}日游",
        daily_plans=daily_plans,
        budget_estimate=state["budget_estimate"],
        validation_log=state.get("validation_log") or [],
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