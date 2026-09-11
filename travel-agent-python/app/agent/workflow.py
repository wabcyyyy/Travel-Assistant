"""初次行程生成的工作流编排（LangGraph：生成 → 校验 → 修复 循环）。

职责：
- run_generate：用 StateGraph 串起 parse → search → generate → reflect → format；
- generate_itinerary：LLM-only 生成——开放模式（LLM 知识 + 权威参考资料注入 +
  高德落坐标）是唯一行程内容来源，失败走 fix 循环重试，耗尽返回待研究草案；
- reflect：调用 reflect.validate_plans 校验并产出修复反馈；
- format_output：补水坐标/价格（联网实时价或季节系数）并组装 GenerateResponse；
- run_adjust：为“替换某景点”提供候选。

实现要点：
- 知识库永远只是补充证据：检索结果以编号参考资料注入 Prompt，命中项落地
  权威字段与溯源，不直接用知识库候选拼装行程（LLM 不可用时如实返回草案）；
- 基于 langgraph 的状态图，reflect 不通过则带 feedback 回到 generate 重试；
- 与 chat_draft 的“对话编辑”链路不同，本模块负责从零生成首版行程；
- 酒店定价链：联网实时价 → 知识库基准价 × 季节系数（season_factor）估算。

产品口径以 generation_core 为唯一真相源。

依赖：day_stream、generators、reflect、tools、pricing、season、schemas.trip、generation_core。
"""

import logging
from datetime import date, datetime, timezone
from math import ceil
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent import research, tools
from app.agent import poi_repository
from app.agent.generation_core import (
    MAX_FIX_ATTEMPTS,
    MAX_GENERATION_ATTEMPTS,
    MAX_REFILLS,
    count_hotel_nights_in_budget,
    draft_day_plans,
    sanitize_itinerary_items,
    spread_hotels,
    stay_nights,
)
from app.agent.generators import (
    ReferencePool,
    _has_valid_coords,
    build_suggestions,
)
from app.agent.day_stream import _amap_ground, _has_coord, _llm_open_day, _llm_open_trip
from app.agent.observability import metrics
from app.agent.pricing import query_live_price
from app.agent.reflect import build_feedback, validate_plans
from app.agent.route_service import get_route_matrix
from app.agent.tool_registry import registry
from app.agent.critic import critique_plans
from app.agent.trace import record_event, traced
from app.agent.tools import search_attractions, search_foods
from app.common.config import settings
from app.common.season import season_factor, season_label
from app.schemas.trip import (
    AdjustRequest, AdjustResponse, DailyPlan, FactEvidence, GenerateDayRequest,
    GenerateRequest, GenerateResponse, PoiOption, QualityIssue, QualityReport,
    SourceRecord, Suggestion, TripItem,
)

logger = logging.getLogger(__name__)

# 产品口径与常量见 generation_core；此处保留兼容别名。
_spread_hotels = spread_hotels


def _generation_attempt_limit(state: dict) -> int:
    request = state.get("request")
    return 1 if request is not None and request.days > 1 else MAX_FIX_ATTEMPTS


def _route_matrix_for_plans(plans: list[dict]) -> dict:
    """只为同一天的相邻候选构建矩阵，避免跨日无效路线调用。

    逐日调用会让工具预算按整个 run 累计（reflect N 天 + format N 天 = 2N 次），
    因此 `get_route_matrix` 的 max_calls 必须覆盖最长行程；这里同时跳过空日，
    减少无意义消耗。同日重复查询由 RouteService 的进程内缓存吸收。
    """
    matrix: dict = {}
    for plan in plans:
        active = [
            item for item in plan.get("items") or []
            if item.get("item_type") in ("attraction", "food")
        ]
        if len(active) < 2:
            continue
        matrix.update(registry.invoke("get_route_matrix", {
            "items": active, "mode": settings.route_mode,
        }))
    return matrix


def _draft_state(req: GenerateRequest, reason: str,
                 schedule_report: dict | None = None) -> dict:
    """结构化"待研究"草案：如实标注降级，不冒充生成结果。"""
    plans = draft_day_plans(req.city, req.days, reason)
    report = dict(schedule_report or {})
    report["destination_status"] = "draft_only"
    report["research_mode"] = "open"
    return {
        "daily_plans": plans,
        "budget_estimate": {},
        "error": None,
        "schedule_report": report,
        "degraded_reason": reason,
    }


