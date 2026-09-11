"""Google Maps / OSM 国外地理提供商（provider chain: 高德 → Google → Nominatim）。

高德仅覆盖中国境内；国外城市检索/落坐标/路线经本模块处理。Provider chain：
1) 高德命中即返回（国内零回归）；2) 高德空 → Google Places/Routes（需 key+绑卡，
   $200/月免费额度）；3) Google 不可用（无 key / 未绑卡）→ OSM Nominatim 免 key
   兜底落真实坐标（POI 语义弱于 Places，路线退回坐标估算）。

安全边界：API Key 只从服务端环境变量读取；调用失败一律返回空/None，由上层
降级（坐标估算/空证据包），绝不让外部地理服务拖垮生成主流程。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.common.config import settings
from app.agent.trace import record_event

logger = logging.getLogger(__name__)

_PLACES_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
# OSM Nominatim：免 key/免绑卡的国外坐标兜底（Google Places 需绑卡启用）。
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim 在国内网络经常超时；连续失败后熔断，避免把 Agent 总 Deadline
# 耗在重复空等上（否则开放研究会整体失败并降级为「待研究草案」）。
_NOMINATIM_TIMEOUT = min(settings.google_maps_timeout, 3.0)
_NOMINATIM_FAIL_THRESHOLD = 2
_NOMINATIM_BREAK_SECONDS = 120.0
_nom_lock = threading.Lock()
_nom_fail_streak = 0
_nom_open_until = 0.0

# Places includedType：把品类映射到 Google 类型，提升检索相关性。
_INCLUDED_TYPES = {
    "attraction": "tourist_attraction",
    "food": "restaurant",
    "hotel": "lodging",
}


def enabled() -> bool:
    return bool((settings.google_maps_api_key or "").strip())


def _headers() -> dict:
    return {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "Content-Type": "application/json",
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def search_text(keywords: str, city: str | None = None, *, category: str | None = None,
                limit: int = 10) -> dict | None:
    """Google Places Text Search（POST）；异常由调用方捕获降级。"""
    query = " ".join(x for x in (keywords, city) if x) or (city or "")
    payload: dict[str, Any] = {"textQuery": query[:200], "pageSize": limit,
                               "languageCode": "zh-CN"}
    included = _INCLUDED_TYPES.get(category or "")
    if included:
        payload["includedType"] = included
    resp = httpx.post(_PLACES_TEXT_URL, json=payload, headers=_headers(),
                      timeout=settings.google_maps_timeout)
    resp.raise_for_status()
    return resp.json()


def normalize_pois(payload: dict | None, category: str | None = None) -> list[dict]:
    """Google Places 结果 → 项目内部 POI 契约（含来源 google.places）。"""
    if not payload:
        return []
    fetched_at = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for raw in payload.get("places") or []:
        name = str(((raw.get("displayName") or {}).get("text") or "")).strip()
        location = raw.get("location") or {}
        latitude, longitude = _number(location.get("latitude")), _number(location.get("longitude"))
        if not name or latitude is None or longitude is None:
            continue
        out.append({
            "id": f"google:{raw.get('id') or name}",
            "name": name,
            "category": category or "attraction",
            "address": raw.get("formattedAddress"),
            "latitude": latitude,
            "longitude": longitude,
            "rating": _number(raw.get("rating")),
            "description": str(((raw.get("editorialSummary") or {}).get("text")) or "").strip() or None,
            "ticket_price": None,
            "open_time": None,
            "tags": None,
            "image": None,
            "source": "google.places",
            "source_fetched_at": fetched_at,
        })
    return out


def search_pois(keywords: str, city: str | None = None, *, category: str | None = None,
                limit: int = 10) -> list[dict]:
    """Google Places POI 检索：失败/未配置 key 返回空列表（由调用方切 Nominatim 兜底）。"""
    if not enabled():
        return []
    try:
        payload = search_text(keywords, city, category=category, limit=limit)
        pois = normalize_pois(payload, category=category)
        record_event("tool", "google.search_pois", metadata={"hits": len(pois)})
        return pois
    except Exception as exc:  # noqa: BLE001 - 外部地理服务失败必须可降级
        logger.warning("google places search failed (%s/%s): %s", city, keywords, exc)
        record_event("tool", "google.search_pois", status="error", error=str(exc))
        return []


def _nominatim_available() -> bool:
    global _nom_open_until
    with _nom_lock:
        return time.monotonic() >= _nom_open_until


def _note_nominatim_failure() -> None:
    global _nom_fail_streak, _nom_open_until
    with _nom_lock:
        _nom_fail_streak += 1
        if _nom_fail_streak >= _NOMINATIM_FAIL_THRESHOLD:
            _nom_open_until = time.monotonic() + _NOMINATIM_BREAK_SECONDS
            logger.warning(
                "nominatim circuit open for %.0fs after %d consecutive failures",
                _NOMINATIM_BREAK_SECONDS, _nom_fail_streak,
            )


def _note_nominatim_success() -> None:
    global _nom_fail_streak, _nom_open_until
    with _nom_lock:
        _nom_fail_streak = 0
        _nom_open_until = 0.0


def search_nominatim(query: str, limit: int = 5) -> list[dict]:
    """OSM Nominatim 检索（免 key）；遵循其 UA/限流政策，异常由调用方捕获。"""
    if not _nominatim_available():
        record_event("tool", "nominatim.search_pois", metadata={"skipped": "circuit_open"})
        return []
    try:
        resp = httpx.get(
            _NOMINATIM_URL,
            params={"q": query[:200], "format": "json", "limit": limit, "addressdetails": 0},
            # Nominatim 使用政策要求可识别、可联系的 UA（勿匿名）。
            headers={"User-Agent": "TravelAssistantDemo/1.0 (student-project; contact=dev@localhost.invalid)",
                     "Accept-Language": "zh-CN,en"},
            timeout=_NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        _note_nominatim_success()
        return resp.json() or []
    except Exception:
        _note_nominatim_failure()
        raise


def normalize_nominatim(rows: list[dict], category: str | None = None) -> list[dict]:
    """Nominatim 结果 → 内部 POI 契约（source=nominatim，坐标为 OSM 真实坐标）。"""
    fetched_at = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for raw in rows or []:
        latitude, longitude = _number(raw.get("lat")), _number(raw.get("lon"))
        display = str(raw.get("display_name") or "").strip()
        if not display or latitude is None or longitude is None:
            continue
        # display_name 是完整地址串；行程展示名优先用 Nominatim 的短 name，
        # 缺失时取地址第一段，避免把整条地址塞进 poiName。
        short_name = str(raw.get("name") or "").strip() or display.split(",")[0].strip() or display[:64]
        out.append({
            "id": f"nominatim:{raw.get('osm_id') or display}",
            "name": short_name[:64],
            "category": category or "attraction",
            "address": display,
            "latitude": latitude,
            "longitude": longitude,
            "rating": None,
            "description": None,
            "ticket_price": None,
            "open_time": None,
            "tags": None,
            "image": None,
            "source": "nominatim",
            "source_fetched_at": fetched_at,
        })
    return out


def search_pois_nominatim(keywords: str, city: str | None = None, *,
                          category: str | None = None) -> list[dict]:
    """免 key 坐标兜底：Google 不可用（未配置/无绑卡）时经 OSM Nominatim 落真实坐标。"""
    if not _nominatim_available():
        return []
    query = " ".join(x for x in (keywords, city) if x) or (city or "")
    try:
        rows = search_nominatim(query, limit=5)
        pois = normalize_nominatim(rows, category=category)
        record_event("tool", "nominatim.search_pois", metadata={"hits": len(pois)})
        return pois
    except Exception as exc:  # noqa: BLE001 - 外部地理服务失败必须可降级
        logger.warning("nominatim search failed (%s/%s): %s", city, keywords, exc)
        record_event("tool", "nominatim.search_pois", status="error", error=str(exc))
        return []


def compute_route(origin: tuple[float, float], destination: tuple[float, float],
                  travel_mode: str = "WALK") -> dict | None:
    """Google Routes API（computeRoutes）单条路线；失败返回 None。"""
    if not enabled():
        return None
    payload = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}}},
        "travelMode": travel_mode,
        "languageCode": "zh-CN",
    }
    resp = httpx.post(
        _ROUTES_URL, json=payload, headers=_headers(),
        params={"key": settings.google_maps_api_key},
        timeout=settings.google_maps_timeout,
    )
    resp.raise_for_status()
    routes = (resp.json().get("routes") or [])
    if not routes:
        return None
    route = routes[0]
    duration_raw = str(route.get("duration") or "0s")
    try:
        duration_min = math.ceil(float(duration_raw.rstrip("s")) / 60)
    except ValueError:
        duration_min = 0
    distance_m = int(route.get("distanceMeters") or 0)
    if duration_min <= 0 or distance_m <= 0:
        return None
    return {"distance_m": distance_m, "duration_min": duration_min}
