"""知识库数据访问层（MySQL）：POI、城市消费、酒店房型查询。

职责：
- 对 poi_knowledge（景点/餐饮/酒店）、city_consumption、hotel_room_type 等表做查询；
- 提供按城市/类别/名称/多城市/全量的检索，以及城市消费系数与酒店房型查询。

实现要点：
- 经 `app.common.db_pool` 连接池访问 MySQL，避免每次查询新建 TCP 连接；
- 统一 try/except 吞掉异常并记日志，查询失败返回空列表/None 而非抛错，
  保证上游检索链路不中断；
- 是 tools 层（RAG + 知识库混合检索）最终回退到的权威数据来源。

依赖：app.common.config.settings、app.common.db_pool。
"""

import logging

from app.common import db_pool

logger = logging.getLogger(__name__)

# 注意：poi_knowledge 另有 avg_cost 列（人均消费，随 Flyway V1 基线创建）。
# 预算契约：ticket_price 优先；food/hotel 在 ticket_price 为空时回落 avg_cost
# （海外种子与部分采集管线把人均/房价写在 avg_cost）。
_POI_COLUMNS = (
    "id, city, name, category, address, latitude, longitude, ticket_price, avg_cost, duration_min, "
    "open_time, tags, rating, description, source, source_updated_at"
)


def list_all_pois_with_status() -> tuple[list[dict], bool]:
    """返回 POI 与查询是否成功，区分“空表”和“数据库暂不可用”。"""
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge ORDER BY id"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql)
            return list(cursor.fetchall()), True
    except Exception as e:
        logger.error("list_all_pois failed: %s", e)
        return [], False


def _connect():
    """兼容旧调用点；请优先使用 db_pool.connection()。"""
    return db_pool.acquire()


def search_pois(city: str, category: str | None = None, limit: int = 50) -> list[dict]:
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city = %s"
    params: list = [city]
    if category:
        sql += " AND category = %s"
        params.append(category)
    sql += f" ORDER BY rating DESC LIMIT {int(limit)}"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_pois failed: %s", e)
        return []


def search_pois_by_cities(cities: list[str], category: str | None = None, limit: int = 50) -> list[dict]:
    """按多个规范化城市检索 POI，供省级目的地复用省内热门城市数据。"""
    normalized = [str(city).strip() for city in cities if str(city).strip()]
    if not normalized:
        return []
    placeholders = ",".join(["%s"] * len(normalized))
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city IN ({placeholders})"
    params: list = list(normalized)
    if category:
        sql += " AND category = %s"
        params.append(category)
    sql += f" ORDER BY rating DESC LIMIT {int(limit)}"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_pois_by_cities failed: %s", e)
        return []


def search_pois_by_keyword(city: str, keywords: str = "", category: str | None = None, limit: int = 30) -> list[dict]:
    """城市 + 关键词（名称/标签/描述）检索本地知识库；关键词为空则取该城评分前 N。

    与 `search_pois` 的区别：这是「用户键入关键词」路径（工作台加点），
    刻意只做 LIKE 匹配而不引向量检索——键入即精确子串，召回可解释。
    """
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city = %s"
    params: list = [city]
    if category:
        sql += " AND category = %s"
        params.append(category)
    keyword = (keywords or "").strip()
    if keyword:
        like = f"%{keyword}%"
        sql += " AND (name LIKE %s OR tags LIKE %s OR description LIKE %s)"
        params.extend([like, like, like])
    sql += f" ORDER BY rating DESC LIMIT {int(limit)}"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_pois_by_keyword failed: %s", e)
        return []


def count_pois_by_city() -> dict[str, int]:
    """各城市的知识库点位数量（供「当前覆盖哪些城市」的如实空态）。"""
    sql = "SELECT city, COUNT(*) AS n FROM poi_knowledge GROUP BY city ORDER BY n DESC, city"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql)
            return {str(row["city"]): int(row["n"]) for row in cursor.fetchall()}
    except Exception as e:
        logger.error("count_pois_by_city failed: %s", e)
        return {}


def search_poi_by_name(name: str, category: str | None = None) -> dict | None:
    """在知识库中按名称兜底查询，名称仍需匹配候选/用户明确指定的酒店。"""
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE name = %s"
    params: list = [name]
    if category:
        sql += " AND category = %s"
        params.append(category)
    sql += " ORDER BY rating DESC LIMIT 1"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row if row else None
    except Exception as e:
        logger.error("search_poi_by_name failed: %s", e)
        return None


def list_all_pois() -> list[dict]:
    rows, _available = list_all_pois_with_status()
    return rows


def list_hotel_pois(city: str) -> list[dict]:
    """完整枚举城市酒店，供档次/价格/房型比较使用，不使用 Top-K 截断。"""
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city = %s AND category = 'hotel' ORDER BY rating DESC, id"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, (city,))
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("list_hotel_pois failed: %s", e)
        return []


def list_hotel_pois_by_cities(cities: list[str]) -> list[dict]:
    """完整枚举多个城市的酒店，不做 Top-K 截断。"""
    normalized = [str(city).strip() for city in cities if str(city).strip()]
    if not normalized:
        return []
    placeholders = ",".join(["%s"] * len(normalized))
    sql = (
        f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city IN ({placeholders}) "
        "AND category = 'hotel' ORDER BY rating DESC, id"
    )
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, normalized)
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("list_hotel_pois_by_cities failed: %s", e)
        return []


def get_poi(city: str, name: str) -> dict | None:
    sql = f"SELECT {_POI_COLUMNS} FROM poi_knowledge WHERE city = %s AND name = %s LIMIT 1"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, (city, name))
            row = cursor.fetchone()
            return row if row else None
    except Exception as e:
        logger.error("get_poi failed: %s", e)
        return None


def get_city_consumption(city: str) -> dict | None:
    sql = "SELECT city, level, meal_price, transport_price, hotel_price FROM city_consumption WHERE city = %s LIMIT 1"
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, (city,))
            row = cursor.fetchone()
            return row if row else None
    except Exception as e:
        logger.error("get_city_consumption failed: %s", e)
        return None


def search_hotel_room_types(poi_ids: list[int]) -> list[dict]:
    if not poi_ids:
        return []
    placeholders = ",".join(["%s"] * len(poi_ids))
    sql = (
        "SELECT id, poi_id, room_name, base_price, capacity, bed_type, breakfast, "
        "description, is_default FROM hotel_room_type "
        f"WHERE poi_id IN ({placeholders}) ORDER BY poi_id, is_default DESC, base_price"
    )
    try:
        with db_pool.connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, poi_ids)
            return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_hotel_room_types failed: %s", e)
        return []
