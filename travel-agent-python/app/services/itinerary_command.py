"""行程项写路径（移植自 Java `ItineraryCommandService` 的 items CRUD 与排序）。

与 Java 一致的三条关键语义：
1. **部分更新**：`null` 表示"不改"，绝不允许把已有事实字段（source/核验状态等）清空——
   旧版编辑表单不会回传这些列；
2. `dayId` 只在**显式新增**时决定归属；PUT 里出现 dayId 即"跨天移动"（v2.2 §6.8），
   目标日必须属于同一行程，落位到目标日 `max(sort_no)+1`；
3. 每次写操作前后各打一条版本快照、并让未应用的 AI 草稿失效（`invalidate_pending_actions`），
   最后精确失效该行程的详情缓存（不再是 allEntries）。
"""

from __future__ import annotations

import json
import logging
from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from app.agent.nl_edit import run_edit_ops
from app.agent.schedule_optimizer import optimize_daily_plan
from app.common.config import settings
from app.common.envelope import ApiError
from app.common.vo_json import iso_time
from app.db.models import (
    BudgetDetail,
    ItineraryChatMessage,
    ItineraryDay,
    ItineraryItem,
    ItineraryMain,
    PoiKnowledge,
)
from app.db.session import session_scope
from app.schemas.business.itinerary import ItemUpsertRequest
from app.schemas.trip import EditOpRequest
from app.services import (
    budget_engine,
    itinerary_chat,
    itinerary_city,
    itinerary_query,
    itinerary_version,
)

logger = logging.getLogger(__name__)

VALID_ITEM_TYPES = ("attraction", "food", "hotel", "transport")
RESERVATION_REMINDER_PREFIX = "【预约提醒】"


# PUT 里带 dayId 即跨天移动（Java 侧此前刻意忽略该字段，v2.2 §6.8 才放开）
_MUTABLE_FIELDS = (
    "poiId",
    "address",
    "latitude",
    "longitude",
    "startTime",
    "endTime",
    "durationMin",
    "cost",
    "tag",
    "remark",
    "openTime",
    "imageUrl",
    "source",
    "sourceUpdatedAt",
    "verificationStatus",
    "valueKind",
    "freshnessStatus",
    "reviewRequirement",
    "factEvidenceJson",
)

_COLUMN_BY_FIELD = {
    "poiId": "poi_id",
    "address": "address",
    "latitude": "latitude",
    "longitude": "longitude",
    "startTime": "start_time",
    "endTime": "end_time",
    "durationMin": "duration_min",
    "cost": "cost",
    "tag": "tag",
    "remark": "remark",
    "openTime": "open_time",
    "imageUrl": "image_url",
    "source": "source",
    "sourceUpdatedAt": "source_updated_at",
    "verificationStatus": "verification_status",
    "valueKind": "value_kind",
    "freshnessStatus": "freshness_status",
    "reviewRequirement": "review_requirement",
    "factEvidenceJson": "fact_evidence_json",
}


def add_item(user_id: int, itinerary_id: int, request: ItemUpsertRequest | None) -> dict[str, Any]:
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        if request is None or request.dayId is None or request.itemType is None or not (request.poiName or "").strip():
            raise ApiError(400, "dayId、itemType、poiName 必填")
        _validate(request)
        day = session.execute(
            select(ItineraryDay).where(ItineraryDay.id == request.dayId, ItineraryDay.itinerary_id == itinerary_id)
        ).scalar_one_or_none()
        if day is None:
            raise ApiError(404, "日期不存在")

    itinerary_version.create_snapshot(user_id, itinerary_id, "add_item", "新增行程项前快照")
    with session_scope() as session:
        entity = ItineraryItem(
            day_id=request.dayId, itinerary_id=itinerary_id, item_type=request.itemType, poi_name=request.poiName
        )
        _copy_optional(entity, request)
        entity.sort_no = itinerary_query.next_sort(session, request.dayId)
        session.add(entity)
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
        budget_engine.recalculate(itinerary_id)
        _apply_suggestion_used(session, itinerary_id, request.poiId, request.poiName, True)
    itinerary_version.create_snapshot(user_id, itinerary_id, "add_item", "新增行程项完成")
    return _fresh_detail(user_id, itinerary_id)


