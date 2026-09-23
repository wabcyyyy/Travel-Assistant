"""统一生成图：整段行程（trip）与单日（day）共用一张 LangGraph StateGraph。

历史上 workflow 与 day_workflow 各持一张图，现已合并为 **一张**
``unified_agent_graph``，用 ``mode`` 字段分流（workflow 提供整段节点函数、
day_stream 提供逐日节点函数）：

```text
dispatch ──mode=day──► day_generate ⇄ day.reflect/retry/fallback ──► END
        └─mode=trip─► parse → research → generate → reflect ⇄ fix/refill → format ──► END
```

事实层（Prompt/坐标落地）仍在 ``day_stream``；产品口径在 ``generation_core``。
``workflow.run_generate`` / ``day_workflow.run_day_agent`` 变为本图的薄门面，
HTTP 契约不变。测试可 monkeypatch ``day_workflow.generate_day_once``
（day 节点经该模块属性调用，保证补丁生效）。
"""

from __future__ import annotations

import logging
from typing import cast

from langgraph.graph import END, StateGraph

from app.agent.generation.content.reflect import build_feedback, validate_plans
from app.agent.generation.rules.generation_core import MAX_DAY_ATTEMPTS
from app.agent.research.agent_state import UnifiedAgentState
from app.agent.runtime.trace import record_event, traced
from app.schemas.trip import DailyPlan, GenerateDayRequest, GenerateRequest, GenerateResponse

logger = logging.getLogger(__name__)

MODE_DAY = "day"
MODE_TRIP = "trip"


def _is_day(state: UnifiedAgentState) -> bool:
    return state.mode == MODE_DAY


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def dispatch(state: UnifiedAgentState) -> dict:
    """入口：仅规范化 mode，便于条件边分流。"""
    mode = state.mode or MODE_TRIP
    return {"mode": mode}


def route_entry(state: UnifiedAgentState) -> str:
    return "day_generate" if _is_day(state) else "parse"


# ---------------------------------------------------------------------------
# day 分支
# ---------------------------------------------------------------------------


@traced("node", "day.generate")
def day_generate(state: UnifiedAgentState) -> dict:
    # 经 day_workflow 模块属性调用，保证 tests monkeypatch 生效
    from app.agent.generation.orchestration import day_workflow as dw

    request: GenerateDayRequest = cast("GenerateDayRequest", state.day_request)
    feedback = state.feedback
    if feedback and feedback != request.feedback:
        request = request.model_copy(update={"feedback": feedback})
    try:
        plan, source = dw.generate_day_once(request, force_fallback=state.force_fallback)
        return {
            "day_request": request,
            "plan": plan,
            "source": source,
            "attempts": state.attempts + 1,
            "error": None,
        }
    except Exception as exc:
        return {
            "day_request": request,
            "plan": None,
            "source": "error",
            "attempts": state.attempts + 1,
            "error": str(exc),
        }


@traced("node", "day.reflect")
def day_reflect(state: UnifiedAgentState) -> dict:
    from app.common.config import settings as _settings

    plan = state.plan
    if plan is None:
        return {
            "validation_issues": [state.error or "单日行程生成失败"],
            "validation_log": ["单日生成失败，准备重试或最后一次无反馈重试"],
            "feedback": state.error or "单日行程生成失败，请重新生成",
        }
    raw = plan.model_dump()
    request = state.day_request
    budget = getattr(request, "budget", None) if request is not None else None
    persons = getattr(request, "persons", 1) or 1 if request is not None else 1
    issues, log = validate_plans(
        [raw],
        budget=budget if _settings.budget_hard_constraint else None,
        persons=persons,
        budget_overage_ratio=_settings.budget_overage_ratio,
    )
    record_event(
        "decision",
        "day.reflect_result",
        metadata={
            "issue_count": len(issues),
            "needs_fix": bool(issues),
        },
    )
    return {
        "validation_issues": issues,
        "validation_log": log,
        "feedback": build_feedback(issues),
    }


def day_route_after_reflect(state: UnifiedAgentState) -> str:
    if not state.validation_issues:
        record_event("route", "finish", metadata={"reason": "validation_pass"})
        return "finish"
    request = state.day_request
    max_attempts = 1 if request is not None and (request.days or 1) > 1 else MAX_DAY_ATTEMPTS
    if state.attempts < max_attempts and not state.force_fallback:
        record_event("route", "retry", metadata={"reason": "validation_issue"})
        return "retry"
    if not state.force_fallback:
        record_event("route", "fallback", metadata={"reason": "retry_exhausted"})
        return "fallback"
    record_event("route", "finish", metadata={"reason": "fallback_result"})
    return "finish"


