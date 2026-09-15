"""预算重算（移植自 Java `BudgetEngineImpl`）。

口径必须与前端「每日费用」明细一致，两条曾经踩过的坑保留原注释：
- 餐饮/门票 = 条目单价 × 人数；**不再**做"按城市基准价封顶"的展示层钳制，
  那会让分类合计与明细对不上、改价后总价看起来"不动"；离谱价格在 Agent 生成侧钳制。
- 酒店按所选房型的容量算房间数（`ceil(persons / capacity)`），不假定每间住 2 人。
- 餐饮/酒店被模型写成 0 视为无效，回落知识库权威价；免费景点保留 0。
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from sqlalchemy import delete, select

from app.db.models import (
    BudgetDetail,
    CityConsumption,
    HotelRoomType,
    ItineraryItem,
    ItineraryMain,
    PoiKnowledge,
)
from app.db.session import session_scope
from app.services import season_price

DEFAULT_TRANSPORT_PER_DAY = Decimal("35.00")
ROOM_TYPE_MARKER = "房型："
ZERO = Decimal("0")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recalculate(itinerary_id: int) -> list[BudgetDetail]:
    with session_scope() as session:
        main = session.get(ItineraryMain, itinerary_id)
        if main is None:
            return []
        persons = main.persons or 1
        days = main.days or 1
        items = session.execute(
            select(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary_id)
        ).scalars().all()

        ticket = meal = hotel = ZERO
        ticket_count = meal_count = hotel_count = 0
        hotel_from_poi_fallback = False

        for item in items:
            item_type = item.item_type
            if item.cost is not None and not _is_zero_cost_for(item_type, item.cost):
                unit = Decimal(item.cost)
            else:
                unit = _poi_unit_cost(session, item, main.city)
                if unit is not None and item_type == "hotel":
                    unit = season_price.apply(unit, main.start_date)
                    hotel_from_poi_fallback = True
            if unit is None:
                continue
            if item_type == "attraction":
                ticket += unit
                ticket_count += 1
            elif item_type == "food":
                meal += unit
                meal_count += 1
            elif item_type == "hotel":
                capacity = _hotel_capacity(session, item)
                rooms = math.ceil(persons / capacity)
                hotel += unit * Decimal(rooms)
                hotel_count += 1

        consumption = session.execute(
            select(CityConsumption).where(CityConsumption.city == main.city)
        ).scalar_one_or_none()
        transport_per_day = (
            consumption.transport_price if consumption and consumption.transport_price else DEFAULT_TRANSPORT_PER_DAY
        )
        transport = Decimal(transport_per_day) * Decimal(days) * Decimal(persons)
        ticket *= Decimal(persons)
        meal *= Decimal(persons)

        hotel_remark = "按每晚房费×房间数合计"
        if hotel_from_poi_fallback and hotel_count > 0:
            hotel_remark = (
                f"知识库基准价已按{season_price.label(main.start_date)}系数×{season_price.factor(main.start_date)}调整"
            )

        session.execute(delete(BudgetDetail).where(BudgetDetail.itinerary_id == itinerary_id))
        created: list[BudgetDetail] = []
        for category, amount, count, remark in (
            ("门票", ticket, ticket_count, "按景点票价×人数"),
            ("餐饮", meal, meal_count, "按餐饮单价×人数"),
            ("交通", transport, days, "按城市系数×天数×人数"),
            ("酒店", hotel, hotel_count, hotel_remark),
        ):
            detail = BudgetDetail(
                itinerary_id=itinerary_id,
                category=category,
                amount=_money(amount),
                item_count=count,
                remark=remark,
            )
            session.add(detail)
            created.append(detail)
        session.flush()
        return created


def _is_zero_cost_for(item_type: str | None, cost: Decimal) -> bool:
    if item_type not in ("food", "hotel"):
        return False
    return cost == ZERO


def _poi_unit_cost(session, item: ItineraryItem, city: str) -> Decimal | None:
    poi = None
    if item.poi_id and item.poi_id.strip() and item.poi_id.isdigit():
        poi = session.get(PoiKnowledge, int(item.poi_id))
    if poi is None and item.poi_name and item.poi_name.strip():
        poi = session.execute(
            select(PoiKnowledge).where(PoiKnowledge.city == city, PoiKnowledge.name == item.poi_name).limit(1)
        ).scalar_one_or_none()
    if poi is None:
        return None
    return poi.ticket_price if poi.ticket_price is not None else poi.avg_cost


def _hotel_capacity(session, item: ItineraryItem) -> int:
    if not item.poi_id or not item.remark:
        return 2
    start = item.remark.find(ROOM_TYPE_MARKER)
    if start < 0:
        return 2
    start += len(ROOM_TYPE_MARKER)
    end = item.remark.find("；", start)
    room_name = (item.remark[start:] if end < 0 else item.remark[start:end]).strip()
    if not item.poi_id.isdigit():
        return 2
    room = session.execute(
        select(HotelRoomType).where(
            HotelRoomType.poi_id == int(item.poi_id), HotelRoomType.room_name == room_name
        ).limit(1)
    ).scalar_one_or_none()
    if room is None or room.capacity is None:
        return 2
    return max(room.capacity, 1)