def update_item(user_id: int, item_id: int, request: ItemUpsertRequest | None) -> dict[str, Any]:
    with session_scope() as session:
        item = _require_item(session, user_id, item_id)
        if request is None:
            raise ApiError(400, "请求不能为空")
        _validate(request)
        itinerary_id = item.itinerary_id
        target_day = None
        if request.dayId is not None and request.dayId != item.day_id:
            target_day = session.execute(
                select(ItineraryDay).where(ItineraryDay.id == request.dayId, ItineraryDay.itinerary_id == itinerary_id)
            ).scalar_one_or_none()
            if target_day is None:
                raise ApiError(400, "目标日不属于该行程")

    operation = "move_item" if target_day is not None else "update_item"
    move_to_day_no = target_day.day_no if target_day is not None else None
    if move_to_day_no is None:
        before_summary, after_summary = "更新行程项前快照", "更新行程项完成"
    else:
        before_summary = f"跨天移动前快照（目标第 {move_to_day_no} 天）"
        after_summary = f"移动到第 {move_to_day_no} 天"
    itinerary_version.create_snapshot(user_id, itinerary_id, operation, before_summary)
    with session_scope() as session:
        item = session.get(ItineraryItem, item_id)
        if request.itemType is not None:
            item.item_type = request.itemType
        if request.poiName is not None and request.poiName.strip():
            item.poi_name = request.poiName
        _copy_optional(item, request)
        if move_to_day_no is not None:
            _move_to_day(session, item, request.dayId)
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
        budget_engine.recalculate(itinerary_id)
    itinerary_version.create_snapshot(user_id, itinerary_id, operation, after_summary)
    return _fresh_detail(user_id, itinerary_id)


def _move_to_day(session, item: ItineraryItem, target_day_id: int) -> None:
    """跨天移动：落位到目标日末尾。

    必须先读目标日的 `max(sort_no)` 再改 `day_id`：SQLAlchemy 会在下一次查询前
    autoflush 待提交的改动，先改后读会把被移动项自己算进目标日，空日也会得到非 0 位次。
    """
    next_sort = itinerary_query.next_sort(session, target_day_id)
    item.day_id = target_day_id
    item.sort_no = next_sort


def delete_item(user_id: int, item_id: int) -> dict[str, Any]:
    with session_scope() as session:
        item = _require_item(session, user_id, item_id)
        itinerary_id = item.itinerary_id
        poi_id, poi_name = item.poi_id, item.poi_name

    itinerary_version.create_snapshot(user_id, itinerary_id, "delete_item", "删除行程项前快照")
    with session_scope() as session:
        # @TableLogic 下 deleteById 是软删
        session.get(ItineraryItem, item_id).deleted = 1
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
        budget_engine.recalculate(itinerary_id)
        _apply_suggestion_used(session, itinerary_id, poi_id, poi_name, False)
    itinerary_version.create_snapshot(user_id, itinerary_id, "delete_item", "删除行程项完成")
    return _fresh_detail(user_id, itinerary_id)


def reorder_items(user_id: int, itinerary_id: int, day_id: int | None, item_ids: list[int] | None) -> dict[str, Any]:
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        if day_id is None or item_ids is None:
            raise ApiError(400, "日期和行程项顺序不能为空")
        existing = (
            session.execute(
                select(ItineraryItem).where(ItineraryItem.day_id == day_id, ItineraryItem.itinerary_id == itinerary_id)
            )
            .scalars()
            .all()
        )
        by_id = {item.id: item for item in existing}
        if len(item_ids) != len(existing) or set(by_id) != set(item_ids):
            raise ApiError(400, "行程项顺序必须包含该日期的全部行程项")

    itinerary_version.create_snapshot(user_id, itinerary_id, "reorder", "调整行程顺序前快照")
    with session_scope() as session:
        for index, item_id in enumerate(item_ids):
            session.get(ItineraryItem, item_id).sort_no = index
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
        budget_engine.recalculate(itinerary_id)
    itinerary_version.create_snapshot(user_id, itinerary_id, "reorder", "调整行程顺序完成")
    return _fresh_detail(user_id, itinerary_id)


