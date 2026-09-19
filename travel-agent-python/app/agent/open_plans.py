"""整段开放模式的草案生成与降级（G-2.4 自 workflow 拆出）。

generate_open_plans 分三段（原 152 行单函数按阶段拆开，行为不变）：
1. `_generate_drafts`：一次 LLM 生成 + 参考落地（多日走 open_trip，单日走
   open_day；单日失败降级为「待研究」空草案）；
2. `_postprocess_drafts`：跨天去重 / 酒店摊铺 / 0 价补水 / 备选池地板 / 遥测；
3. `draft_state`：整段失败或重试耗尽时返回「待研究草案」（不冒充成功）。

**可 mock 契约（勿随意搬移）**：单测经 `open_plans.llm_open_day`、
`open_plans.llm_open_trip`、`open_plans.local_ground` 注入桩，替身须打在
本模块（调用期解析）。

依赖：day_prompts/day_stream/grounding/reference_pool、budget/suggestions、
generation_core；不 import workflow（禁反向）。
"""

import logging

from app.agent.day_prompts import llm_open_trip
from app.agent.day_stream import llm_open_day
from app.agent.generation_core import (
    draft_day_plans,
    fill_zero_costs,
    spread_hotels,
    stay_nights,
)
from app.agent.landing import drop_refuted_items, filter_plan_items, ground_item
from app.agent.poi_identity import drop_cross_day_duplicates
from app.agent.reference_pool import ReferencePool
from app.agent.suggestions import activity_floor, floor_suggestions
from app.agent.trace import record_event
from app.schemas.trip import GenerateDayRequest, GenerateRequest

logger = logging.getLogger(__name__)


def draft_state(req: GenerateRequest, reason: str, schedule_report: dict | None = None) -> dict:
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


def _generate_drafts(
    req: GenerateRequest, feedback: str, context: dict, ref_pool: ReferencePool, schedule_report: dict
) -> tuple[list[dict], list[dict], list[str]]:
    """第一段（草案生成）：LLM 一次生成 + 参考落地 + 矛盾点位出局。

    多日走 llm_open_trip（整体失败逐日落成「待研究」空草案），单日走
    llm_open_day；命中参考资料的点位由 ref_pool 落地权威字段，未命中交
    存在性解析器补真实坐标，解析到别处的点位在这里删掉（G5）。
    返回 (plans, raw_suggestions, research_errors)。
    """
    plans: list[dict] = []
    used: set[str] = set()
    raw_suggestions: list[dict] = []
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
        # 结构校验：LLM 可能返回非 dict 项或无 poi_name 的脏项，必须在
        # 落地前过滤，否则 format_output 的 item.get / TripItem(**item) 崩溃。
        plan["items"] = filter_plan_items(plan.get("items"))
        for item in plan["items"]:
            ground_item(item, city=req.city, ref_pool=ref_pool)
        # 与本次行程矛盾的点位（解析到别处 / 权威源否证）在这里出局，剩下
        # 的"未判定"项保留——09-19 复评：免费源的"查不到"不足以删用户的点。
        plan["items"] = drop_refuted_items(plan["items"], city=req.city, report=schedule_report)
        for item in plan["items"]:
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
    return plans, raw_suggestions, research_errors