def day_prepare_retry(state: UnifiedAgentState) -> dict:
    return {"force_fallback": False}


def day_prepare_fallback(state: UnifiedAgentState) -> dict:
    return {"force_fallback": True, "feedback": ""}


# ---------------------------------------------------------------------------
# trip 分支：节点实现委托 workflow 模块（延迟导入避免环）
# ---------------------------------------------------------------------------


def _wf():
    from app.agent.generation.orchestration import workflow as wf

    return wf


@traced("node", "parse")
def parse(state: UnifiedAgentState) -> dict:
    return _wf().parse_requirements(state)


@traced("node", "research")
def research(state: UnifiedAgentState) -> dict:
    return _wf().research_pois(state)


@traced("node", "generate")
def trip_generate(state: UnifiedAgentState) -> dict:
    return _wf().generate_itinerary(state)


@traced("node", "reflect")
def trip_reflect(state: UnifiedAgentState) -> dict:
    return _wf().reflect(state)


@traced("node", "refill_research")
def trip_refill(state: UnifiedAgentState) -> dict:
    return _wf().research_refill(state)


@traced("node", "format")
def trip_format(state: UnifiedAgentState) -> dict:
    return _wf().format_output(state)


def trip_needs_fix(state: UnifiedAgentState) -> str:
    return _wf().needs_fix(state)


# ---------------------------------------------------------------------------
# 统一图
# ---------------------------------------------------------------------------


def build_unified_graph() -> StateGraph:
    graph = StateGraph(UnifiedAgentState)

    graph.add_node("dispatch", dispatch)

    # day
    graph.add_node("day_generate", day_generate)
    graph.add_node("day.reflect", day_reflect)
    graph.add_node("day.retry", day_prepare_retry)
    graph.add_node("day.fallback", day_prepare_fallback)

    # trip
    graph.add_node("parse", parse)
    graph.add_node("research", research)
    graph.add_node("generate", trip_generate)
    graph.add_node("reflect", trip_reflect)
    graph.add_node("refill_research", trip_refill)
    graph.add_node("format", trip_format)

    graph.set_entry_point("dispatch")
    graph.add_conditional_edges(
        "dispatch",
        route_entry,
        {
            "day_generate": "day_generate",
            "parse": "parse",
        },
    )

    # day edges
    graph.add_edge("day_generate", "day.reflect")
    graph.add_conditional_edges(
        "day.reflect",
        day_route_after_reflect,
        {
            "finish": END,
            "retry": "day.retry",
            "fallback": "day.fallback",
        },
    )
    graph.add_edge("day.retry", "day_generate")
    graph.add_edge("day.fallback", "day_generate")

    # trip edges
    graph.add_edge("parse", "research")
    graph.add_edge("research", "generate")
    graph.add_edge("generate", "reflect")
    graph.add_conditional_edges(
        "reflect",
        trip_needs_fix,
        {
            "fix": "generate",
            "refill": "refill_research",
            "pass": "format",
        },
    )
    graph.add_edge("refill_research", "generate")
    graph.add_edge("format", END)

    return graph


unified_agent_graph = build_unified_graph().compile()


def empty_trip_state(req: GenerateRequest) -> dict:
    return {
        "mode": MODE_TRIP,
        "request": req,
        "requirements": {},
        "candidates": [],
        "foods": [],
        "hotels": [],
        "consumption": None,
        "weather": None,
        "daily_plans": [],
        "budget_estimate": {},
        "attempts": 0,
        "fix_count": 0,
        "error": None,
        "feedback": "",
        "validation_issues": [],
        "validation_log": [],
        "degraded_reason": None,
        "schedule_report": {},
        "critic_report": {},
        "research_report": {},
        "refill_count": 0,
    }


def empty_day_state(req: GenerateDayRequest) -> dict:
    return {
        "mode": MODE_DAY,
        "day_request": req,
        "plan": None,
        "source": "",
        "attempts": 0,
        "force_fallback": False,
        "error": None,
        "feedback": req.feedback,
        "validation_issues": [],
        "validation_log": [],
    }


def run_trip(req: GenerateRequest) -> GenerateResponse:
    result = unified_agent_graph.invoke(empty_trip_state(req))
    return result["result"]


def run_day(req: GenerateDayRequest) -> DailyPlan:
    result = unified_agent_graph.invoke(empty_day_state(req))
    if result.get("plan") is None:
        raise ValueError(result.get("error") or "单日行程生成失败")
    return result["plan"]