def optimize_day(user_id: int, itinerary_id: int, day_id: int) -> dict[str, Any]:
    """按路线重排某天（v2.6 W3）：确定性优化器全量重排，不引入/不删除任何点位。

    与 local_replan 的差异：优化器若因「超过每日景点上限」给出 removed_candidates，
    这里**只重排、不落删**——被移除的候选留在原相对位置，用户数据不静默丢失。
    模型/计算在事务外（与 nl_edit 同纪律）；路线矩阵缺省走坐标估算（degraded 由上游如实标记）。
    """
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        day = session.execute(
            select(ItineraryDay).where(ItineraryDay.id == day_id, ItineraryDay.itinerary_id == itinerary_id)
        ).scalar_one_or_none()
        if day is None:
            raise ApiError(404, "日期不存在")
        day_no = day.day_no
        rows = (
            session.execute(
                select(ItineraryItem)
                .where(ItineraryItem.day_id == day_id, ItineraryItem.itinerary_id == itinerary_id)
                .order_by(ItineraryItem.sort_no)
            )
            .scalars()
            .all()
        )
        if len([row for row in rows if row.item_type in ("attraction", "food")]) < 2:
            raise ApiError(400, "当天不足 2 个可优化点位")

    plan = {
        "day_no": day_no,
        "items": [
            {
                "poi_id": row.poi_id,
                "poi_name": row.poi_name,
                "item_type": row.item_type,
                "open_time": row.open_time,
                "start_time": _time_text(row.start_time),
                "end_time": _time_text(row.end_time),
                "duration_min": row.duration_min,
                "cost": float(row.cost) if row.cost is not None else None,
                "latitude": float(row.latitude) if row.latitude is not None else None,
                "longitude": float(row.longitude) if row.longitude is not None else None,
            }
            for row in rows
        ],
    }
    result = optimize_daily_plan(plan, mode=settings.route_mode)

    # 优化器输出顺序 → 原行 id（同名点位按原顺序逐个配对；未被安排的尾随行保持原相对顺序）
    by_name: dict[str, list[int]] = {}
    for row in rows:
        by_name.setdefault(row.poi_name or "", []).append(row.id)
    ordered_ids: list[int] = []
    for item in result.plan.get("items") or []:
        bucket = by_name.get(str(item.get("poi_name") or ""))
        if bucket:
            ordered_ids.append(bucket.pop(0))
    for bucket in by_name.values():
        ordered_ids.extend(bucket)

    itinerary_version.create_snapshot(user_id, itinerary_id, "optimize", f"优化路线前快照（第 {day_no} 天）")
    with session_scope() as session:
        for index, row_id in enumerate(ordered_ids):
            session.get(ItineraryItem, row_id).sort_no = index
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
    itinerary_version.create_snapshot(user_id, itinerary_id, "optimize", f"优化路线完成（第 {day_no} 天）")
    return _fresh_detail(user_id, itinerary_id)


def update_day(user_id: int, itinerary_id: int, day_id: int, theme: str | None) -> dict[str, Any]:
    """编辑某天副标题（复用 metadata_json.theme，v2.6 W3）：空串 = 清空，回退派生标题。"""
    cleaned = (theme or "").strip()
    if len(cleaned) > 60:
        raise ApiError(400, "日标题过长（最多 60 字）")
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        day = session.execute(
            select(ItineraryDay).where(ItineraryDay.id == day_id, ItineraryDay.itinerary_id == itinerary_id)
        ).scalar_one_or_none()
        if day is None:
            raise ApiError(404, "日期不存在")
        day_no = day.day_no

    itinerary_version.create_snapshot(user_id, itinerary_id, "update_day", f"编辑日标题前快照（第 {day_no} 天）")
    with session_scope() as session:
        day = session.get(ItineraryDay, day_id)
        metadata = _parse_metadata(day.metadata_json)
        if cleaned:
            metadata["theme"] = cleaned
        else:
            metadata.pop("theme", None)
        day.metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
    itinerary_version.create_snapshot(user_id, itinerary_id, "update_day", f"编辑日标题（第 {day_no} 天）")
    return _fresh_detail(user_id, itinerary_id)


