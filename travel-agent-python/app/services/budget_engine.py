"""预算重算（移植自 Java `BudgetEngineImpl`）。

口径必须与前端「每日费用」明细一致，两条曾经踩过的坑保留原注释：
- 餐饮/门票 = 条目单价 × 人数；**不再**做"按城市基准价封顶"的展示层钳制，
  那会让分类合计与明细对不上、改价后总价看起来"不动"；离谱价格在 Agent 生成侧钳制。
- 酒店按所选房型的容量算房间数（`ceil(persons / capacity)`），不假定每间住 2 人。
- 餐饮/酒店被模型写成 0 视为无效，回落知识库权威价；免费景点保留 0。
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select

from app.db.models import (
    BudgetDetail,
    CityConsumption,
    ItineraryItem,
    ItineraryMain,
)
from app.db.session import session_scope

DEFAULT_TRANSPORT_PER_DAY = Decimal("35.00")
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
        items = session.execute(select(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary_id)).scalars().all()

        ticket = meal = hotel = ZERO
        ticket_count = meal_count = hotel_count = 0

        for item in items:
            item_type = item.item_type
            # 语料库退役后无"知识库权威价"回落：条目成本缺失或为 0 即不计入，如实缺省
            unit = Decimal(item.cost) if item.cost is not None and not _is_zero_cost_for(item_type, item.cost) else None
            if unit is None:
                continue
            if item_type == "attraction":
                ticket += unit
                ticket_count += 1
            elif item_type == "food":
                meal += unit
                meal_count += 1
            elif item_type == "hotel":
                # 房型表已退役：容量统一按每间 2 人计
                rooms = math.ceil(persons / 2)
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


# 房型表已退役：酒店容量统一按每间 2 人计。
