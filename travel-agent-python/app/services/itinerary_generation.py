"""行程生成编排（移植自 Java `ItineraryGenerationService` + `ItineraryAsyncPlanner`）。

结构上照 Java 的分层：本文件只做**流程编排**——幂等原语在 `generation_gate`、事务写入在
`day_persistence`、富化在 `itinerary_enricher`、事件在 `generation_events`。

同进程化后的三处必要差异（都不是"顺手改"，是换了运行模型就必须跟着改）：

1. `@Async("generationExecutor")`（core2/max4/queue20/AbortPolicy）→ `_SlotExecutor`：
   Python 的 `ThreadPoolExecutor` 队列无界，直接用会把"生成队列已满 → 429"这条用户可见
   语义丢掉，所以用信号量把「在跑 + 排队」的总量卡在 24，提交点满即抛 `TaskRejected`。
2. agent 调用不再走 HTTP，但**每一次生成仍单独包 `observe_run`/`use_scene`**：
   `RunLimits`（90s deadline、LLM/token/检索/重规划预算）与 trace 全靠 ContextVar，
   不包就等于静默关掉预算与遥测。ContextVar 只能在同一 Context 里 set/reset，
   所以进入点必须在工作线程内部。
3. `run_plan_context` 今天就是**不带 trace** 被调用的（`/v1/plan-context` 只有 `@scene`），
   因此研究事件的 `data` 里没有 `runId`。这里保持不包，避免直调后凭空多出前端会看见的键。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import update

from app.agent import observe_run, run_generate_day, run_generate_trip_stream, run_plan_context, use_scene
from app.common import cache_store
from app.common.envelope import ApiError
from app.common.task_pool import SlotExecutor, TaskRejected
from app.db.models import ItineraryDay, ItineraryMain
from app.db.session import session_scope
from app.schemas.business.itinerary import GenerateTripRequest
from app.schemas.stream_events import StreamEvent
from app.schemas.trip import MAX_TRIP_DAYS, DailyPlan, GenerateDayRequest
from app.services import (
    budget_engine,
    day_persistence,
    generation_events,
    generation_gate,
    itinerary_enricher,
    itinerary_query,
    itinerary_version,
)
from app.services import preferences as preferences_service

logger = logging.getLogger(__name__)

MAX_STREAM_CONTRACT_ERRORS = 3
KNOWN_STREAM_TYPES = ("start", "day", "day_patch", "suggestions", "done", "error")

# Java AsyncConfig：generationExecutor core2/max4/queue20、enricherExecutor core1/max2/queue10
_GENERATION_SLOTS = 4 + 20
_ENRICHER_SLOTS = 2 + 10


# 与池抛出的异常同一个类；池本身共用 app.common.task_pool（导出任务也用同一个原语）
_SlotExecutor = SlotExecutor


generation_pool = _SlotExecutor("travel-generation", 4, _GENERATION_SLOTS)
enricher_pool = _SlotExecutor("travel-enricher", 2, _ENRICHER_SLOTS)


@dataclass
class GenerateCommand:
    """编排层需要的生成参数（Java 侧就是 `GenerateRequest` DTO）。

    `stay_nights` 在建壳时已归一（None → max(days-1, 0)），指纹与逐日 `needs_hotel`
    都读它，因此必须在**归一之后**再构造一次。
    """

    city: str
    days: int
    persons: int
    stay_nights: int
    start_date: date | None = None
    end_date: date | None = None
    budget: Decimal | None = None
    preferences: list[str] = field(default_factory=list)
    hotel_tier: str | None = None
    region_hint: str | None = None
    requirements: str | None = None
    intent: str | None = None

    def resolved_intent(self) -> str:
        """意图兜底：未填 intent 时用 requirements（M1 契约，与 Java `resolveIntent` 一致）。"""
        if self.intent and self.intent.strip():
            return self.intent.strip()
        return self.requirements or ""


def submit_planning(user_id: int, itinerary_id: int, command: GenerateCommand) -> None:
    """把一次生成排进有界池；满了直接抛 `TaskRejected`（端点转 429）。"""
    generation_pool.submit(plan_days, user_id, itinerary_id, command, None)


# ---------- 编排主体（工作线程内） ----------


def plan_days(user_id: int, itinerary_id: int, command: GenerateCommand, context: dict[str, Any] | None = None) -> None:
    try:
        if not _shell_exists(itinerary_id):
            logger.error("itinerary shell %s not visible before planning; abort", itinerary_id)
            raise ApiError(500, "行程壳数据不存在，无法开始生成")
        day_persistence.mark_generating(itinerary_id)

        used_names: list[str] = []
        chosen_hotel: str | None = None
        first_day_suggestions: list[Any] | None = None
        fingerprint = generation_gate.request_fingerprint(command)
        if context is None:
            # 不包 observe_run：与迁移前的 /v1/plan-context 口径一致（研究事件不带 runId）。
            # start_date+days 供城市级天气一次取整趟预报窗（C3.1）；无日期自然为 None。
            context = run_plan_context(
                command.city,
                command.preferences,
                itinerary_id=itinerary_id,
                start_date=command.start_date.isoformat() if command.start_date else None,
                days=command.days,
            )

        suggestions_persisted = False
        unfinished = day_persistence.unfinished_day_nos(itinerary_id)
        fresh_trip = len(unfinished) >= command.days
        if fresh_trip:
            try:
                suggestions_persisted = _plan_whole_trip(user_id, itinerary_id, command, context, fingerprint)
            except Exception as stream_exc:
                logger.warning("whole-trip stream failed for itinerary %s: %s", itinerary_id, stream_exc)

        for day_no in range(1, command.days + 1):
            action_id = f"day-{itinerary_id}-{day_no}"
            if not generation_gate.try_day_lock(itinerary_id, day_no):
                logger.warning("day lock busy, skip itinerary %s day %s", itinerary_id, day_no)
                continue
            try:
                day = day_persistence.find_day(itinerary_id, day_no)
                if day is None:
                    raise ApiError(500, "行程日不存在")
                if day.generation_status == "SUCCEEDED":
                    # 已成功的天只做幂等校验与跨天去重登记，不重写（也跳过收尾失效：无变更）
                    generation_gate.verify_action(day, action_id, fingerprint)
                    day_persistence.append_existing_items(day.id, used_names)
                    if chosen_hotel is None:
                        chosen_hotel = day_persistence.existing_hotel(day.id)
                    continue
                day_persistence.mark_running(day.id, action_id, fingerprint)
                generation_events.day_start(itinerary_id, day_no)
                try:
                    plan = _generate_day_with_trace(
                        itinerary_id, command, context, day_no, used_names, chosen_hotel, action_id, fingerprint
                    )
                    if day_no == 1:
                        first_day_suggestions = plan.suggestions
                        day_persistence.set_trip_theme(itinerary_id, plan.trip_theme)
                except Exception as day_exc:
                    day_persistence.mark_failed(day.id, action_id, fingerprint, str(day_exc) or None)
                    generation_events.degraded(itinerary_id, f"day_{day_no}", str(day_exc), "待重试")
                    raise
                persisted = day_persistence.find_day(itinerary_id, day_no)
                if persisted is not None:
                    day_persistence.append_existing_items(persisted.id, used_names)
                    if chosen_hotel is None:
                        chosen_hotel = day_persistence.existing_hotel(persisted.id)
            finally:
                generation_gate.release_day_lock(itinerary_id, day_no)
            itinerary_query.evict_detail(user_id, itinerary_id)
            _submit_budget_recalculate(itinerary_id)

        if not suggestions_persisted:
            itinerary_enricher.persist_suggestions(itinerary_id, first_day_suggestions)
        _finish(user_id, itinerary_id, command)
    except Exception as exc:
        logger.error("async planning failed for itinerary %s", itinerary_id, exc_info=True)
        generation_events.error(itinerary_id, "AGENT_ERROR", str(exc), True)
        day_persistence.fail_trip(itinerary_id, str(exc) or None)
        itinerary_query.evict_detail(user_id, itinerary_id)


def _generate_day_with_trace(
    itinerary_id: int,
    command: GenerateCommand,
    context: dict[str, Any],
    day_no: int,
    used_names: list[str],
    chosen_hotel: str | None,
    action_id: str,
    fingerprint: str,
) -> DailyPlan:
    request = GenerateDayRequest(
        city=command.city,
        persons=command.persons,
        budget=None if command.budget is None else float(command.budget),
        start_date=None if command.start_date is None else str(command.start_date),
        day_no=day_no,
        used_names=list(used_names),
        hotel_tier=command.hotel_tier,
        chosen_hotel=chosen_hotel,
        needs_hotel=day_no <= command.stay_nights,
        requirements=command.requirements,
        intent=command.resolved_intent(),
        region_hint=command.region_hint,
        request_id=f"itinerary-{itinerary_id}",
        action_id=action_id,
        context=context,
    )
    # 注意：**不传 days**。`trip_graph` 里 `days>1` 会关掉单日反思重试（那是给整段流式用的），
    # 逐日修复路径必须保留重试。Java 也是这么发的（generate-day payload 无 days 键）。
    with use_scene("generate"), observe_run(request_id=f"itinerary-{itinerary_id}", action_id=action_id):
        plan = run_generate_day(request)
    day_persistence.persist(itinerary_id, command, day_no, plan, action_id, fingerprint)
    generation_events.day_done(itinerary_id, day_no, plan.theme, len(plan.items or []), plan.note)
    return plan


# ---------- 整段流式（一次 LLM 生成全程，边流边落库） ----------

_stream_events = TypeAdapter(StreamEvent)


def _plan_whole_trip(
    user_id: int, itinerary_id: int, command: GenerateCommand, context: dict[str, Any], fingerprint: str
) -> bool:
    request = GenerateDayRequest(
        city=command.city,
        persons=command.persons,
        budget=None if command.budget is None else float(command.budget),
        start_date=None if command.start_date is None else str(command.start_date),
        day_no=1,
        days=command.days,
        used_names=[],
        hotel_tier=command.hotel_tier,
        chosen_hotel=None,
        needs_hotel=command.stay_nights > 0,
        requirements=command.requirements,
        intent=command.resolved_intent(),
        region_hint=command.region_hint,
        request_id=f"itinerary-{itinerary_id}",
        context=context,
    )
    logger.info("whole-trip stream generating itinerary %s (%s days)", itinerary_id, command.days)
    suggestions_done = False
    done_seen = False
    contract_errors = 0
    # 与 /v1/generate-stream 同：只落 trace，不把 runId 回填进事件（消费者看到的键不变）
    with use_scene("generate"), observe_run(request_id=f"itinerary-{itinerary_id}"):
        try:
            for event in run_generate_trip_stream(request):
                event_type = str(event.get("type") or "")
                if event_type not in KNOWN_STREAM_TYPES:
                    # 未知类型 = 前向兼容的附加事件：忽略且不计数（增量演进不算协议破坏）
                    logger.debug("stream event with unknown type ignored for %s: %s", itinerary_id, event_type)
                    continue
                try:
                    _stream_events.validate_python(event)
                except ValidationError as exc:
                    contract_errors += 1
                    logger.warning(
                        "stream event rejected by contract for %s (#%s): type=%s %s",
                        itinerary_id,
                        contract_errors,
                        event_type,
                        "; ".join(str(item.get("msg")) for item in exc.errors()[:5]),
                    )
                    if contract_errors > MAX_STREAM_CONTRACT_ERRORS:
                        raise ApiError(502, "行程流事件契约校验失败") from exc
                    continue
                if event_type in ("day", "day_patch"):
                    plan_node = event.get("plan")
                    if not plan_node:
                        continue
                    day_no = int(plan_node.get("dayNo") or 0)
                    if day_no < 1 or day_no > command.days:
                        logger.warning("stream day_no out of range for %s: %s", itinerary_id, day_no)
                        continue
                    try:
                        _persist_stream_day(
                            user_id,
                            itinerary_id,
                            command,
                            day_no,
                            plan_node,
                            fingerprint,
                            overwrite=event_type == "day_patch",
                        )
                    except Exception as day_exc:
                        logger.warning("stream day %s persist failed for %s: %s", day_no, itinerary_id, day_exc)
                elif event_type == "suggestions":
                    rows = event.get("items") or []
                    if not rows:
                        continue
                    try:
                        itinerary_enricher.persist_suggestions(itinerary_id, [dict(row) for row in rows])
                        suggestions_done = True
                    except Exception as suggest_exc:
                        logger.warning("stream suggestions persist failed for %s: %s", itinerary_id, suggest_exc)
                elif event_type == "done":
                    done_seen = True
                    day_persistence.set_trip_theme(itinerary_id, event.get("tripTheme"))
                    logger.info(
                        "whole-trip stream done for %s: emitted %s of %s days, complete=%s",
                        itinerary_id,
                        event.get("daysEmitted"),
                        command.days,
                        event.get("complete"),
                    )
                elif event_type == "error":
                    logger.warning("whole-trip stream error for %s: %s", itinerary_id, event.get("message"))
        except Exception as stream_exc:
            if done_seen:
                # done 之后连接收尾的残余异常（如 Premature EOF）不影响结果：缺天交给逐日循环
                logger.info("stream closed after done for itinerary %s (%s), ignoring", itinerary_id, stream_exc)
            else:
                raise
    if contract_errors:
        logger.warning(
            "whole-trip stream for %s finished with %s contract violation(s); "
            "affected days fall back to per-day generation",
            itinerary_id,
            contract_errors,
        )
    return suggestions_done


def _persist_stream_day(
    user_id: int,
    itinerary_id: int,
    command: GenerateCommand,
    day_no: int,
    plan_node: dict[str, Any],
    fingerprint: str,
    overwrite: bool,
) -> None:
    action_id = f"day-{itinerary_id}-{day_no}"
    if not generation_gate.try_day_lock(itinerary_id, day_no):
        logger.warning("stream day lock busy, skip itinerary %s day %s", itinerary_id, day_no)
        return
    try:
        day = day_persistence.find_day(itinerary_id, day_no)
        if day is None:
            raise ApiError(500, "行程日不存在")
        generation_gate.verify_action(day, action_id, fingerprint)
        if day.generation_status != "SUCCEEDED" or overwrite:
            day_persistence.mark_running(day.id, action_id, fingerprint)
            generation_events.day_start(itinerary_id, day_no)
            plan = DailyPlan.model_validate(plan_node)
            day_persistence.persist(
                itinerary_id, command, day_no, plan, action_id, fingerprint, allow_overwrite=overwrite
            )
            generation_events.day_done(itinerary_id, day_no, plan.theme, len(plan.items or []), plan.note)
            itinerary_query.evict_detail(user_id, itinerary_id)
            _submit_budget_recalculate(itinerary_id)
    finally:
        generation_gate.release_day_lock(itinerary_id, day_no)


# ---------- 终态 ----------


def _finish(user_id: int, itinerary_id: int, command: GenerateCommand) -> None:
    with session_scope() as session:
        main = session.get(ItineraryMain, itinerary_id)
    if main is None:
        itinerary_query.evict_detail(user_id, itinerary_id)
        return
    all_succeeded = day_persistence.all_days_succeeded(itinerary_id)
    day_persistence.complete_trip(itinerary_id, all_succeeded)
    version_id: int | None = None
    try:
        snapshot = itinerary_version.create_snapshot(user_id, itinerary_id, "generate", "行程生成完成")
        if isinstance(snapshot.get("id"), int):
            version_id = snapshot["id"]
    except Exception as snapshot_error:
        logger.warning("version snapshot failed for %s: %s", itinerary_id, snapshot_error)
    generation_events.complete(
        itinerary_id,
        "COMPLETED" if all_succeeded else "PARTIAL",
        main.days,
        day_persistence.unfinished_day_nos(itinerary_id),
        version_id,
    )
    _submit_budget_recalculate(itinerary_id)
    try:
        enricher_pool.submit(itinerary_enricher.enrich_itinerary, user_id, itinerary_id, command)
    except TaskRejected as rejected:
        logger.warning("itinerary enrichment rejected for %s: %s", itinerary_id, rejected)
    itinerary_query.evict_detail(user_id, itinerary_id)


def _submit_budget_recalculate(itinerary_id: int) -> None:
    """预算重算移出落库事务，交给富化池；被拒只 warn（后续天/终态还会再算）。"""
    try:
        enricher_pool.submit(budget_engine.recalculate, itinerary_id)
    except TaskRejected as rejected:
        logger.warning("budget recalculate rejected for %s: %s", itinerary_id, rejected)


def _shell_exists(itinerary_id: int) -> bool:
    with session_scope() as session:
        return session.get(ItineraryMain, itinerary_id) is not None


# ---------- 请求入口（Java `ItineraryGenerationService.generate`） ----------

# Java 的 `\p{IsHan}` 覆盖全部汉字区块，这里用 BMP 常用汉字区近似；
# 差异只出现在生僻扩展区汉字（本项目的城市名不会用到），不为它引第三方 regex 库。
_CITY_RE = re.compile(r"^[一-鿿A-Za-z0-9][一-鿿A-Za-z0-9\s·'’\-()（）]{0,30}$")
MAX_CITY_LENGTH = 32
QUEUE_FULL_NOTE = "生成失败：系统繁忙，生成队列已满"


IDEMPOTENCY_TTL_SECONDS = 600
_IDEM_NAMESPACE = "idem_generate"


def _reserve_idempotent(user_id: int, key: str | None) -> int | None:
    """占幂等键；已占用时返回先前那次生成创建的 itinerary_id。

    语义（backlog「被重复请求咬过」）：同一个 user 的同一个幂等键在 TTL 内
    只会建壳一次——网络层重试 / 双击拿回的是**同一个行程**（可能仍在生成、
    已完成或已失败），而不是第二份行程第二份 LLM 账单。想重新生成就不带键
    或换键（那是用户的显式新意图）。
    """
    normalized = (key or "").strip()
    if not normalized:
        return None
    cache_key = f"{user_id}:{normalized[:128]}"
    if cache_store.reserve(_IDEM_NAMESPACE, cache_key, None, IDEMPOTENCY_TTL_SECONDS):
        return None  # 首次占位（值在建壳成功后回填）
    existing = cache_store.get_json(_IDEM_NAMESPACE, cache_key)
    return int(existing) if isinstance(existing, int) else None


def _replay_if_known(user_id: int, replay_id: int | None, idempotency_key: str | None) -> dict[str, Any] | None:
    """幂等重放：占位值指向的行程存在且属于本人时，回放它的详情。

    占位值在首次建壳成功后回填；理论上此处读不到值只在「占位后进程崩溃
    未回填」的窗口出现——此时释放键并降级为新一次生成（宁重复、不 500）。
    """
    if replay_id is None:
        return None
    with session_scope() as session:
        exists = session.get(ItineraryMain, replay_id)
    if exists is not None and exists.user_id == user_id:
        return itinerary_query.detail(user_id, replay_id)
    cache_store.delete(_IDEM_NAMESPACE, f"{user_id}:{(idempotency_key or '').strip()[:128]}")
    return None


def generate(user_id: int, body: GenerateTripRequest, idempotency_key: str | None = None) -> dict[str, Any]:
    """建壳 → 逐日异步生成 → 立即返回可轮询的初始详情（status=1）。

    `idempotency_key`（来自 X-Idempotency-Key 头，可选）：TTL 内同键重试
    返回既有行程，不重复建壳（见 _reserve_idempotent）。
    """
    command = _validate(body)
    replay = _replay_if_known(user_id, _reserve_idempotent(user_id, idempotency_key), idempotency_key)
    if replay is not None:
        return replay
    with session_scope() as session:
        main = ItineraryMain(
            user_id=user_id,
            title=f"{command.city}{command.days}日游",
            city=command.city,
            start_date=command.start_date,
            end_date=command.end_date,
            days=command.days,
            persons=command.persons,
            budget=command.budget,
            preferences=",".join(command.preferences) if command.preferences else None,
            hotel_tier=command.hotel_tier,
            stay_nights=command.stay_nights,
            status=1,
            # 显式状态机：建壳即入 GENERATING 并记开始时间，恢复任务据此识别生成中/僵尸
            gen_state="GENERATING",
            gen_started_at=datetime.now(),
        )
        session.add(main)
        session.flush()
        itinerary_id = main.id
        for day_no in range(1, command.days + 1):
            session.add(
                ItineraryDay(
                    itinerary_id=itinerary_id,
                    day_no=day_no,
                    city=command.city,
                    travel_date=None if command.start_date is None else command.start_date + timedelta(days=day_no - 1),
                    generation_status="PENDING",
                )
            )
    preferences_service.record_preferences(user_id, command.preferences)
    # 壳已提交：这里若抛 500，submit_planning 就跑不到，留下一个 GENERATING 空壳等 5 分钟续跑扫描。
    itinerary_version.record_snapshot_or_log(user_id, itinerary_id, "create", "创建行程草稿")
    # 建壳成功后回填幂等占位值：此后同键重试拿回这个 itinerary_id
    if idempotency_key and idempotency_key.strip():
        cache_store.set_json(
            _IDEM_NAMESPACE, f"{user_id}:{idempotency_key.strip()[:128]}", itinerary_id, IDEMPOTENCY_TTL_SECONDS
        )

    try:
        submit_planning(user_id, itinerary_id, command)
    except TaskRejected as exc:
        # 生成池满：快速失败返回 429，绝不退回请求线程同步生成。
        # 壳数据置为失败终态（该状态不满足自动续跑条件），用户可见并可重新创建。
        with session_scope() as session:
            session.execute(
                update(ItineraryMain)
                .where(ItineraryMain.id == itinerary_id)
                .values(status=3, gen_state="FAILED", plan_note=QUEUE_FULL_NOTE)
            )
        itinerary_query.evict_detail(user_id, itinerary_id)
        # 幂等键随本次明确失败一并释放：4xx 是"结果已知"的失败，用户重试
        # 期望的是新一次尝试，而不是被回放到同一个 FAILED 壳。幂等只防
        # "结果未知"（网络超时/断连）的重复——那条路径在 try 块之外，不受影响。
        if idempotency_key and idempotency_key.strip():
            cache_store.delete(_IDEM_NAMESPACE, f"{user_id}:{idempotency_key.strip()[:128]}")
        raise ApiError(429, "行程生成任务已满，系统繁忙，请稍后再试") from exc
    return itinerary_query.detail(user_id, itinerary_id)


def _validate(body: GenerateTripRequest) -> GenerateCommand:
    """校验阶梯与 Java 一致：先 DTO（Bean Validation），再服务层规则。"""
    if not body.city or not body.city.strip():
        raise ApiError(400, "目的地不能为空")
    if body.days is None:
        raise ApiError(400, "出行天数不能为空")
    if body.days < 1:
        raise ApiError(400, "天数至少为 1 天")
    if body.days > MAX_TRIP_DAYS:
        raise ApiError(400, "天数最多为 7 天")
    if body.persons is not None and body.persons < 1:
        raise ApiError(400, "人数至少为 1 人")
    if body.persons is not None and body.persons > 20:
        raise ApiError(400, "人数最多为 20 人")
    if body.stayNights is not None and body.stayNights < 0:
        raise ApiError(400, "住宿晚数不能为负数")
    if body.stayNights is not None and body.stayNights > MAX_TRIP_DAYS:
        raise ApiError(400, "住宿晚数最多为 7 晚")
    if body.budget is not None and body.budget < 0:
        raise ApiError(400, "预算不能为负数")
    if body.intent is not None and len(body.intent) > 800:
        raise ApiError(400, "旅行意图最多 800 字")

    city = body.city.strip()
    if len(city) > MAX_CITY_LENGTH or not _CITY_RE.match(city):
        raise ApiError(400, "目的地名称格式不正确，请输入城市或景点所在城市")
    persons = body.persons if body.persons is not None else 1
    if persons < 1 or persons > 20:
        raise ApiError(400, "出行人数必须在 1 到 20 人之间")
    if body.startDate and body.endDate:
        if body.endDate < body.startDate:
            raise ApiError(400, "结束日期不能早于开始日期")
        if (body.endDate - body.startDate).days + 1 != body.days:
            raise ApiError(400, "日期范围与行程天数不一致")
    stay_nights = body.stayNights if body.stayNights is not None else max(body.days - 1, 0)
    if stay_nights < 0 or stay_nights > body.days:
        raise ApiError(400, "住宿晚数必须在 0 到行程天数之间")

    return GenerateCommand(
        city=city,
        days=body.days,
        persons=persons,
        stay_nights=stay_nights,
        start_date=body.startDate,
        end_date=body.endDate,
        budget=body.budget,
        preferences=body.preferences or [],
        hotel_tier=body.hotelTier,
        region_hint=body.regionHint,
        requirements=body.requirements,
        intent=body.intent,
    )