def _time_text(value) -> str | None:
    return value.strftime("%H:%M:%S") if value is not None else None


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def nl_edit(user_id: int, itinerary_id: int, instruction: str) -> dict[str, Any]:
    """自然语言编辑：解析一句话并**直接落库**（与 chat-edit「只出草稿」相对）。

    与 Java 的唯一结构差异：模型调用放在事务之外（读快照 → 调模型 → 一个 scope 内应用），
    不是一次 LLM 调用占住一条连接池连接那么久。op 的应用语义、跳过条件与提示文案逐条照搬，
    包括三条容易被当成 bug 的既有行为：
    - `move_day` 的目标恒为 `day_no + 1`（按天数截断），尽管提示词写的是「换到第几天」；
    - `delete` 在 `day_no` 缺失/无法解析时作用于**整趟行程**的点位；
    - 时间解析失败会让整个请求以 400「时间格式必须为 HH:mm」中止（不是跳过该条 op）。
    """
    with session_scope() as session:
        main = _require_main(session, user_id, itinerary_id)
        city, trip_days = main.city, main.days
    itinerary_version.create_snapshot(user_id, itinerary_id, "nl_edit", "自然语言编辑前快照")

    with session_scope() as session:
        day_rows = (
            session.execute(
                select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id).order_by(ItineraryDay.day_no)
            )
            .scalars()
            .all()
        )
        plans = [
            {
                "day_no": day.day_no,
                "items": [
                    {
                        "item_type": item.item_type or "",
                        "poi_name": item.poi_name or "",
                        "start_time": iso_time(item.start_time) or "",
                    }
                    for item in _items_of_day(session, day.id)
                ],
            }
            for day in day_rows
        ]
        day_ids_by_no = {day.day_no: day.id for day in day_rows}

    ops = itinerary_city.guard_agent_call(
        "指令解析服务暂不可用",
        lambda: run_edit_ops(
            EditOpRequest(city=city or "", days=trip_days, plans=plans, instruction=instruction or "")
        ),
    )

    applied: list[str] = []
    with session_scope() as session:
        for op in ops:
            message = _apply_edit_op(session, op, itinerary_id, city, day_ids_by_no)
            if message:
                applied.append(message)
        if not applied:
            raise ApiError(400, "未能从指令中解析出可执行的修改，请换个说法")
        session.flush()
        itinerary_chat.invalidate_pending_actions(user_id, itinerary_id)
        budget_engine.recalculate(itinerary_id)
    itinerary_version.create_snapshot(user_id, itinerary_id, "nl_edit", "自然语言编辑完成")
    return {"applied": applied, "detail": _fresh_detail(user_id, itinerary_id)}


def _apply_edit_op(session, op, itinerary_id: int, city: str | None, day_ids_by_no: dict[int, int]) -> str | None:
    """执行一条 op；返回给用户的中文回执，`None` 表示按 Java 口径跳过该条。"""
    action = op.action or ""
    day_no = op.day_no
    poi_name = op.poi_name
    start_time = op.start_time
    tier = op.tier

    if action == "upgrade_hotel":
        return _upgrade_hotel(session, itinerary_id, city, day_no, tier)

    if action in ("update_time", "move_day") and (day_no is None or poi_name is None):
        return None
    if action in ("delete", "add") and poi_name is None:
        return None
    target_day_id = day_ids_by_no.get(day_no) if day_no is not None else None
    if target_day_id is None and action != "delete":
        return None

    if action == "delete":
        scope = (
            _items_of_day(session, target_day_id)
            if target_day_id is not None
            else session.execute(select(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary_id))
            .scalars()
            .all()
        )
        item = _find_item_by_name(scope, poi_name)
        if item is None:
            return None
        item.deleted = 1  # 同 @TableLogic 的 deleteById：软删，行留在表里
        return f"删除「{poi_name}」"

    if action == "update_time":
        item = _find_item_by_name(_items_of_day(session, target_day_id), poi_name)
        if item is None:
            return None
        item.start_time = _parse_required_time(start_time)
        item.end_time = None
        return f"第{day_no}天「{poi_name}」改为 {start_time}"

    if action == "move_day":
        item = _find_item_by_name(_items_of_day(session, target_day_id), poi_name)
        dest_no = min(day_no + 1, len(day_ids_by_no))
        dest_id = day_ids_by_no.get(dest_no)
        if item is None or dest_id is None or dest_id == target_day_id:
            return None
        # 先取目标日末尾位次再改归属（autoflush 会让被移动项自己算进去）
        next_sort = itinerary_query.next_sort(session, dest_id)
        item.day_id = dest_id
        item.sort_no = next_sort
        return f"「{poi_name}」移到第{dest_no}天"

    if action == "add":
        poi = session.execute(
            select(PoiKnowledge).where(PoiKnowledge.city == city, PoiKnowledge.name == poi_name).limit(1)
        ).scalar_one_or_none()
        entity = ItineraryItem(
            day_id=target_day_id,
            itinerary_id=itinerary_id,
            item_type=poi.category if poi else "attraction",
            poi_name=poi_name,
        )
        if poi is not None:
            entity.poi_id = str(poi.id)
            entity.address = poi.address
            entity.latitude = poi.latitude
            entity.longitude = poi.longitude
            entity.cost = poi.ticket_price
            entity.duration_min = poi.duration_min
            entity.open_time = poi.open_time
            entity.source = poi.source
            entity.source_updated_at = poi.source_updated_at
            entity.verification_status = "unverified" if poi.source_updated_at is None else "partially_verified"
            entity.value_kind = "observed"
            entity.freshness_status = "unknown" if poi.source_updated_at is None else "fresh"
            entity.review_requirement = "before_departure" if poi.source_updated_at is None else "none"
            entity.tag = poi.tags
        if start_time is not None:
            entity.start_time = _parse_required_time(start_time)
        entity.sort_no = itinerary_query.next_sort(session, target_day_id)
        session.add(entity)
        return f"第{day_no}天新增「{poi_name}」"

    return None


