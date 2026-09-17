"""统一图（整段）的节点实现（G-2.4 自 workflow 拆出）。

节点清单与职责：parse_requirements（解析）→ research_pois（研究）→
generate_itinerary（生成/重试编排）→ reflect（校验）→ needs_fix（路由）→
research_refill（补查）→ format（装配见 formatting.assembly）。

编排图在 trip_graph.unified_agent_graph（整段/逐日共用）；本模块只提供节点
函数，`workflow.py` 作为薄门面导出它们（trip_graph 经 `workflow.X` 调用，
测试据此 monkeypatch——**勿改访问路径**）。

依赖：open_plans、suggestions、formatting.assembly、generators 下层面。
"""

import logging

from app.agent import research
from app.agent.formatting.assembly import (
    format_output as format_output,  # 门面转发（trip_graph 经 workflow.format_output 调用）
)
from app.agent.formatting.assembly import (
    generation_attempt_limit,
)
from app.agent.generation_core import MAX_GENERATION_ATTEMPTS, MAX_REFILLS
from app.agent.graph_state import AgentState
from app.agent.observability import metrics
from app.agent.open_plans import draft_state, generate_open_plans
from app.agent.reflect import build_feedback, validate_plans
from app.agent.research.evidence import ResearchDomain
from app.agent.route_matrix import route_matrix_for_plans
from app.agent.trace import record_event, traced
from app.common.addons import addons
from app.common.config import settings
from app.schemas.trip import GenerateRequest

logger = logging.getLogger(__name__)


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


@traced("node", "research")
def research_pois(state: AgentState) -> dict:
    """研究阶段：Supervisor 并行派发酒店/景点/美食研究 Agent，整合证据上下文。

    多 Agent 化后，检索不再是单一工具调用，而是三个领域研究 Agent 各自产出
    证据包（EvidencePack），由 Supervisor 并行执行并整合回旧上下文契约
    {candidates, foods, hotels, consumption}；research_report 随状态流转，
    由 format_output 写入 schedule_report 供观测与演示。
    """
    req: GenerateRequest = state["request"]
    context = research.run_research_context(req)
    return {
        "candidates": context["candidates"],
        "foods": context["foods"],
        "hotels": context["hotels"],
        "consumption": context["consumption"],
        "weather": context.get("weather"),
        "research_report": context["research_report"],
    }


