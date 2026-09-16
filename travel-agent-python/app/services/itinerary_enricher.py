"""生成后的可选富化（移植自 Java `ItineraryEnricher`）。

三段彼此独立的增强，**任何一段失败都只降级、不影响已生成好的行程**：
A. AI 管家讲解 → `itinerary_main.plan_note`
B. 景点详细介绍 → `itinerary_item.intro`（按 8 个一批，避免 max_tokens 截断致整批解析失败）
C. 备选池介绍补写 → 重写 `itinerary_main.suggestions_json`

三条实现纪律（都是并发写回踩过的坑）：
- 一律**单列 UPDATE**，不用陈旧实体整行回写：富化动辄几十秒，期间用户可能正在编辑同一行程；
- B 段按 `poi_name` 批量覆盖同名列（不按 day_id 精确定位），与 Java 一致；
- 收尾无条件按 `(userId, itineraryId)` 精确失效详情缓存（不是全量 clear，避免一次生成
  把所有用户的详情缓存击穿）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select, update

from app.agent import run_butler_note, run_poi_intros
from app.db.models import ItineraryDay, ItineraryItem, ItineraryMain
from app.db.session import session_scope
from app.schemas.trip import Suggestion
from app.services import itinerary_query

logger = logging.getLogger(__name__)

INTRO_BATCH_SIZE = 8
MIN_SUGGESTION_INTRO = 50
BUTLER_PREVIEW = 60


def persist_suggestions(itinerary_id: int, suggestions: list[Suggestion] | list[dict] | None) -> None:
    """落库行程级备选池（「发现更多」）；失败只记日志。"""
    if not suggestions:
        return
    rows = [
        suggestion.model_dump(mode="json", by_alias=True) if hasattr(suggestion, "model_dump") else dict(suggestion)
        for suggestion in suggestions
    ]
    try:
        payload = json.dumps(rows, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("persist suggestions failed for %s: %s", itinerary_id, exc)
        return
    with session_scope() as session:
        session.execute(update(ItineraryMain).where(ItineraryMain.id == itinerary_id).values(suggestions_json=payload))


def enrich_itinerary(user_id: int, itinerary_id: int, request: Any) -> None:
    """生成完成后的富化主入口（编排层提交到富化线程池执行）。"""
    with session_scope() as session:
        main = session.get(ItineraryMain, itinerary_id)
    if main is None:
        return
    _write_butler_note(user_id, main, request, itinerary_id)
    _fill_item_intros(user_id, main, request, itinerary_id)
    try:
        _enrich_suggestion_intros(main, request, itinerary_id)
    except Exception as exc:
        logger.warning("suggestion intros failed for %s: %s", itinerary_id, exc)
    itinerary_query.evict_detail(user_id, itinerary_id)


def _plans_for_butler(itinerary_id: int) -> list[dict[str, Any]]:
    """管家讲解的行程摘要：每天 {day_no, items:[点位名]}（键是 snake_case，Python 契约）。"""
    with session_scope() as session:
        days = (
            session.execute(
                select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id).order_by(ItineraryDay.day_no)
            )
            .scalars()
            .all()
        )
        plans: list[dict[str, Any]] = []
        for day in days:
            names = [
                name
                for name in session.execute(
                    select(ItineraryItem.poi_name).where(ItineraryItem.day_id == day.id).order_by(ItineraryItem.sort_no)
                )
                .scalars()
                .all()
                if name and name.strip()
            ]
            if names:
                plans.append({"day_no": day.day_no, "items": names})
    return plans


def _write_butler_note(user_id: int, main: ItineraryMain, request: Any, itinerary_id: int) -> None:
    plans = _plans_for_butler(itinerary_id)
    if not plans:
        return
    try:
        payload = {
            "city": main.city,
            "days": main.days,
            "persons": main.persons if main.persons is not None else 1,
            # 偏好列本身是逗号拼接串；Java 也是原样传字符串，
            # `run_butler_note` 内部 `"、".join(str)` 会逐字符连接——这是迁移前就有的形状，
            # 不在迁移里改提示词口径（会动到评测基线）。
            "preferences": main.preferences or "",
            "hotel_tier": main.hotel_tier or "",
            "region_hint": getattr(request, "region_hint", None) or "",
            "budget": "" if main.budget is None else main.budget,
            "requirements": getattr(request, "requirements", None) or "",
            "intent": resolve_intent(request),
            "plans": plans,
            "validation_log": None,
        }
        note = run_butler_note(payload) or ""
        if not note.strip():
            return
        with session_scope() as session:
            session.execute(update(ItineraryMain).where(ItineraryMain.id == itinerary_id).values(plan_note=note))
        from app.services import generation_events

        generation_events.butler_note(itinerary_id, len(note), note[:BUTLER_PREVIEW])
    except Exception as exc:
        logger.warning("butler note failed for %s: %s", itinerary_id, exc)
        _publish_degraded(itinerary_id, "butler", str(exc), "跳过讲解")


def _fill_item_intros(user_id: int, main: ItineraryMain, request: Any, itinerary_id: int) -> None:
    with session_scope() as session:
        names = list(
            dict.fromkeys(
                name
                for name in session.execute(
                    select(ItineraryItem.poi_name).where(ItineraryItem.itinerary_id == itinerary_id)
                )
                .scalars()
                .all()
                if name and name.strip()
            )
        )
    intros: dict[str, str] = {}
    try:
        for start in range(0, len(names), INTRO_BATCH_SIZE):
            chunk = names[start : start + INTRO_BATCH_SIZE]
            try:
                intros.update(run_poi_intros(main.city, chunk, resolve_intent(request)) or {})
            except Exception as exc:
                logger.warning("poi intros batch failed for %s: %s", itinerary_id, exc)
        with session_scope() as session:
            for name, intro in intros.items():
                if intro and intro.strip():
                    session.execute(
                        update(ItineraryItem)
                        .where(ItineraryItem.itinerary_id == itinerary_id, ItineraryItem.poi_name == name)
                        .values(intro=intro)
                    )
    except Exception as exc:
        logger.warning("poi intros failed for %s: %s", itinerary_id, exc)
        _publish_degraded(itinerary_id, "poi_intros", str(exc), "跳过景点介绍")


def _enrich_suggestion_intros(main: ItineraryMain, request: Any, itinerary_id: int) -> None:
    with session_scope() as session:
        fresh = session.get(ItineraryMain, itinerary_id)  # 用最新行，避免拿 finish 时的陈旧快照
        raw = fresh.suggestions_json if fresh is not None else None
    if not raw or not raw.strip():
        return
    try:
        rows = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("suggestions json parse failed for %s: %s", itinerary_id, exc)
        return
    if not isinstance(rows, list) or not rows:
        return

    def needs_intro(row: dict) -> bool:
        intro = row.get("intro")
        return intro is None or not str(intro).strip() or len(str(intro)) < MIN_SUGGESTION_INTRO

    # 只补「没有有效介绍」的行：模型单次生成的 60-100 字亮点遵循度不足，短于 50 字视为无介绍
    names = list(
        dict.fromkeys(
            str(row.get("name"))
            for row in rows
            if isinstance(row, dict)
            and needs_intro(row)
            and row.get("name") is not None
            and str(row.get("name")).strip()
            and str(row.get("name")) != "null"
        )
    )

    intros: dict[str, str] = {}
    for start in range(0, len(names), INTRO_BATCH_SIZE):
        try:
            intros.update(
                run_poi_intros(main.city, names[start : start + INTRO_BATCH_SIZE], resolve_intent(request)) or {}
            )
        except Exception as exc:
            logger.warning("suggestion intros batch failed for %s: %s", itinerary_id, exc)
    if not intros:
        return

    changed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        intro = intros.get(str(name)) if name is not None else None
        if intro and intro.strip():
            row["intro"] = intro
            changed = True
    if not changed:
        return
    try:
        with session_scope() as session:
            session.execute(
                update(ItineraryMain)
                .where(ItineraryMain.id == itinerary_id)
                .values(suggestions_json=json.dumps(rows, ensure_ascii=False))
            )
    except (TypeError, ValueError) as exc:
        logger.warning("suggestions json write failed for %s: %s", itinerary_id, exc)


def resolve_intent(request: Any) -> str:
    """意图兜底：未填 intent 时用 requirements 作为意图（M1 契约）。"""
    if request is None:
        return ""
    intent = getattr(request, "intent", None)
    if intent and intent.strip():
        return intent.strip()
    return getattr(request, "requirements", None) or ""


def _publish_degraded(itinerary_id: int, scope: str, reason: str, fallback: str) -> None:
    # 延迟导入：富化 → 事件 → trace，避免模块级环依赖
    from app.services import generation_events

    generation_events.degraded(itinerary_id, scope, reason, fallback)