# 摊铺逻辑见 generation_core.spread_hotels（兼容旧内部名）
_spread_hotels = spread_hotels


def _fill_zero_costs(plans: list[dict], lookup: dict[str, dict]) -> int:
    """餐饮/酒店 cost=0 时用知识库权威价覆盖（模型常把未知价写成 0）。

    注意：RAG/知识库中的 ticket_price=0 与 None 含义不同——None 表示未知，
    0 对景点表示免费；对 food/hotel 的 0 一律视为未知并回落 avg_cost。
    """
    filled = 0
    for plan in plans:
        for item in plan.get("items") or []:
            if item.get("item_type") not in ("food", "hotel"):
                continue
            try:
                cost = float(item.get("cost")) if item.get("cost") is not None else None
            except (TypeError, ValueError):
                cost = None
            if cost not in (0, 0.0, None):
                continue
            name = str(item.get("poi_name") or "").strip()
            poi = lookup.get(name) or {}
            price = poi.get("ticket_price")
            if price is None or price == 0:
                price = poi.get("avg_cost")
            if price is None or price == 0:
                continue
            try:
                item["cost"] = float(price)
                filled += 1
            except (TypeError, ValueError):
                continue
    return filled


def _floor_suggestions(raw: list[dict], extra_pool: list[dict]) -> list[dict]:
    """备选池数量地板：主类尽量 ≥4、每类 ≤20；shopping=商城/名店。

    酒店/体验/美食也参与地板；体验类从 extra_pool 的 activity 或景点映射补充。
    """
    main_cats = ("attraction", "activity", "food", "hotel", "shopping")
    max_per = 20
    min_per = 4

    def _norm_name(name: str) -> str:
        return "".join(str(name or "").lower().split())

    by_cat: dict[str, list[dict]] = {}
    used_names: set[str] = set()
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        cat = str(s.get("category") or "attraction")
        if cat == "souvenir":
            cat = "shopping"
        name = str(s.get("name") or s.get("poi_name") or "").strip()
        key = _norm_name(name)
        if name and key in used_names:
            continue
        if name:
            used_names.add(key)
        by_cat.setdefault(cat, []).append({**s, "category": cat})

    def _from_poi(poi: dict, cat: str) -> dict:
        name = str(poi.get("name") or "").strip()
        price = poi.get("ticket_price")
        if price is None or price == 0:
            price = poi.get("avg_cost")
        return {
            "name": name,
            "category": cat,
            "intro": (poi.get("description") or "")[:80] or None,
            "latitude": poi.get("latitude"),
            "longitude": poi.get("longitude"),
            "estimated_cost": float(price or 0),
            "source": poi.get("source"),
            "poi_id": str(poi.get("id") or "") or None,
        }

    for cat in main_cats:
        if len(by_cat.get(cat) or []) >= min_per:
            continue
        need = min_per - len(by_cat.get(cat) or [])
        pool_cat = cat
        if cat == "activity":
            pool_cat = "activity"
        for poi in extra_pool or []:
            if need <= 0:
                break
            if str(poi.get("category") or "") != pool_cat:
                continue
            name = str(poi.get("name") or "").strip()
            key = _norm_name(name)
            if not name or key in used_names:
                continue
            by_cat.setdefault(cat, []).append(_from_poi(poi, cat))
            used_names.add(key)
            need -= 1
        # 体验类知识库常为空：允许用未入程的高分景点/付费体验顶上
        if cat == "activity" and need > 0:
            for poi in extra_pool or []:
                if need <= 0:
                    break
                if str(poi.get("category") or "") != "attraction":
                    continue
                name = str(poi.get("name") or "").strip()
                key = _norm_name(name)
                if not name or key in used_names:
                    continue
                tags = str(poi.get("tags") or "")
                try:
                    rating = float(poi.get("rating") or 0)
                except (TypeError, ValueError):
                    rating = 0
                # 海外开放模式常无评分：无 rating 时只看标签，避免 activity 永远为 0
                if poi.get("rating") is not None and rating < 4.3 and not any(
                        x in tags for x in ("体验", "演出", "潜水", "SPA", "spa", "冲浪", "剧场", "美术馆", "观景")):
                    continue
                by_cat.setdefault(cat, []).append(_from_poi(poi, "activity"))
                used_names.add(key)
                need -= 1
    out: list[dict] = []
    for cat in ("attraction", "activity", "food", "hotel", "shopping"):
        out.extend((by_cat.get(cat) or [])[:max_per])
    return out


