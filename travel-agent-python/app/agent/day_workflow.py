"""生产逐日生成的 Agent 闭环。

Java 侧按天调用 generate-day，但每一天都必须经过：

    生成 -> 确定性反思 -> LLM 修复 -> 确定性 fallback -> 输出

单次生成逻辑保留在 day_stream，LangGraph 只负责状态、分支和重试，保证
逐日生成与整段生成拥有一致的 Agent 编排语义。
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent.day_stream import _generate_day_once
from app.agent.reflect import build_feedback, validate_plans
from app.agent.trace import record_event, traced
from app.schemas.trip import DailyPlan, GenerateDayRequest


MAX_DAY_ATTEMPTS = 2


class DayAgentState(TypedDict):
    request: GenerateDayRequest
    plan: DailyPlan | None
    source: str
    attempts: int
    force_fallback: bool
    error: str | None
    feedback: str
    validation_issues: list[str]
    validation_log: list[str]


@traced("node", "day.generate")
def generate_day(state: DayAgentState) -> dict:
    request = state["request"]
    feedback = state.get("feedback", "")
    if feedback and feedback != request.feedback:
        request = request.model_copy(update={"feedback": feedback})
    try:
        plan, source = _generate_day_once(
            request, force_fallback=state.get("force_fallback", False)
        )
        return {
            "request": request,
            "plan": plan,
            "source": source,
            "attempts": state.get("attempts", 0) + 1,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - 路由节点统一处理失败
        return {
            "request": request,
            "plan": None,
            "source": "error",
            "attempts": state.get("attempts", 0) + 1,
            "error": str(exc),
        }


@traced("node", "day.reflect")
def reflect_day(state: DayAgentState) -> dict:
    plan = state.get("plan")
    if plan is None:
        return {
            "validation_issues": [state.get("error") or "单日行程生成失败"],
            "validation_log": ["单日生成失败，准备重试或确定性兜底"],
            "feedback": state.get("error") or "单日行程生成失败，请重新生成",
        }
    raw = plan.model_dump() if hasattr(plan, "model_dump") else plan
    issues, log = validate_plans([raw])
    record_event("decision", "day.reflect_result", metadata={
        "issue_count": len(issues), "needs_fix": bool(issues),
    })
    return {
        "validation_issues": issues,
        "validation_log": log,
        "feedback": build_feedback(issues),
    }


def route_after_reflect(state: DayAgentState) -> str:
    if not state.get("validation_issues"):
        record_event("route", "finish", metadata={"reason": "validation_pass"})
        return "finish"
    if state.get("attempts", 0) < MAX_DAY_ATTEMPTS and not state.get("force_fallback"):
        record_event("route", "retry", metadata={"reason": "validation_issue"})
        return "retry"
    if not state.get("force_fallback"):
        record_event("route", "fallback", metadata={"reason": "retry_exhausted"})
        return "fallback"
    record_event("route", "finish", metadata={"reason": "fallback_result"})
    return "finish"


@traced("node", "day.retry")
def prepare_retry(state: DayAgentState) -> dict:
    return {"force_fallback": False}


@traced("node", "day.fallback")
def prepare_fallback(state: DayAgentState) -> dict:
    return {"force_fallback": True, "feedback": ""}


def build_day_graph():
    graph = StateGraph(DayAgentState)
    graph.add_node("generate", generate_day)
    graph.add_node("reflect", reflect_day)
    graph.add_node("retry", prepare_retry)
    graph.add_node("fallback", prepare_fallback)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "reflect")
    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {"finish": END, "retry": "retry", "fallback": "fallback"},
    )
    graph.add_edge("retry", "generate")
    graph.add_edge("fallback", "generate")
    return graph.compile()


day_agent_graph = build_day_graph()


def run_day_agent(req: GenerateDayRequest) -> DailyPlan:
    state: DayAgentState = {
        "request": req,
        "plan": None,
        "source": "",
        "attempts": 0,
        "force_fallback": False,
        "error": None,
        "feedback": req.feedback,
        "validation_issues": [],
        "validation_log": [],
    }
    result = day_agent_graph.invoke(state)
    if result.get("plan") is None:
        raise ValueError(result.get("error") or "单日行程生成失败")
    return result["plan"]
