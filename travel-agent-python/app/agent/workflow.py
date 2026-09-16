"""初次行程生成的工作流编排（LangGraph：生成 → 校验 → 修复 循环）。

跨模块 API（G-1.2 提级，供 rag.evaluation_generation 复用）：generate_open_plans。

职责：
- run_generate：入口委托给 trip_graph 统一图（本模块提供其节点函数）；
- generate_itinerary：LLM-only 生成——开放模式（LLM 知识 + 权威参考资料注入 +
  高德落坐标）是唯一行程内容来源，失败走 fix 循环重试，耗尽返回待研究草案；
- reflect：调用 reflect.validate_plans 校验并产出修复反馈；
- format_output：编排「回填权威事实 → 定价 → 终检 → 质量结论 → 建议池 → 组装
  GenerateResponse」，各阶段实现见 app.agent.formatting；
- run_adjust：为“替换某景点”提供候选。

实现要点：
- 知识库永远只是补充证据：检索结果以编号参考资料注入 Prompt，命中项落地
  权威字段与溯源，不直接用知识库候选拼装行程（LLM 不可用时如实返回草案）；
- 编排图见 trip_graph.unified_agent_graph（整段/逐日共用），reflect 不通过则
  带 feedback 回到 generate 重试；
- 与 chat_draft 的“对话编辑”链路不同，本模块负责从零生成首版行程；
- 酒店定价链（联网实时价 → 基准价 × 季节系数）在 formatting.prices 实现。

产品口径以 generation_core 为唯一真相源。

依赖：day_stream、generators、reflect、formatting、route_matrix、schemas.trip、generation_core。
"""

import logging
from typing import TypedDict

from app.agent import poi_repository, research
from app.agent.day_stream import llm_open_day, llm_open_trip, local_ground
from app.agent.formatting.facts import (
    apply_item_facts,
    build_lookup,
    sync_duration_from_time_window,
)
from app.agent.formatting.prices import PriceStage
from app.agent.formatting.quality import judge_output, run_final_validation
from app.agent.generation_core import (
    MAX_FIX_ATTEMPTS,
    MAX_GENERATION_ATTEMPTS,
    MAX_REFILLS,
    count_hotel_nights_in_budget,
    draft_day_plans,
    drop_cross_day_duplicates,
    fill_zero_costs,
    sanitize_itinerary_items,
    spread_hotels,
    stay_nights,
)
from app.agent.generators import (
    ReferencePool,
    budget_tier,
    build_suggestions,
    fill_suggestion_gaps,
)
from app.agent.observability import metrics
from app.agent.reflect import build_feedback, validate_plans
from app.agent.route_matrix import route_matrix_for_plans
from app.agent.tools import search_attractions, search_foods
from app.agent.trace import record_event, traced
from app.common.config import settings
from app.schemas.trip import (
    AdjustRequest,
    AdjustResponse,
    DailyPlan,
    GenerateDayRequest,
    GenerateRequest,
    GenerateResponse,
    PoiOption,
    SourceRecord,
    Suggestion,
    TripItem,
)

logger = logging.getLogger(__name__)

# 产品口径与常量见 generation_core；此处保留兼容别名。
_spread_hotels = spread_hotels


def _generation_attempt_limit(state: dict) -> int:
    request = state.get("request")
    return 1 if request is not None and request.days > 1 else MAX_FIX_ATTEMPTS


def _draft_state(req: GenerateRequest, reason: str, schedule_report: dict | None = None) -> dict:
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


def _activity_floor(city: str) -> list[dict]:
    """体验类不在 Supervisor 三域研究里：从知识库补入，保证「发现更多-体验」有地板。

    唯一实现（G-1.3 ④）：原在 _generate_open_plans 后处理与建议装配两处逐字重复。
    """
    return [{**row, "_authoritative": True} for row in poi_repository.search_pois(city, category="activity", limit=12)]


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
                if (
                    poi.get("rating") is not None
                    and rating < 4.3
                    and not any(
                        x in tags for x in ("体验", "演出", "潜水", "SPA", "spa", "冲浪", "剧场", "美术馆", "观景")
                    )
                ):
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
    return {
        "candidates": context["candidates"],
        "foods": context["foods"],
        "hotels": context["hotels"],
        "consumption": context["consumption"],
        "research_report": context["research_report"],
    }


