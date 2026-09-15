"""本地 POI 检索（加点工作台的数据源）：只读 `poi_knowledge`，不触任何外部 API。

与 Agent 检索的关系：Agent 走 `poi_store`（向量召回）+ `poi_repository`（名称兜底），
本模块是同一张表上的「用户键入关键词」路径——共享同一份权威数据，
所以「工作台能加的点位」与「生成时能引用的点位」不会分叉。

空态如实：返回 `coveredCities`（各城点位数），前端据此区分
「该城有库但关键词没命中」与「该城根本不在库里」——不假装是「无结果」。
"""

from __future__ import annotations

from app.agent import poi_repository

CATEGORY_LABELS: dict[str, str] = {"attraction": "景点", "food": "餐饮", "hotel": "住宿"}
MAX_LIMIT = 30


def _to_vo(row: dict) -> dict:
    ticket = row.get("ticket_price")
    avg = row.get("avg_cost")
    cost = ticket if ticket is not None else avg
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "category": row.get("category"),
        "address": row.get("address"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "rating": row.get("rating"),
        "tags": row.get("tags"),
        "cost": cost,
        "source": row.get("source"),
    }


def search_local(city: str, keywords: str = "", category: str | None = None) -> dict:
    rows = poi_repository.search_pois_by_keyword(
        city, keywords=keywords, category=category, limit=MAX_LIMIT
    )
    coverage = poi_repository.count_pois_by_city()
    return {
        "city": city,
        "category": category,
        "items": [_to_vo(row) for row in rows],
        "coveredCities": [{"city": name, "count": n} for name, n in coverage.items()],
    }
