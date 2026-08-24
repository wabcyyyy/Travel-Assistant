import logging

import pymysql

from app.common.config import settings

logger = logging.getLogger(__name__)


def _connect():
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def search_pois(city: str, category: str | None = None, limit: int = 50) -> list[dict]:
    sql = "SELECT id, city, name, category, address, latitude, longitude, ticket_price, duration_min, open_time, tags, rating, description FROM poi_knowledge WHERE city = %s"
    params: list = [city]
    if category:
        sql += " AND category = %s"
        params.append(category)
    sql += f" ORDER BY rating DESC LIMIT {int(limit)}"
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_pois failed: %s", e)
        return []


def list_all_pois() -> list[dict]:
    sql = "SELECT id, city, name, category, address, latitude, longitude, ticket_price, duration_min, open_time, tags, rating, description FROM poi_knowledge ORDER BY id"
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                return list(cursor.fetchall())
    except Exception as e:
        logger.error("list_all_pois failed: %s", e)
        return []


def get_poi(city: str, name: str) -> dict | None:
    sql = "SELECT id, city, name, category, address, latitude, longitude, ticket_price, duration_min, open_time, tags, rating, description FROM poi_knowledge WHERE city = %s AND name = %s LIMIT 1"
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (city, name))
                row = cursor.fetchone()
                return row if row else None
    except Exception as e:
        logger.error("get_poi failed: %s", e)
        return None


def get_city_consumption(city: str) -> dict | None:
    sql = "SELECT city, level, meal_price, transport_price, hotel_price FROM city_consumption WHERE city = %s LIMIT 1"
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
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
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, poi_ids)
                return list(cursor.fetchall())
    except Exception as e:
        logger.error("search_hotel_room_types failed: %s", e)
        return []