@traced("node", "generate")
def generate_itinerary(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    attempts = state.get("attempts", 0)
    feedback = state.get("feedback", "")
    schedule_report: dict = {}

    # LLM-only 生成：开放模式（LLM 知识 + 权威参考资料注入 + 高德落坐标）
    # 是唯一的行程内容来源；知识库只作为证据引导与事实校准，绝不直接
    # 拼装行程。开放失败时记 error 走 fix 循环重试一次（与 days 无关），
    # 重试耗尽或未配置 LLM 则返回结构化待研究草案——如实降级，不冒充生成结果。
    if settings.llm_api_key and attempts < MAX_GENERATION_ATTEMPTS:
        open_state = generate_open_plans(
            req,
            feedback,
            state.get("hotels"),
            candidates=state.get("candidates"),
            foods=state.get("foods"),
            weather=state.get("weather"),
        )
        if open_state is not None:
            return open_state
        if attempts + 1 >= MAX_GENERATION_ATTEMPTS:
            # 重试耗尽：草案必须可达（多日行程此前因 attempts 预算与 days
            # 挂钩而直接落到空 plans，草案分支成为死代码）。
            return draft_state(req, "开放研究重试耗尽，已返回待研究草案", schedule_report)
        record_event("route", "retry", metadata={"reason": "open_research_failed"})
        return {"error": "开放研究失败", "attempts": attempts + 1, "schedule_report": schedule_report}

    reason = "未配置 LLM，无法生成行程内容" if not settings.llm_api_key else "开放研究重试耗尽，已返回待研究草案"
    return draft_state(req, reason, schedule_report)


@traced("node", "reflect")
def reflect(state: AgentState) -> dict:
    plans = state.get("daily_plans") or []
    issues: list[str] = []
    log: list[str] = []
    if state.get("error"):
        log.append("生成失败，跳过校验")
        return {"validation_issues": issues, "validation_log": log, "fix_count": state.get("fix_count", 0)}
    if plans:
        route_matrix = None
        if settings.route_service_enabled and addons.is_enabled("route_service"):
            route_matrix = route_matrix_for_plans(plans)
        req = state.get("request")
        budget = getattr(req, "budget", None) if req is not None else None
        persons = getattr(req, "persons", 1) or 1 if req is not None else 1
        issues, log = validate_plans(
            plans,
            route_matrix=route_matrix,
            budget=budget if settings.budget_hard_constraint else None,
            persons=persons,
            consumption=state.get("consumption"),
            budget_overage_ratio=settings.budget_overage_ratio,
        )
    record_event(
        "decision",
        "reflect_result",
        metadata={
            "issue_count": len(issues),
            "needs_fix": bool(issues),
        },
    )
    return {
        "validation_issues": issues,
        "validation_log": log,
        "feedback": build_feedback(issues),
        "fix_count": state.get("fix_count", 0) + (1 if issues else 0),
    }


def needs_fix(state: AgentState) -> str:
    attempt_limit = generation_attempt_limit(state)
    # 生成失败的重试次数与 days 无关（定稿口径：失败→重试一次→草案）；
    # 校验修复次数才按 attempt_limit 收窄。
    if state.get("error") and state.get("attempts", 0) < MAX_GENERATION_ATTEMPTS:
        route = "fix"
        record_event("route", route, metadata={"reason": "generation_error"})
        return route
    if state.get("validation_issues") and state.get("fix_count", 0) <= attempt_limit:
        # Supervisor 缺口补查优先于整体重生成：仅当校验问题属于"证据型缺口"
        # （如未安排任何景点）且补查预算未耗尽时，重派发对应研究 Agent。
        if _refillable(state) and state.get("refill_count", 0) < MAX_REFILLS:
            route = "refill"
            record_event("route", route, metadata={"reason": "evidence_gap"})
            return route
        route = "fix"
        record_event("route", route, metadata={"reason": "validation_issue"})
        return route
    record_event("route", "pass", metadata={"reason": "validation_pass"})
    return "pass"


def _refill_domain(issues: list[str]) -> ResearchDomain | None:
    """校验问题 → 证据缺口域：目前只有"未安排任何景点"是明确的证据型缺口。"""
    if any("未安排任何景点" in issue for issue in issues or []):
        return "attraction"
    return None


def _refillable(state: AgentState) -> bool:
    return _refill_domain(state.get("validation_issues") or []) is not None


@traced("node", "refill_research")
def research_refill(state: AgentState) -> dict:
    """Supervisor 缺口补查：重派发缺口域研究 Agent，合并补查证据后重新生成。

    只补证据不生成内容（LLM-only）：补查结果并入 candidates，随
    research_report 记录补查域统计，供观测与演示。
    """
    domain = _refill_domain(state.get("validation_issues") or [])
    if domain is None:
        return {"refill_count": state.get("refill_count", 0)}
    req: GenerateRequest = state["request"]
    pack = research.run_refill(domain, req)
    candidates = research.merge_candidates(state.get("candidates") or [], pack.items)
    research_report = dict(state.get("research_report") or {})
    agents = dict(research_report.get("agents") or {})
    agents[domain] = {**pack.to_dict(), "refilled": True}
    research_report["agents"] = agents
    record_event(
        "decision", "research_refill", metadata={"domain": domain, "count": len(pack.items), "rounds": pack.rounds}
    )
    metrics.record_research_refill()
    return {
        "candidates": candidates,
        "research_report": research_report,
        "refill_count": state.get("refill_count", 0) + 1,
    }
