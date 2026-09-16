"""自然语言编辑：一句话 → 结构化操作 → 直接落库（自 itinerary_command 拆出）。

与 chat-edit「只出草稿」相对：本模块**直接写库**。op 的应用语义、跳过条件与
提示文案逐条照搬 Java，包括三条容易被当成 bug 的既有行为：

- `move_day` 的目标恒为 `day_no + 1`（按天数截断），尽管提示词写的是「换到第几天」；
- `delete` 在 `day_no` 缺失/无法解析时作用于**整趟行程**的点位；
- 时间解析失败会让整个请求以 400「时间格式必须为 HH:mm」中止（不是跳过该条 op）。

模型调用放在事务之外（读快照 → 调模型 → 一个 scope 内应用），避免一次 LLM
调用占住连接池连接。

依赖：itinerary_command（共享 helper：_require_main/_fresh_detail/_time_text 等）、
itinerary_city（guard_agent_call）、itinerary_chat/budget_engine/itinerary_version。
本模块与 itinerary_command 是**单向**依赖（后者只在注释里提到 nl_edit 纪律）。
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

from sqlalchemy import select

from app.agent import run_edit_ops
from app.common.envelope import ApiError
from app.common.vo_json import iso_time
from app.db.models import ItineraryDay, ItineraryItem, PoiKnowledge
from app.db.session import session_scope
from app.schemas.trip import EditOpRequest
from app.services import budget_engine, itinerary_chat, itinerary_city, itinerary_query, itinerary_version
from app.services.itinerary_command import (
    _fresh_detail,
    _require_main,
)

logger = logging.getLogger(__name__)

VALID_ITEM_TYPES = ("attraction", "food", "hotel", "transport")
RESERVATION_REMINDER_PREFIX = "【预约提醒】"


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
        # 上方守卫已保证 move_day 时 day_no 非 None；这里显式再判一次，既让类型
        # 收窄（复合条件无法跨语句推断），也让守卫未来被改动时不致 TypeError。
        if day_no is None:
            return None
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