def _upgrade_hotel(session, itinerary_id: int, city: str | None, day_no: int | None, tier: str | None) -> str | None:
    """换酒店：按档次关键词在同城权威库里挑一家，挑不到就退而求其次换一家同类的。"""
    if day_no is not None:
        day_id = session.execute(
            select(ItineraryDay.id).where(ItineraryDay.itinerary_id == itinerary_id, ItineraryDay.day_no == day_no)
        ).scalar_one_or_none()
        scope = _items_of_day(session, day_id) if day_id is not None else []
    else:
        scope = session.execute(select(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary_id)).scalars().all()
    current = next((item for item in scope if item.item_type == "hotel"), None)
    if current is None:
        return None
    hotels = (
        session.execute(select(PoiKnowledge).where(PoiKnowledge.city == city, PoiKnowledge.category == "hotel"))
        .scalars()
        .all()
    )
    if not hotels:
        return None
    keywords = _hotel_keywords(tier)
    others = [hotel for hotel in hotels if str(hotel.id) != current.poi_id]
    ranked = next(
        (hotel for hotel in others if _contains_any((hotel.description or "") + (hotel.tags or ""), keywords)), None
    )
    selected = ranked or (others[0] if others else hotels[0])
    current.poi_id = str(selected.id)
    current.poi_name = selected.name
    current.address = selected.address
    current.latitude = selected.latitude
    current.longitude = selected.longitude
    current.cost = selected.ticket_price
    current.duration_min = selected.duration_min
    current.tag = selected.tags
    current.remark = selected.description
    return "酒店已调整为" + (tier if tier and tier.strip() else "推荐档次")


_HOTEL_KEYWORDS = {
    "经济型": ("经济",),
    "舒适型": ("舒适", "中端"),
    "高档型": ("高端", "高档"),
    "豪华型": ("高端", "五星", "国宾", "地标"),
    "奢华型": ("国宾", "地标", "五星", "百年"),
}


def _hotel_keywords(tier: str | None) -> tuple[str, ...]:
    if not tier or not tier.strip():
        return ()
    return _HOTEL_KEYWORDS.get(tier, (tier,))


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return not keywords or any(keyword in text for keyword in keywords)


def _items_of_day(session, day_id: int | None) -> list[ItineraryItem]:
    if day_id is None:
        return []
    return list(session.execute(select(ItineraryItem).where(ItineraryItem.day_id == day_id)).scalars().all())


def _find_item_by_name(items, name: str | None):
    return next((item for item in items if name is not None and item.poi_name == name), None)


def _parse_required_time(value: str) -> time:
    """与 Java `LocalTime.parse` 同口径：`HH:mm`（可带秒），不接受 `9:30` / `0930` 这类宽松形式。"""
    text = (value or "").strip()
    try:
        if ":" not in text:
            raise ValueError(text)
        return time.fromisoformat(text)
    except ValueError as exc:
        raise ApiError(400, "时间格式必须为 HH:mm") from exc


def delete_itinerary(user_id: int, itinerary_id: int) -> None:
    itinerary_version.create_snapshot(user_id, itinerary_id, "delete", "删除行程前快照")
    delete_cascade(user_id, itinerary_id)


def delete_cascade(user_id: int, itinerary_id: int) -> None:
    """级联软删日/项/预算/聊天记录与主表（用户侧与 Admin 侧共用，避免只删主表留孤儿）。"""
    with session_scope() as session:
        for model in (ItineraryDay, ItineraryItem, BudgetDetail):
            rows = session.execute(select(model).where(model.itinerary_id == itinerary_id)).scalars().all()
            for row in rows:
                row.deleted = 1
        chats = (
            session.execute(select(ItineraryChatMessage).where(ItineraryChatMessage.itinerary_id == itinerary_id))
            .scalars()
            .all()
        )
        for chat in chats:
            session.delete(chat)  # itinerary_chat_message 无 deleted 列：Java 同样是物理删
        main = session.get(ItineraryMain, itinerary_id)
        if main is not None:
            main.deleted = 1
    itinerary_query.evict_detail(user_id, itinerary_id)


