"""事实落地：坐标校验与外部数据补点（G-2.2 自 day_stream 拆出）。

职责：
- has_coord：坐标存在且非 0/0（0/0 是缺失哨兵）；
- local_ground：开放模式自选点位经 Nominatim 按名解析并回填真实坐标。

依赖：tools（外部地点检索）；无上层依赖。
"""

import logging

from app.agent import tools

logger = logging.getLogger(__name__)


def has_coord(value) -> bool:
    """坐标有效：非 None 且非 0.0（0/0 是缺失哨兵，与 find_nearby_pois 口径一致）。"""
    try:
        return value is not None and abs(float(value)) > 1e-6
    except (TypeError, ValueError):
        return False


def local_ground(item: dict, city: str, cache: dict) -> None:
    """用外部地点层落坐标与地址（去高德后：Nominatim 是唯一的点名 grounding 源）。

    按名称解析、过名称相似度门槛后才采纳坐标/地址——查不到就保持原样，
    由上层按「证据不足」降级（票价/营业时间数据源不再提供，恒为 LLM 估价）。
    """
    from app.agent.tools import anchor_name_similar

    if has_coord(item.get("latitude")) and has_coord(item.get("longitude")):
        return
    key = f"{city}:{item.get('poi_name')}"
    if key in cache:
        hit = cache[key]
        if hit:
            item["latitude"] = hit["lat"]
            item["longitude"] = hit["lng"]
            item["address"] = hit.get("address")
            if hit.get("photo"):
                item["image"] = hit["photo"]
        return
    try:
        pois = tools.search_local_poi(city, item.get("poi_name") or "")
        query_name = str(item.get("poi_name") or "")
        hit = None
        for poi in pois or []:
            if anchor_name_similar(query_name, str(poi.get("name") or "")):
                hit = poi
                break
        if hit and hit.get("longitude") is not None and hit.get("latitude") is not None:
            item["longitude"] = float(hit["longitude"])
            item["latitude"] = float(hit["latitude"])
            item["address"] = hit.get("address") or None
            if hit.get("ticket_price") is not None and not item.get("cost"):
                item["cost"] = float(hit["ticket_price"])
            if hit.get("image"):
                item["image"] = hit["image"]
            cache[key] = {
                "lat": item["latitude"],
                "lng": item["longitude"],
                "address": item.get("address"),
                "photo": hit.get("image"),
            }
            return
        cache[key] = None
    except Exception as e:
        logger.warning("local ground failed: %s", e)
        cache[key] = None