class AgentState(TypedDict):
    request: GenerateRequest
    requirements: dict
    candidates: list[dict]
    foods: list[dict]
    hotels: list[dict]
    consumption: dict | None
    daily_plans: list[dict]
    budget_estimate: dict
    raw_suggestions: list[dict]
    result: GenerateResponse
    attempts: int
    fix_count: int
    error: str | None
    feedback: str
    validation_issues: list[str]
    validation_log: list[str]
    degraded_reason: str | None
    schedule_report: dict
    critic_report: dict
    research_report: dict
    refill_count: int


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
    return {"candidates": context["candidates"], "foods": context["foods"],
            "hotels": context["hotels"], "consumption": context["consumption"],
            "research_report": context["research_report"]}


def _generate_open_plans(req: GenerateRequest, feedback: str,
                         context_hotels: list[dict] | None,
                         candidates: list[dict] | None = None,
                         foods: list[dict] | None = None) -> dict | None:
    """开放模式生成：权威参考资料 + LLM 知识 + 高德落坐标。

    P1 引用式生成：本地知识库检索结果（candidates/foods）作为带编号参考
    资料注入 Prompt，模型选点输出 refs 引用，生成后由 ReferencePool 落地
    为权威字段并回填真实来源；未命中资料的地点仍走高德落坐标并保持
    unverified。返回 AgentState 增量；开放研究整体失败（所有天均为空草案）
    时返回 None，由调用方降级到候选池约束链路或草案。
    """
    schedule_report: dict = {"destination_status": "draft_only", "research_mode": "open"}
    try:
        plans: list[dict] = []
        used: set[str] = set()
        raw_suggestions: list[dict] = []
        context = {
            "hotels": context_hotels or [],
            "candidates": candidates or [],
            "foods": foods or [],
        }
        ref_pool = ReferencePool(context)
        research_errors: list[str] = []
        if req.days > 1:
            trip_req = GenerateDayRequest(
                city=req.city, persons=req.persons, budget=req.budget,
                start_date=(str(req.start_date) if req.start_date else None),
                day_no=1, days=req.days, used_names=[],
                hotel_tier=req.hotel_tier, needs_hotel=True, context=context,
                requirements=req.requirements, region_hint=req.region_hint, feedback=feedback,
            )
            try:
                trip_plans, trip_suggestions = _llm_open_trip(trip_req)
                # 模型可能返回重复/越界的 day_no；字典推导会静默后覆盖前，
                # 保留首个并遥测丢弃项，缺的天在下方落成待研究草案。
                plans_by_day: dict[int, dict] = {}
                for i, p in enumerate(trip_plans):
                    try:
                        key = int(p.get("day_no", i + 1))
                    except (TypeError, ValueError):
                        key = i + 1
                    if key in plans_by_day:
                        record_event("decision", "duplicate_day_no_dropped",
                                     metadata={"day_no": key})
                        continue
                    plans_by_day[key] = p
                raw_suggestions.extend(trip_suggestions)
            except Exception as exc:  # noqa: BLE001 - open research is best effort
                logger.warning("open research failed for %s: %s", req.city, exc)
                research_errors.append(f"开放研究失败：{exc}")
                plans_by_day = {}
        else:
            plans_by_day = {}
        for day_no in range(1, req.days + 1):
            if req.days == 1:
                day_req = GenerateDayRequest(
                    city=req.city, persons=req.persons, budget=req.budget,
                    start_date=(str(req.start_date) if req.start_date else None),
                    day_no=day_no, days=req.days, used_names=sorted(used),
                    hotel_tier=req.hotel_tier, needs_hotel=day_no <= stay_nights(req.days),
                    context=context, requirements=req.requirements,
                    region_hint=req.region_hint, feedback=feedback,
                )
                try:
                    plan = _llm_open_day(day_req, used)
                    raw_suggestions.extend(plan.get("suggestions") or [])
                except Exception as exc:  # noqa: BLE001 - open research is best effort
                    logger.warning("open research failed for %s day %s: %s", req.city, day_no, exc)
                    research_errors.append(f"第{day_no}天开放研究失败：{exc}")
                    plan = {"note": f"{req.city}第{day_no}天待研究", "items": []}
            else:
                plan = plans_by_day.get(day_no) or {"note": f"{req.city}第{day_no}天待研究", "items": []}
            ground_cache: dict = {}
            # 结构校验：LLM 可能返回非 dict 项或无 poi_name 的脏项，必须在
            # 落地前过滤，否则 format_output 的 item.get / TripItem(**item) 崩溃。
            plan["items"] = [item for item in (plan.get("items") or [])
                             if isinstance(item, dict) and str(item.get("poi_name") or "").strip()]
            for item in plan["items"]:
                if not ref_pool.ground(item):
                    _amap_ground(item, req.city, ground_cache)
                if item.get("poi_name"):
                    used.add(str(item["poi_name"]))
            plans.append({
                "day_no": day_no,
                "note": plan.get("note"),
                "theme": plan.get("theme"),
                "mini_route": plan.get("mini_route") or plan.get("miniRoute") or {},
                "backup_plan": plan.get("backup_plan") or plan.get("backupPlan") or [],
                "photo_spots": plan.get("photo_spots") or plan.get("photoSpots") or [],
                "practical_notes": plan.get("practical_notes") or plan.get("practicalNotes") or [],
                "items": plan.get("items") or [],
            })
        if research_errors and not any(p.get("items") for p in plans):
            # 整段开放研究失败：交由调用方降级，避免把候选库城市打成空草案。
            return None
        # 跨天去重：多日一次生成时 used 只在 grounding 后累计，模型可能跨天重复。
        seen_names: set[str] = set()
        for plan in plans:
            kept_items = []
            for item in plan.get("items") or []:
                name = str(item.get("poi_name") or "").strip()
                if name and name in seen_names:
                    record_event("decision", "duplicate_cross_day_dropped",
                                 metadata={"day_no": plan.get("day_no"), "poi_name": name})
                    continue
                if name:
                    seen_names.add(name)
                kept_items.append(item)
            plan["items"] = kept_items
        # 后处理：酒店摊晚 + 0 价覆盖 + 备选池地板（不改变「LLM 决定内容」契约）
        stay_n = stay_nights(req.days)
        hotels_added = _spread_hotels(plans, stay_n)
        price_lookup: dict[str, dict] = {}
        for poi in (candidates or []) + (foods or []) + (context_hotels or []):
            name = str(poi.get("name") or "").strip()
            if name:
                price_lookup[name] = poi
        filled_costs = _fill_zero_costs(plans, price_lookup)
        # 备选池补全必须看到酒店/体验候选，否则对应 tab 会空
        activities = [
            {**row, "_authoritative": True}
            for row in poi_repository.search_pois(req.city, category="activity", limit=12)
        ]
        extra_pool = (candidates or []) + (foods or []) + (context_hotels or []) + activities
        raw_suggestions = _floor_suggestions(raw_suggestions, extra_pool)
        if hotels_added or filled_costs:
            schedule_report["postprocess"] = {
                "hotels_spread": hotels_added,
                "costs_filled": filled_costs,
            }
            record_event("decision", "postprocess", metadata=schedule_report["postprocess"])
        schedule_report["destination_status"] = "researched" if not research_errors else "draft_only"
        schedule_report["open_research"] = True
        if research_errors:
            schedule_report["research_errors"] = research_errors
        if ref_pool:
            # 引用式生成遥测：命中率/refs 有效率/资料利用率（评测与观测共用）。
            schedule_report["reference_stats"] = dict(ref_pool.stats)
            record_event("decision", "reference_usage", metadata=dict(ref_pool.stats))
        return {
            "daily_plans": plans,
            "budget_estimate": {},
            "raw_suggestions": raw_suggestions,
            "error": None,
            "schedule_report": schedule_report,
            "degraded_reason": (
                "已使用开放研究生成；关键事实需出发前复核"
                if not research_errors else
                "开放研究部分失败，已返回待研究草案；关键事实需出发前复核"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - 开放模式整体异常时降级
        logger.warning("open generation crashed for %s: %s", req.city, exc)
        return None


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
        open_state = _generate_open_plans(
            req, feedback, state.get("hotels"),
            candidates=state.get("candidates"), foods=state.get("foods"),
        )
        if open_state is not None:
            return open_state
        if attempts + 1 >= MAX_GENERATION_ATTEMPTS:
            # 重试耗尽：草案必须可达（多日行程此前因 attempts 预算与 days
            # 挂钩而直接落到空 plans，草案分支成为死代码）。
            return _draft_state(req, "开放研究重试耗尽，已返回待研究草案", schedule_report)
        record_event("route", "retry", metadata={"reason": "open_research_failed"})
        return {"error": "开放研究失败", "attempts": attempts + 1,
                "schedule_report": schedule_report}

    reason = ("未配置 LLM，无法生成行程内容" if not settings.llm_api_key
              else "开放研究重试耗尽，已返回待研究草案")
    return _draft_state(req, reason, schedule_report)


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
        if settings.route_service_enabled:
            route_matrix = _route_matrix_for_plans(plans)
        issues, log = validate_plans(plans, route_matrix=route_matrix)
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
    attempt_limit = _generation_attempt_limit(state)
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


def _refill_domain(issues: list[str]) -> str | None:
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
    record_event("decision", "research_refill", metadata={
        "domain": domain, "count": len(pack.items), "rounds": pack.rounds})
    metrics.record_research_refill()
    return {"candidates": candidates, "research_report": research_report,
            "refill_count": state.get("refill_count", 0) + 1}


@traced("node", "format")
def format_output(state: AgentState) -> dict:
    req: GenerateRequest = state["request"]
    raw_plans = state["daily_plans"]
    budget_source = state["budget_estimate"]
    schedule_report: dict = dict(state.get("schedule_report") or {})
    # 多 Agent 研究阶段统计随 schedule_report 透出（证据包规模/置信度/缺口）。
    if state.get("research_report"):
        schedule_report["research"] = state["research_report"]
    quality_fallback_reason: str | None = None
    if state.get("validation_issues") and state.get("fix_count", 0) > _generation_attempt_limit(state):
        # LLM-only 原则：重试耗尽也不允许用知识库候选拼装行程替换模型结果
        # （那是"直接使用知识库"）。保留开放模式结果，把未修复的约束问题
        # 如实降级标注，交给用户复核。
        quality_fallback_reason = (
            "开放模式结果未通过全部约束校验（见校验日志），已保留但请复核当日时间安排"
        )
        record_event("route", "keep_llm_result",
                     metadata={"reason": "validation_retry_exhausted"})
    lookup: dict[str, dict] = {}
    # 酒店同样属于本次候选快照的权威事实源。若遗漏酒店，格式化阶段会把
    # 已知城市的酒店误判为开放模式 LLM 生成，导致来源和质量状态失真。
    for poi in ((state.get("candidates") or []) + (state.get("foods") or [])
                + (state.get("hotels") or [])):
        name = poi.get("name")
        if name and name not in lookup:
            lookup[name] = poi
    daily_plans = []
    source_records: dict[str, SourceRecord] = {}
    # 不在生成请求中串行检索图片。该操作会对每个 POI 访问外部网络并显著
    # 放大首屏耗时；前端在卡片加载时通过 /api/amap/poi-photo 懒加载图片。
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
        if item.get("item_type") != "hotel":
            return
        if name not in live_cache:
            if remaining["n"] > 0 and settings.llm_api_key:
                remaining["n"] -= 1
                live_cache[name] = query_live_price(req.city, name, req.start_date)
            else:
                live_cache[name] = None
        live = live_cache.get(name)
        try:
            base = float(item.get("cost")) if item.get("cost") is not None else None
        except (TypeError, ValueError):
            base = None
        if base is not None and base == 0:
            base = None
        if live:
            # 联网拿到的是"当前挂牌价"，未来日期的季节差异再叠系数
            # （即使模型未写 cost / 写成 0，也必须应用实时价）
            adjusted = live["price"] * factor
            item["cost"] = round(adjusted, 2)
            remark = f"联网实时价￥{live['price']:g}：{live['note']}"
            if factor != 1.0:
                remark += f"；按{label}系数×{factor}调整"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
        elif base is not None and factor != 1.0:
            item["cost"] = round(base * factor, 2)
            remark = f"{label}估算：系数×{factor}（知识库基准价￥{base:g}）"
            item["remark"] = f"{item['remark']}；{remark}" if item.get("remark") else remark
        elif base is None and item.get("cost") is None:
            # 无实时价且无基准价：保持缺省，由预算引擎/知识库回落
            return

    hotel_total = 0.0
    attraction_total = 0.0
    for plan in raw_plans:
        items = []
        # LLM 可能输出 souvenir/activity 等扩展类型：归一到 TripItem 契约，避免 Pydantic 500
        for item in sanitize_itinerary_items(plan.get("items")):
            poi = lookup.get(item.get("poi_name"))
            if poi:
                # 0/0 是缺失坐标的哨兵值（store._row_payload 会把 NULL 写成 0.0），
                # 不能作为权威坐标回填，否则幻觉坐标获得权威背书。
                if not _has_coord(item.get("latitude")) and _has_valid_coords(poi):
                    item["latitude"] = float(poi["latitude"])
                    item["longitude"] = float(poi["longitude"])
                if not item.get("poi_id"):
                    item["poi_id"] = str(poi.get("id") or "")
                if not item.get("cost") and poi.get("ticket_price") is not None:
                    item["cost"] = float(poi["ticket_price"])
                if item.get("open_time") is None:
                    item["open_time"] = poi.get("open_time")
                source_name = str(poi.get("source") or "mysql.poi_knowledge")
                source_updated_at = str(poi.get("source_updated_at") or "") or None
                item["source"] = source_name
                item["source_updated_at"] = source_updated_at
                item["verification_status"] = "partially_verified"
                item["value_kind"] = "observed"
                item["freshness_status"] = "fresh" if source_updated_at else "unknown"
                item["review_requirement"] = "none" if source_updated_at else "before_departure"
                if not _has_valid_coords(poi):
                    # 权威行缺坐标：item 上残留的是模型自填坐标，不背书。
                    item["verification_status"] = "unverified"
                    item["value_kind"] = "estimated"
                    item["freshness_status"] = "unknown"
                    item["review_requirement"] = "before_departure"
                # fact_evidence 延迟构建：前端请求详情时再补充，不阻塞生成流程
                source_records.setdefault(source_name, SourceRecord(
                    source_id=source_name, storage_source=source_name,
                    provider=source_name, retrieved_at=str(poi.get("source_fetched_at") or source_updated_at or "") or None,
                    expires_at=None,
                ))
            else:
                # 开放模式中的 LLM 地点必须明确标为生成/待复核事实。
                item["source"] = item.get("source") or "llm.open_day"
                item["verification_status"] = "unverified"
                item["value_kind"] = "estimated"
                item["freshness_status"] = "unknown"
                item["review_requirement"] = "before_departure"
                # fact_evidence 延迟构建：前端请求详情时再补充
                source_records.setdefault("llm.open_day", SourceRecord(
                    source_id="llm.open_day", provider="llm.open_day",
                    retrieved_at=None, expires_at=None,
                ))
                if item.get("latitude") is not None and item.get("longitude") is not None:
                    source_records.setdefault("amap-grounding", SourceRecord(
                        source_id="amap-grounding", storage_source="amap-grounding",
                        provider="amap", retrieved_at=None, expires_at=None,
                    ))
            if item.get("item_type") == "hotel":
                price_hotel(item)
                if count_hotel_nights_in_budget(plan["day_no"], req.days, "hotel"):
                    hotel_total += float(item.get("cost") or 0)
            elif item.get("item_type") == "attraction":
                attraction_total += float(item.get("cost") or 0)
            # 时间窗优先：库内典型时长可能与已排 start/end 冲突（西湖 480 vs 150）。
            from app.agent.reflect import parse_time as _parse_time
            st = _parse_time(item.get("start_time"))
            en = _parse_time(item.get("end_time"))
            if st is not None and en is not None and en > st:
                item["duration_min"] = en - st
            items.append(TripItem(**item))
        daily_plans.append(DailyPlan(day_no=plan["day_no"], note=plan.get("note"), items=items,
                                     theme=plan.get("theme"), mini_route=plan.get("mini_route") or {},
                                     backup_plan=plan.get("backup_plan") or [],
                                     photo_spots=plan.get("photo_spots") or [],
                                     practical_notes=plan.get("practical_notes") or []))

    # 预算只把 LLM/候选池预算当作初始估计，最终按本次实际选中的 POI 重算，
    # 避免“候选平均票价”与用户看到的具体景点不一致。
    budget_estimate = dict(budget_source or {})
    budget_estimate["门票"] = round(attraction_total * req.persons, 2)
    meal_price = float((state.get("consumption") or {}).get("meal_price", 60.0))
    transport_price = float((state.get("consumption") or {}).get("transport_price", 35.0))
    # 餐饮优先按实际选中的餐厅人均价计（每日两餐同档估算），知识库无价的日期
    # 回落到城市人均餐价；这样高档餐厅的选择会真实反映在预算里。
    meal_total = 0.0
    priced_days = 0
    for plan in daily_plans:
        day_meal = max((float(i.cost or 0) for i in plan.items
                        if i.item_type == "food" and i.cost is not None), default=0.0)
        if day_meal > 0:
            meal_total += day_meal * 2
            priced_days += 1
    unpriced_days = max(len(daily_plans) - priced_days, 0)
    budget_estimate["餐饮"] = round(
        meal_total * req.persons + meal_price * 2 * unpriced_days * req.persons, 2)
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
            "theme": plan.theme,
            "mini_route": plan.mini_route,
            "backup_plan": plan.backup_plan,
            "photo_spots": plan.photo_spots,
            "practical_notes": plan.practical_notes,
            "items": [item.model_dump() for item in plan.items],
        }
        for plan in daily_plans
    ]
    final_route_matrix = None
    if settings.route_service_enabled:
        final_route_matrix = _route_matrix_for_plans(final_raw_plans)
        route_sources = [str(route.get("source") or "unknown") for route in final_route_matrix.values()]
        if route_sources:
            schedule_report.setdefault("route_sources", list(dict.fromkeys(route_sources)))
            schedule_report["degraded"] = bool(schedule_report.get("degraded")) or any(
                source != "amap" for source in route_sources
            )
    final_issues, final_log = validate_plans(final_raw_plans, route_matrix=final_route_matrix)
    # critique_plans 是纯内存的轻量软评审，直接同步调用即可。
    # （此前每请求新建 ThreadPoolExecutor 且从不 shutdown，会泄漏常驻线程。）
    try:
        critic_report = critique_plans(final_raw_plans, req.preferences).as_dict()
    except Exception:
        critic_report = {"score": 0.0, "issues": [], "strengths": [], "dimensions": {}}
    record_event("decision", "critic_result", metadata={
        "score": critic_report["score"], "issue_count": len(critic_report.get("issues", [])),
    })
    validation_log = list(state.get("validation_log") or [])
    validation_log.extend(final_log)
    degraded_reasons: list[str] = []
    if state.get("degraded_reason"):
        degraded_reasons.append(state["degraded_reason"] or "")
    if schedule_report.get("degraded") and settings.route_service_enabled:
        degraded_reasons.append("真实路线服务部分不可用，已使用坐标估算")
    if quality_fallback_reason:
        degraded_reasons.append(quality_fallback_reason)
    if final_issues:
        validation_log.extend(final_issues)
        degraded_reasons.append("达到重试上限后仍存在行程约束问题")
    degraded_reasons = list(dict.fromkeys(reason for reason in degraded_reasons if reason))
    status = "degraded" if degraded_reasons else "success"
    quality_warnings: list[QualityIssue] = []
    item_count = 0
    estimated_count = 0
    evidenced_count = 0
    for day_index, day in enumerate(daily_plans):
        for item_index, item in enumerate(day.items):
            item_count += 1
            if item.verification_status != "verified":
                quality_warnings.append(QualityIssue(
                    code="FACT_REQUIRES_REVIEW",
                    # path 必须是"日索引 + 当日内索引"，此前用跨天累计序号
                    # 会让前端定位指错条目。
                    path=f"trip.daily_plans[{day_index}].items[{item_index}]",
                    message=f"{item.poi_name} 的部分事实需要出发前复核",
                ))
            if item.value_kind == "estimated":
                estimated_count += 1
            # fact_evidence 延迟构建，此处基于 source 字段判断是否有溯源
            if item.source:
                evidenced_count += 1
    blocking = [QualityIssue(code="ROUTE_OR_SCHEDULE_CONFLICT", message=issue) for issue in final_issues]
    if item_count == 0:
        blocking.append(QualityIssue(code="NO_ITINERARY_ITEMS", message="没有可交付的行程地点"))
    elif not any(item.item_type == "attraction" for day in daily_plans for item in day.items):
        # 占位酒店式行程（有 items 但 0 景点）不可作为可交付行程放行。
        blocking.append(QualityIssue(code="NO_ATTRACTION_ITEMS", message="行程中没有安排任何景点"))
    empty_days = [day.day_no for day in daily_plans if not day.items]
    if empty_days:
        blocking.append(QualityIssue(
            code="MISSING_DAY_ITEMS",
            message="以下日期没有可交付的行程地点：" + ", ".join(str(day_no) for day_no in empty_days),
        ))
    quality_status = "BLOCKED" if blocking else ("READY_WITH_WARNINGS" if quality_warnings else "READY")
    if schedule_report.get("destination_status") == "draft_only" and not blocking:
        quality_status = "READY_WITH_WARNINGS"
    quality_report = QualityReport(
        quality_status=quality_status,
        validated_at=datetime.now(timezone.utc).isoformat(),
        blocking_issues=blocking,
        warnings=quality_warnings,
        metrics={
            "item_count": float(item_count),
            "fact_evidence_coverage": round(evidenced_count / item_count, 4) if item_count else 0.0,
            "estimated_fact_ratio": round(estimated_count / item_count, 4) if item_count else 0.0,
        },
    )
    # 没有任何可交付地点时，质量状态必须为 BLOCKED；这类草案不能被
    # “degraded” 状态误解为可直接执行的行程。
    if item_count == 0:
        status = "failed"
    destination_status = schedule_report.get("destination_status")
    if destination_status not in {"knowledge_backed", "researched", "draft_only"}:
        destination_status = "knowledge_backed" if state.get("candidates") else "draft_only"
    record_event("decision", "run_status", metadata={
        "status": status,
        "final_issue_count": len(final_issues),
    })
    # 开放模式下模型建议可来自候选池之外（allow_external）：坐标留空的
    # 条目由前端在加入行程前经高德补齐；候选池保底链路仍保持池内过滤。
    open_research = bool((state.get("schedule_report") or {}).get("open_research"))
    # 体验类不在 Supervisor 三域研究里：从知识库补入，保证「发现更多-体验」有地板
    activities = [
        {**row, "_authoritative": True}
        for row in poi_repository.search_pois(req.city, category="activity", limit=12)
    ]
    suggestion_models = [
        Suggestion(**row)
        for row in build_suggestions(
            raw_plans,
            (state.get("candidates") or []) + activities,
            state.get("foods"),
            state.get("hotels") or [],
            state.get("raw_suggestions") or [],
            allow_external=open_research,
        )
    ]
    result = GenerateResponse(
        city=req.city,
        days=req.days,
        title=f"{req.city}{req.days}日游",
        daily_plans=daily_plans,
        budget_estimate=budget_estimate,
        suggestions=suggestion_models,
        validation_log=validation_log,
        price_note=price_note,
        schedule_report=schedule_report,
        critic_report=critic_report,
        destination_status=destination_status,
        sources=list(source_records.values()),
        quality_report=quality_report,
        status=status,
        status_reason="；".join(degraded_reasons) or None,
    )
    return {"result": result}