def _apply_suggestion_used(session, itinerary_id: int, poi_id: str | None, poi_name: str | None, used: bool) -> None:
    """维护备选池 used 标记，并同步增删管家说（planNote）里的预约提醒。"""
    main = session.get(ItineraryMain, itinerary_id)
    if main is None:
        return
    suggestions = _parse_suggestions(main.suggestions_json)
    if not suggestions:
        return
    changed = False
    for suggestion in suggestions:
        suggestion_id = "" if suggestion.get("poiId") is None else str(suggestion.get("poiId"))
        suggestion_name = "" if suggestion.get("name") is None else str(suggestion.get("name"))
        hit = (poi_id and poi_id.strip() and poi_id == suggestion_id) or (
            poi_name and poi_name.strip() and poi_name == suggestion_name
        )
        if not hit:
            continue
        if bool(suggestion.get("used")) != used:
            suggestion["used"] = used
            changed = True
        note = main.plan_note or ""
        marker = f"{RESERVATION_REMINDER_PREFIX}「{suggestion_name}」"
        need_reservation = bool(suggestion.get("needReservation"))
        if used and need_reservation and marker not in note:
            line = f"{marker}通常需要提前预约或取票，建议出发前通过官方渠道/小程序确认。"
            main.plan_note = line if not note.strip() else f"{note}\n{line}"
            changed = True
        elif not used and marker in note:
            cleaned = "\n".join(line for line in note.splitlines() if marker not in line)
            main.plan_note = cleaned or None
            changed = True
    if not changed:
        return
    try:
        main.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.warning("suggestions serialization failed, keeping original json")
    session.flush()


def _require_main(session, user_id: int, itinerary_id: int) -> ItineraryMain:
    return itinerary_query.require_main(session, user_id, itinerary_id)


def _require_item(session, user_id: int, item_id: int) -> ItineraryItem:
    item = session.get(ItineraryItem, item_id)
    if item is None:
        raise ApiError(404, "行程项不存在")
    _require_main(session, user_id, item.itinerary_id)
    return item


def _copy_optional(target: ItineraryItem, request: ItemUpsertRequest) -> None:
    for field in _MUTABLE_FIELDS:
        value = getattr(request, field)
        if value is not None:
            setattr(target, _COLUMN_BY_FIELD[field], value)


def set_favorite(user_id: int, itinerary_id: int, favorite: bool) -> dict[str, Any]:
    """收藏开关：单列写（§4 纪律 1——整行 update 会冲掉异步生成链路的并发回写）。"""
    itinerary_query.find_owned_main(user_id, itinerary_id)
    with session_scope() as session:
        session.execute(update(ItineraryMain).where(ItineraryMain.id == itinerary_id).values(favorite=bool(favorite)))
    return _fresh_detail(user_id, itinerary_id)


def set_archived(user_id: int, itinerary_id: int, archived: bool) -> dict[str, Any]:
    """归档开关：与「删除」语义区分——归档不隐藏分享，只移出默认视图/图鉴。"""
    itinerary_query.find_owned_main(user_id, itinerary_id)
    with session_scope() as session:
        session.execute(update(ItineraryMain).where(ItineraryMain.id == itinerary_id).values(archived=bool(archived)))
    return _fresh_detail(user_id, itinerary_id)


def _validate(request: ItemUpsertRequest) -> None:
    if request.itemType is not None and request.itemType not in VALID_ITEM_TYPES:
        raise ApiError(400, "行程项类型不合法")
    if request.poiName is not None and len(request.poiName) > 128:
        raise ApiError(400, "地点名称过长")
    if request.cost is not None and (request.cost < 0 or request.cost > Decimal("1000000")):
        raise ApiError(400, "费用必须在 0 到 1000000 之间")
    if request.durationMin is not None and not (0 <= request.durationMin <= 1440):
        raise ApiError(400, "时长必须在 0 到 1440 分钟之间")


def _fresh_detail(user_id: int, itinerary_id: int) -> dict[str, Any]:
    """写后立即回源：evict 由 detail() 的缓存重建完成，与 Java 末尾的 CacheEvict 等价。"""
    itinerary_query.evict_detail(user_id, itinerary_id)
    return itinerary_query.detail(user_id, itinerary_id)


def _parse_suggestions(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("json column parse failed, returned empty list instead")
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