def _postprocess_drafts(
    req: GenerateRequest,
    plans: list[dict],
    raw_suggestions: list[dict],
    candidates: list[dict] | None,
    foods: list[dict] | None,
    context_hotels: list[dict] | None,
    ref_pool: ReferencePool,
    schedule_report: dict,
) -> list[dict]:
    """第二段（后处理）：跨天去重 / 酒店摊铺 / 0 价补水 / 备选池地板 / 遥测。

    不改变「LLM 决定内容」契约，只做确定性语义补齐；返回更新后的
    raw_suggestions。
    """
    # 跨天去重：多日一次生成时 used 只在 grounding 后累计，模型可能跨天重复。
    # 共享双通道判重：归一化同名 + 落地后同类型近坐标（<80m），名称变体
    # （"圣家堂" vs "圣家堂大教堂"）由坐标通道兜底；酒店豁免（摊铺语义）。
    dropped = drop_cross_day_duplicates(plans)
    for row in dropped:
        record_event("decision", "duplicate_cross_day_dropped", metadata=row)
    # 后处理：酒店摊晚 + 0 价覆盖 + 备选池地板（不改变「LLM 决定内容」契约）
    stay_n = stay_nights(req.days)
    hotels_added = spread_hotels(plans, stay_n)
    price_lookup: dict[str, dict] = {}
    for poi in (candidates or []) + (foods or []) + (context_hotels or []):
        name = str(poi.get("name") or "").strip()
        if name:
            price_lookup[name] = poi
    filled_costs = fill_zero_costs(plans, price_lookup)
    # 备选池补全必须看到酒店/体验候选，否则对应 tab 会空
    activities = activity_floor(req.city)
    extra_pool = (candidates or []) + (foods or []) + (context_hotels or []) + activities
    raw_suggestions = floor_suggestions(raw_suggestions, extra_pool)
    if hotels_added or filled_costs:
        schedule_report["postprocess"] = {
            "hotels_spread": hotels_added,
            "costs_filled": filled_costs,
        }
        record_event("decision", "postprocess", metadata=schedule_report["postprocess"])
    if ref_pool:
        # 引用式生成遥测：命中率/refs 有效率/资料利用率（评测与观测共用）。
        schedule_report["reference_stats"] = dict(ref_pool.stats)
        record_event("decision", "reference_usage", metadata=dict(ref_pool.stats))
    return raw_suggestions


def generate_open_plans(
    req: GenerateRequest,
    feedback: str,
    context_hotels: list[dict] | None,
    candidates: list[dict] | None = None,
    foods: list[dict] | None = None,
    weather: list[dict] | None = None,
) -> tuple[dict | None, list[str]]:
    """开放模式生成（三段编排：草案生成 → 后处理 → 失败即降级）。

    返回 ``(状态增量 | None, 研究错误)``：整体失败时错误必须跟着返回——调用方
    只剩一个 ``None`` 可看，就只能写一句"重试耗尽"，把 deadline / 配额这类真因
    盖在底下（夜里排障的人会照着那句话去查研究层）。

    引用式生成：本地知识库检索结果（candidates/foods）作为带编号参考
    资料注入 Prompt，模型选点输出 refs 引用，生成后由 ReferencePool 落地
    为权威字段并回填真实来源；未命中资料的地点由 local_ground 补真实坐标
    并保持 unverified。返回 AgentState 增量；开放研究整体失败（所有天均为
    空草案）时返回 None，由调用方降级到候选池约束链路或草案。
    """
    schedule_report: dict = {"destination_status": "draft_only", "research_mode": "open"}
    try:
        context = {
            "hotels": context_hotels or [],
            "candidates": candidates or [],
            "foods": foods or [],
            "weather": weather or [],
        }
        ref_pool = ReferencePool(context)
        plans, raw_suggestions, research_errors = _generate_drafts(req, feedback, context, ref_pool, schedule_report)
        if research_errors and not any(p.get("items") for p in plans):
            # 整段开放研究失败：交由调用方降级，避免把候选库城市打成空草案。
            return None, research_errors
        raw_suggestions = _postprocess_drafts(
            req, plans, raw_suggestions, candidates, foods, context_hotels, ref_pool, schedule_report
        )
        # 空池不算 error，但也不能算研究过（P4）：三个候选域全空时唯一的可能
        # 是"模型凭自身知识写完了"——打成 researched 会让零外部证据的产出
        # 看起来像经过核实。OTM key 未配、城市中心缺失、联网预算耗尽都会到这里。
        empty_domains = [
            name
            for name, rows in (("candidates", candidates), ("foods", foods), ("hotels", context_hotels))
            if not rows
        ]
        if empty_domains:
            schedule_report["empty_domains"] = empty_domains
        researched = not research_errors and len(empty_domains) < 3
        schedule_report["destination_status"] = "researched" if researched else "draft_only"
        schedule_report["open_research"] = True
        if research_errors:
            schedule_report["research_errors"] = research_errors
        return (
            {
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
            },
            research_errors,
        )
    except Exception as exc:
        logger.warning("open generation crashed for %s: %s", req.city, exc)
        return None, [f"开放研究异常：{exc}"]