def build_graph() -> StateGraph:
    """兼容保留：实际执行请使用 trip_graph.unified_agent_graph。

    历史两套图（本文件整段图 + day_workflow 逐日图）已合并为一张
    ``trip_graph``；此处仍导出整段子图的 StateGraph 定义供阅读/对照，
    运行时入口 ``run_generate`` 走统一图。
    """
    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_requirements)
    graph.add_node("research", research_pois)
    graph.add_node("generate", generate_itinerary)
    graph.add_node("reflect", reflect)
    graph.add_node("refill_research", research_refill)
    graph.add_node("format", format_output)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "research")
    graph.add_edge("research", "generate")
    graph.add_edge("generate", "reflect")
    graph.add_conditional_edges("reflect", needs_fix, {
        "fix": "generate", "refill": "refill_research", "pass": "format"})
    graph.add_edge("refill_research", "generate")
    graph.add_edge("format", END)
    return graph


# 统一图（运行时真实入口）；旧名 agent_graph 保留兼容。
def _load_unified():
    from app.agent.trip_graph import unified_agent_graph
    return unified_agent_graph


agent_graph = None  # 延迟到首次 run_generate，避免与 trip_graph 循环导入


def run_generate(req: GenerateRequest) -> GenerateResponse:
    from app.agent.trip_graph import run_trip
    return run_trip(req)


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
        # POI 行主键是 "id"，PoiOption 字段是 poi_id；直接 **poi 会因键名
        # 不匹配把 poi_id 静默丢成 None（前端"换一批"无法定位）。
        option_row = {**poi, "poi_id": poi.get("poi_id", poi.get("id"))}
        recommendations.append(PoiOption(**option_row))
        if len(recommendations) >= 5:
            break
    return AdjustResponse(city=req.city, current=req.poi_name, recommendations=recommendations)
