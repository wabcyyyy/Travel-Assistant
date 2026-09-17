"""外部地点数据层：OpenTripMap 为主、Nominatim 兜底、地图深链工具。

POI 权威库退役后的坐标/分类/图片来源（TREK 式"不存语料，事实交给外部活数据"）：

- **OpenTripMap**（OSM+Wikidata 加工的旅游切片）：城市定位（geoname）、景点半径
  检索（坐标/分类/热度）、xid 详情（结构化地址/官网/图片/维基简介）。免费 key，
  仅 en/ru 两种语言——返回名称为英文，中文名由生成链路的 LLM 对齐；
- **Nominatim**（OSM 官方地理编码）：任意名称→坐标，OTM 失败或缺 key 时兜底；
  使用政策要求 1 rps 与可联系的 User-Agent；
- **地图深链**：谷歌地图（海外）/ 高德 URI（国内）的搜索与路线链接。纯函数拼
  URL，无 key 无网络，把"事实核实"交给地图 App 的活数据。

事实边界：两家数据源都**没有票价/营业时间**——这些字段由 LLM 估价并按
`estimated` 如实标注，行程页以深链引导用户出发前自行核实。

依赖：common（external_client/http_client/config）；无 agent 内部依赖，无数据库。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from app.common.config import settings
from app.common.external_client import ExternalClient
from app.common.http_client import api_client

logger = logging.getLogger(__name__)

_OTM_BASE = "https://api.opentripmap.com/0.1/en"
_NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"
# 与 wikipedia 图片通道一致的 UA 策略（Nominatim 政策要求可联系的标识）
_NOMINATIM_UA = "TravelAssistantDemo/1.0 (student-project; contact=dev@localhost.invalid)"

_AMAP_SRC = "travel-assistant"


def otm_enabled() -> bool:
    return bool(str(settings.otm_api_key or "").strip())


# ---- 缓存/节流通道（G-3.2） -------------------------------------------------
# 城市坐标与地点详情基本不变：成功缓存 24h；半径检索 6h（新开景点能较快出现）。
_otm_geo_client: ExternalClient = ExternalClient(
    name="otm_geoname",
    ttl_seconds=24 * 3600,
    negative_ttl_seconds=300,
    timeout_seconds=settings.places_timeout_seconds,
)
_otm_radius_client: ExternalClient = ExternalClient(
    name="otm_radius",
    ttl_seconds=6 * 3600,
    negative_ttl_seconds=600,
    timeout_seconds=settings.places_timeout_seconds,
)
_otm_detail_client: ExternalClient = ExternalClient(
    name="otm_detail",
    ttl_seconds=24 * 3600,
    negative_ttl_seconds=1800,
    timeout_seconds=settings.places_timeout_seconds,
)
# Nominatim 政策：公共实例 1 rps —— 显式放宽车道间隔到 1.1s。
_nominatim_client: ExternalClient = ExternalClient(
    name="nominatim",
    ttl_seconds=24 * 3600,
    negative_ttl_seconds=600,
    timeout_seconds=settings.places_timeout_seconds,
    min_interval_seconds=1.1,
)


def _otm_get(path: str, params: dict[str, Any], client: ExternalClient) -> Any:
    key = str(settings.otm_api_key or "").strip()
    if not key:
        return None
    params = {**params, "apikey": key}
    payload = client.call(
        f"{path}:{sorted(params.items(), key=lambda kv: kv[0])}",
        lambda: api_client().get(f"{_OTM_BASE}/{path}", params=params).json(),
    )
    if isinstance(payload, dict) and payload.get("error"):
        logger.warning("otm[%s] error: %s", path, str(payload["error"])[:120])
        return None
    return payload


# ---- OpenTripMap：城市定位 / 半径检索 / 详情 ---------------------------------


def resolve_city_center(city_en: str) -> dict[str, Any] | None:
    """城市名（建议英文）→ 中心坐标与国家；OTM 不可用返回 None。"""
    name = str(city_en or "").strip()
    if not name:
        return None
    row = _otm_get("places/geoname", {"name": name[:64]}, _otm_geo_client)
    if not isinstance(row, dict) or row.get("lat") is None or row.get("lon") is None:
        return None
    return {
        "name": str(row.get("name") or name),
        "country": str(row.get("country") or ""),
        "country_code": str(row.get("country") or ""),
        "latitude": float(row["lat"]),
        "longitude": float(row["lon"]),
    }


def _normalize_place(
    row: dict[str, Any], *, city: str | None = None, category: str = "attraction"
) -> dict[str, Any] | None:
    """OTM 列表行 → 统一地点条目；空名/缺坐标的行丢弃（name:"" 的 OSM 节点不少见）。"""
    point = row.get("point") or {}
    name = str(row.get("name") or "").strip()
    lat_raw, lon_raw = point.get("lat"), point.get("lon")
    if lat_raw is None or lon_raw is None:
        return None
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except (TypeError, ValueError):
        return None
    if not name or (lat == 0.0 and lon == 0.0):
        return None
    rate = row.get("rate")
    if isinstance(rate, str) and rate.isdigit():
        rate = int(rate)
    return {
        "xid": str(row.get("xid") or ""),
        "name": name,
        "category": category,
        "latitude": lat,
        "longitude": lon,
        "dist_m": round(float(row["dist"])) if row.get("dist") is not None else None,
        "popularity": int(rate) if isinstance(rate, (int, float)) else None,
        "kinds": str(row.get("kinds") or ""),
        "source": "opentripmap",
        "city": city,
    }


def search_places_near(
    latitude: float,
    longitude: float,
    *,
    radius_m: int | None = None,
    limit: int | None = None,
    city: str | None = None,
    kinds: str | None = None,
    category: str = "attraction",
) -> list[dict[str, Any]]:
    """以坐标为圆心的地点检索（热度降序）；kinds 传 OTM 分类（如 foods）可收窄。

    OTM 不可用返回空，由上层降级为联网搜索/纯 LLM。
    """
    if not otm_enabled():
        return []
    params: dict[str, Any] = {
        "radius": int(radius_m or settings.otm_radius_m),
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "limit": int(limit or settings.otm_limit),
        "sort": "-rate",
    }
    if kinds:
        params["kinds"] = kinds
    payload = _otm_get("places/radius", params, _otm_radius_client)
    if not isinstance(payload, list):
        return []
    out = [p for row in payload if isinstance(row, dict) if (p := _normalize_place(row, city=city, category=category))]
    out.sort(key=lambda p: (-(p["popularity"] or 0), p["dist_m"] if p["dist_m"] is not None else 1 << 30))
    return out


def place_detail(xid: str) -> dict[str, Any] | None:
    """xid → 地址/官网/图片/维基简介；用于给头部候选补详情（后台车道）。"""
    row = _otm_get("places/xid/" + quote(str(xid or "")), {}, _otm_detail_client)
    if not isinstance(row, dict):
        return None
    address = row.get("address") or {}
    address_text = " ".join(
        str(address.get(k) or "").strip()
        for k in ("road", "house", "city", "state")
        if str(address.get(k) or "").strip()
    )
    extract = (row.get("wikipedia_extracts") or {}).get("text")
    preview = (row.get("preview") or {}).get("source")
    rate = row.get("rate")
    return {
        "xid": str(row.get("xid") or xid),
        "name": str(row.get("name") or ""),
        "address": address_text or None,
        "url": str(row.get("url") or "") or None,
        "image": preview or (str(row.get("image") or "") or None),
        "intro": str(extract or "").strip() or None,
        "wikipedia": str(row.get("wikipedia") or "") or None,
        "wikidata": str(row.get("wikidata") or "") or None,
        "popularity": int(rate) if isinstance(rate, (int, float)) else None,
        "source": "opentripmap",
    }


def enrich_with_details(places: list[dict[str, Any]], *, top: int = 12) -> list[dict[str, Any]]:
    """给热度最高的前 top 个景点并入详情字段（官网/图片/简介）；后台车道、失败原地保留。"""
    for place in places[:top]:
        detail = place_detail(str(place.get("xid") or ""))
        if not detail:
            continue
        for key in ("address", "url", "image", "intro", "wikipedia", "wikidata"):
            if detail.get(key) and not place.get(key):
                place[key] = detail[key]
    return places


# ---- Nominatim 兜底 ---------------------------------------------------------


def geocode_place(name: str, city: str | None = None) -> dict[str, Any] | None:
    """名称（可带城市）→ 坐标；OTM 是分类检索、兜不了"点名解析"，由 Nominatim 承担。"""
    query = " ".join(part for part in (str(name or "").strip(), str(city or "").strip()) if part)
    if not query:
        return None
    payload = _nominatim_client.call(
        f"q:{query[:120]}",
        lambda: (
            api_client()
            .get(
                _NOMINATIM_BASE,
                params={"q": query[:120], "format": "jsonv2", "limit": 1},
                headers={"User-Agent": _NOMINATIM_UA, "Accept-Language": "zh,en"},
            )
            .json()
        ),
    )
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    try:
        return {
            "name": str(row.get("name") or name),
            "display_name": str(row.get("display_name") or ""),
            "latitude": float(row["lat"]),
            "longitude": float(row["lon"]),
            "source": "nominatim",
        }
    except (TypeError, ValueError, KeyError):
        return None


# ---- 地图深链（纯函数，无网络） ----------------------------------------------


def _in_china(latitude: float, longitude: float) -> bool:
    return 18.0 <= latitude <= 54.0 and 73.0 <= longitude <= 135.0


def _looks_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _is_domestic(latitude: float | None, longitude: float | None, city: str) -> bool:
    """坐标优先（国界框），无坐标按城市名是否含汉字——只是链接选择提示，错选不致命。"""
    try:
        if latitude is not None and longitude is not None:
            return _in_china(float(latitude), float(longitude))
    except (TypeError, ValueError):
        pass
    return _looks_chinese(city)


def map_search_url(name: str, city: str, *, latitude: float | None = None, longitude: float | None = None) -> str:
    """单点"地图核实"链接：国内高德、海外谷歌；有坐标用 marker/marker 语义，否则关键词搜索。"""
    label = str(name or "").strip()
    if _is_domestic(latitude, longitude, city):
        try:
            if latitude is not None and longitude is not None and float(latitude) and float(longitude):
                return (
                    f"https://uri.amap.com/marker?position={float(longitude)},{float(latitude)}"
                    f"&name={quote(label)}&src={_AMAP_SRC}&callnative=0"
                )
        except (TypeError, ValueError):
            pass
        keyword = f"{label} {str(city or '').strip()}".strip()
        return f"https://uri.amap.com/search?keyword={quote(keyword)}&src={_AMAP_SRC}&callnative=0"
    query = quote(f"{label} {str(city or '').strip()}".strip())
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def map_directions_url(stops: list[dict[str, Any]]) -> str | None:
    """全天路线链接：取有有效坐标的停靠点串 waypoint；少于 2 点返回 None。

    国内走高德 navigation（from/to/via，坐标必须）；海外走谷歌 dir
    （waypoints 支持坐标）。
    """
    points: list[tuple[str, float, float]] = []
    for stop in stops:
        lat_raw, lon_raw = stop.get("latitude"), stop.get("longitude")
        if lat_raw is None or lon_raw is None:
            continue
        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except (TypeError, ValueError):
            continue
        if not lat or not lon:
            continue
        points.append((str(stop.get("poi_name") or stop.get("name") or ""), lat, lon))
    if len(points) < 2:
        return None
    domestic = _in_china(points[0][1], points[0][2])

    def _coord(point: tuple[str, float, float]) -> str:
        return f"{point[2]},{point[1]}"

    if domestic:
        via = ";".join(_coord(p) for p in points[1:-1])
        url = (
            f"https://uri.amap.com/navigation?from={_coord(points[0])}&to={_coord(points[-1])}"
            f"&mode=car&policy=1&src={_AMAP_SRC}&coordinate=gaode&callnative=0"
        )
        return f"{url}&via={via}" if via else url
    origin = quote(points[0][0] or _coord(points[0]))
    destination = quote(points[-1][0] or _coord(points[-1]))
    waypoints = quote("|".join(_coord(p) for p in points[1:-1]))
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}"
    return f"{url}&waypoints={waypoints}" if waypoints else url