def generate_open_plans(
    req: GenerateRequest,
    feedback: str,
    context_hotels: list[dict] | None,
    candidates: list[dict] | None = None,
    foods: list[dict] | None = None,
) -> dict | None:
    """开放模式生成：权威参考资料 + LLM 知识 + 高德落坐标。

    引用式生成：本地知识库检索结果（candidates/foods）作为带编号参考
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
                city=req.city,
                persons=req.persons,
                budget=req.budget,
                start_date=(str(req.start_date) if req.start_date else None),
                day_no=1,
                days=req.days,
                used_names=[],
                hotel_tier=req.hotel_tier,
                needs_hotel=True,
                context=context,
                requirements=req.requirements,
                intent=req.intent,
                region_hint=req.region_hint,
                feedback=feedback,
            )
            try:
                trip_plans, trip_suggestions = llm_open_trip(trip_req)
                # 模型可能返回重复/越界的 day_no；字典推导会静默后覆盖前，
                # 保留首个并遥测丢弃项，缺的天在下方落成待研究草案。
                plans_by_day: dict[int, dict] = {}
                for i, p in enumerate(trip_plans):
                    try:
                        key = int(p.get("day_no", i + 1))
                    except (TypeError, ValueError):
                        key = i + 1
                    if key in plans_by_day:
                        record_event("decision", "duplicate_day_no_dropped", metadata={"day_no": key})
                        continue
                    plans_by_day[key] = p
                raw_suggestions.extend(trip_suggestions)
            except Exception as exc:
                logger.warning("open research failed for %s: %s", req.city, exc)
                research_errors.append(f"开放研究失败：{exc}")
                plans_by_day = {}
        else:
            plans_by_day = {}
        for day_no in range(1, req.days + 1):
            if req.days == 1:
                day_req = GenerateDayRequest(
                    city=req.city,
                    persons=req.persons,
                    budget=req.budget,
                    start_date=(str(req.start_date) if req.start_date else None),
                    day_no=day_no,
                    days=req.days,
                    used_names=sorted(used),
                    hotel_tier=req.hotel_tier,
                    needs_hotel=day_no <= stay_nights(req.days),
                    context=context,
                    requirements=req.requirements,
                    intent=req.intent,
                    region_hint=req.region_hint,
                    feedback=feedback,
                )
                try:
                    plan = llm_open_day(day_req, used)
                    raw_suggestions.extend(plan.get("suggestions") or [])
                except Exception as exc:
                    logger.warning("open research failed for %s day %s: %s", req.city, day_no, exc)
                    research_errors.append(f"第{day_no}天开放研究失败：{exc}")
                    plan = {"note": f"{req.city}第{day_no}天待研究", "items": []}
            else:
                plan = plans_by_day.get(day_no) or {"note": f"{req.city}第{day_no}天待研究", "items": []}
            ground_cache: dict = {}
            # 结构校验：LLM 可能返回非 dict 项或无 poi_name 的脏项，必须在
            # 落地前过滤，否则 format_output 的 item.get / TripItem(**item) 崩溃。
            plan["items"] = [
                item
                for item in (plan.get("items") or [])
                if isinstance(item, dict) and str(item.get("poi_name") or "").strip()
            ]
            for item in plan["items"]:
                if not ref_pool.ground(item):
                    local_ground(item, req.city, ground_cache)
                if item.get("poi_name"):
                    used.add(str(item["poi_name"]))
            plans.append(
                {
                    "day_no": day_no,
                    "note": plan.get("note"),
                    "theme": plan.get("theme"),
                    "mini_route": plan.get("mini_route") or plan.get("miniRoute") or {},
                    "backup_plan": plan.get("backup_plan") or plan.get("backupPlan") or [],
                    "photo_spots": plan.get("photo_spots") or plan.get("photoSpots") or [],
                    "practical_notes": plan.get("practical_notes") or plan.get("practicalNotes") or [],
                    # 叙事层透传：day_options（当日可选方案）与 trip_theme
                    # （整趟主题，open_trip 顶层/open_day 第 1 天产出，见
                    # llm_open_trip 的注入逻辑）；items 内 why_this 随 dict 原样携带。
                    "day_options": plan.get("day_options") or plan.get("dayOptions") or [],
                    "trip_theme": plan.get("trip_theme") or plan.get("tripTheme"),
                    "items": plan.get("items") or [],
                }
            )
        if research_errors and not any(p.get("items") for p in plans):
            # 整段开放研究失败：交由调用方降级，避免把候选库城市打成空草案。
            return None
        # 跨天去重：多日一次生成时 used 只在 grounding 后累计，模型可能跨天重复。
        # 共享双通道判重：归一化同名 + 落地后同类型近坐标（<80m），名称变体
        # （"圣家堂" vs "圣家堂大教堂"）由坐标通道兜底；酒店豁免（摊铺语义）。
        dropped = drop_cross_day_duplicates(plans)
        for row in dropped:
            record_event("decision", "duplicate_cross_day_dropped", metadata=row)
        # 后处理：酒店摊晚 + 0 价覆盖 + 备选池地板（不改变「LLM 决定内容」契约）
        stay_n = stay_nights(req.days)
        hotels_added = _spread_hotels(plans, stay_n)
        price_lookup: dict[str, dict] = {}
        for poi in (candidates or []) + (foods or []) + (context_hotels or []):
            name = str(poi.get("name") or "").strip()
            if name:
                price_lookup[name] = poi
        filled_costs = fill_zero_costs(plans, price_lookup)
        # 备选池补全必须看到酒店/体验候选，否则对应 tab 会空
        activities = _activity_floor(req.city)
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
                if not research_errors
                else "开放研究部分失败，已返回待研究草案；关键事实需出发前复核"
            ),
        }
    except Exception as exc:
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
        open_state = generate_open_plans(
            req,
            feedback,
            state.get("hotels"),
            candidates=state.get("candidates"),
            foods=state.get("foods"),
        )
        if open_state is not None:
            return open_state
        if attempts + 1 >= MAX_GENERATION_ATTEMPTS:
            # 重试耗尽：草案必须可达（多日行程此前因 attempts 预算与 days
            # 挂钩而直接落到空 plans，草案分支成为死代码）。
            return _draft_state(req, "开放研究重试耗尽，已返回待研究草案", schedule_report)
        record_event("route", "retry", metadata={"reason": "open_research_failed"})
        return {"error": "开放研究失败", "attempts": attempts + 1, "schedule_report": schedule_report}

    reason = "未配置 LLM，无法生成行程内容" if not settings.llm_api_key else "开放研究重试耗尽，已返回待研究草案"
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
    record_event(
        "decision", "research_refill", metadata={"domain": domain, "count": len(pack.items), "rounds": pack.rounds}
    )
    metrics.record_research_refill()
    return {
        "candidates": candidates,
        "research_report": research_report,
        "refill_count": state.get("refill_count", 0) + 1,
    }


@traced("node", "format")
def _quality_fallback_reason(state: AgentState) -> str | None:
    """重试耗尽时的口径：保留开放模式结果并如实降级标注，不用知识库候选替换模型。"""
    if state.get("validation_issues") and state.get("fix_count", 0) > _generation_attempt_limit(state):
        # LLM-only 原则：重试耗尽也不允许用知识库候选拼装行程替换模型结果
        # （那是"直接使用知识库"）。保留开放模式结果，把未修复的约束问题
        # 如实降级标注，交给用户复核。
        record_event("route", "keep_llm_result", metadata={"reason": "validation_retry_exhausted"})
        return "开放模式结果未通过全部约束校验（见校验日志），已保留但请复核当日时间安排"
    return None


def format_output(state: AgentState) -> dict:
    """组装 GenerateResponse：回填权威事实 → 定价 → 终检 → 质量结论 → 建议池。

    各阶段实现见 app.agent.formatting；本函数只保留跨阶段的编排与状态流转。
    """
    req: GenerateRequest = state["request"]
    raw_plans = state["daily_plans"]
    schedule_report: dict = dict(state.get("schedule_report") or {})
    # 多 Agent 研究阶段统计随 schedule_report 透出（证据包规模/置信度/缺口）。
    if state.get("research_report"):
        schedule_report["research"] = state["research_report"]
    quality_fallback_reason = _quality_fallback_reason(state)
    consumption = state.get("consumption") or {}

    lookup = build_lookup(state.get("candidates"), state.get("foods"), state.get("hotels"))
    prices = PriceStage.create(req)
    source_records: dict[str, SourceRecord] = {}
    daily_plans: list[DailyPlan] = []
    hotel_total = 0.0
    attraction_total = 0.0
    for plan in raw_plans:
        items = []
        # LLM 可能输出 souvenir/activity 等扩展类型：归一到 TripItem 契约，避免 Pydantic 500
        for item in sanitize_itinerary_items(plan.get("items")):
            apply_item_facts(item, lookup.get(item.get("poi_name")), source_records)
            if item.get("item_type") == "hotel":
                prices.price_hotel(item)
                if count_hotel_nights_in_budget(plan["day_no"], req.days, "hotel"):
                    hotel_total += float(item.get("cost") or 0)
            elif item.get("item_type") == "food":
                prices.price_food(item, float(consumption.get("meal_price") or 0) or None)
            elif item.get("item_type") == "attraction":
                attraction_total += float(item.get("cost") or 0)
            sync_duration_from_time_window(item)
            items.append(TripItem(**item))
        daily_plans.append(
            DailyPlan(
                day_no=plan["day_no"],
                note=plan.get("note"),
                items=items,
                theme=plan.get("theme"),
                mini_route=plan.get("mini_route") or {},
                backup_plan=plan.get("backup_plan") or [],
                photo_spots=plan.get("photo_spots") or [],
                practical_notes=plan.get("practical_notes") or [],
                day_options=plan.get("day_options") or [],
                trip_theme=plan.get("trip_theme"),
            )
        )

    budget_estimate = prices.recompute_budget(
        state["budget_estimate"], daily_plans, hotel_total, attraction_total, consumption
    )
    check = run_final_validation(req, daily_plans, schedule_report, state.get("consumption"))
    outcome = judge_output(state, daily_plans, schedule_report, check, quality_fallback_reason)

    # 开放模式下模型建议可来自候选池之外（allow_external）：坐标留空的
    # 条目由前端在加入行程前经高德补齐；候选池保底链路仍保持池内过滤。
    open_research = bool((state.get("schedule_report") or {}).get("open_research"))
    activities = _activity_floor(req.city)
    tier_label, _tier_g, _tier_ppd = budget_tier(req.budget, req.persons, req.days)
    suggestion_rows = fill_suggestion_gaps(
        build_suggestions(
            raw_plans,
            (state.get("candidates") or []) + activities,
            state.get("foods"),
            state.get("hotels") or [],
            state.get("raw_suggestions") or [],
            allow_external=open_research,
        ),
        req.city,
        budget_tier=tier_label or None,
    )

    return {
        "result": GenerateResponse(
            city=req.city,
            days=req.days,
            title=f"{req.city}{req.days}日游",
            # 整趟主题承接第 1 天（open_trip 顶层 / open_day day_no==1 产出）
            trip_theme=(daily_plans[0].trip_theme if daily_plans else None),
            daily_plans=daily_plans,
            budget_estimate=budget_estimate,
            suggestions=[Suggestion(**row) for row in suggestion_rows],
            validation_log=outcome.validation_log,
            price_note=prices.price_note(),
            schedule_report=schedule_report,
            critic_report=check.critic_report,
            destination_status=outcome.destination_status,
            sources=list(source_records.values()),
            quality_report=outcome.quality_report,
            status=outcome.status,
            status_reason=outcome.status_reason,
        )
    }


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
