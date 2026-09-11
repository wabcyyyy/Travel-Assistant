"""路线服务适配层。

路线是旅行规划中的事实数据，不应由模型猜测。本模块提供一个很薄的、可
替换的路线服务：配置高德 Web API 时使用真实步行/驾车耗时；未配置、超时
或接口异常时回退到坐标估算，并在结果中保留 ``degraded`` 标记。

对外只暴露领域契约，优化器和校验器不需要知道底层是高德 REST、MCP 还是
测试替身。进程内缓存用于避免同一轮规划重复查询同一条边。
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime
from typing import Any, Callable

import httpx

from app.agent.geo import haversine_meters
from app.agent.trace import record_event
from app.common.config import settings
from app.integrations import google_maps


ROUTE_SPEED_KMH = 25.0
ROAD_DISTANCE_FACTOR = 1.35
ROUTE_BUFFER_RATIO = 0.25
ROUTE_FIXED_BUFFER_MIN = 10

RouteFetcher = Callable[[dict, dict, str, str | None], dict | None]

_route_cache: dict[tuple, tuple[float, dict]] = {}
# 缓存只在读时判 TTL，过期项永不清理会无界增长（每次路线查询写一条）。
# 写入时做一次轻量清扫，并设硬上限兜底。
_ROUTE_CACHE_MAX = 2000


def _prune_route_cache(now: float) -> None:
    if len(_route_cache) < _ROUTE_CACHE_MAX:
        return
    expired = [key for key, (stored_at, _) in _route_cache.items()
               if now - stored_at > settings.route_cache_ttl]
    for key in expired:
        _route_cache.pop(key, None)
    # 仍超限时按写入时间淘汰最旧的（近似 LRU，避免无界内存）。
    while len(_route_cache) >= _ROUTE_CACHE_MAX:
        oldest = min(_route_cache.items(), key=lambda kv: kv[1][0])[0]
        _route_cache.pop(oldest, None)


def _coords(item: dict) -> tuple[float, float] | None:
    try:
        lat = item.get("latitude")
        lng = item.get("longitude")
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _item_key(item: dict) -> str:
    value = item.get("poi_id") or item.get("id") or item.get("poi_name") or item.get("name")
    if value:
        return str(value)
    coords = _coords(item)
    return ":".join(f"{part:.6f}" for part in coords) if coords else "unknown"


def _departure_hour(departure_time: str | datetime | None) -> int | None:
    if isinstance(departure_time, datetime):
        return departure_time.hour
    if isinstance(departure_time, str):
        try:
            return datetime.fromisoformat(departure_time).hour
        except ValueError:
            try:
                return int(departure_time.strip().split(":", 1)[0])
            except (ValueError, IndexError):
                return None
    return None


def _peak_factor(departure_time: str | datetime | None) -> float:
    hour = _departure_hour(departure_time)
    if hour is None:
        return 1.0
    return settings.route_peak_factor if hour in set(range(7, 10)) | set(range(17, 20)) else 1.0


def _base_result(first: dict, second: dict, mode: str, *, source: str,
                 distance_m: float, duration_min: int, confidence: float,
                 degraded: bool, departure_time: str | datetime | None = None,
                 fallback_reason: str | None = None) -> dict:
    result = {
        "from_poi_id": _item_key(first),
        "to_poi_id": _item_key(second),
        "mode": mode,
        "distance_m": round(max(distance_m, 0.0), 1),
        "duration_min": max(int(duration_min), 0),
        "source": source,
        "fetched_at": datetime.now().astimezone().isoformat(),
        "confidence": confidence,
        "degraded": degraded,
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    factor = _peak_factor(departure_time)
    if factor != 1.0:
        result["base_duration_min"] = result["duration_min"]
        result["peak_factor"] = factor
        result["duration_min"] = math.ceil(result["duration_min"] * factor)
    return result


def coordinate_estimate(first: dict, second: dict, mode: str = "walking",
                        departure_time: str | datetime | None = None,
                        reason: str = "route_service_unavailable") -> dict | None:
    """使用坐标产生保守估算；任一地点缺坐标时不猜路线。"""
    first_coords = _coords(first)
    second_coords = _coords(second)
    if first_coords is None or second_coords is None:
        return None
    distance_m = haversine_meters(*first_coords, *second_coords)
    speed_kmh = 25.0 if mode == "walking" else 32.0
    base = max(5.0, distance_m * ROAD_DISTANCE_FACTOR / (speed_kmh * 1000 / 60))
    duration = math.ceil(base * (1 + ROUTE_BUFFER_RATIO) + ROUTE_FIXED_BUFFER_MIN)
    return _base_result(
        first, second, mode, source="coordinate-estimate", distance_m=distance_m,
        duration_min=duration, confidence=0.45, degraded=True,
        departure_time=departure_time, fallback_reason=reason,
    )


def _extract_amap_result(payload: dict, first: dict, second: dict, mode: str,
                         departure_time: str | datetime | None) -> dict:
    if str(payload.get("status", "1")) not in {"1", "true", "True"}:
        raise ValueError(payload.get("info") or "高德路线接口返回失败")
    route = payload.get("route") or {}
    paths = route.get("paths") or route.get("taxi") or []
    if not paths:
        raise ValueError("高德路线接口未返回可行路径")
    path = paths[0] if isinstance(paths, list) else paths
    distance = float(path.get("distance") or path.get("distance_m") or 0)
    raw_duration = path.get("duration") or path.get("duration_s")
    if raw_duration is None and path.get("duration_min") is not None:
        duration_min = math.ceil(float(path["duration_min"]))
    else:
        duration_min = math.ceil(float(raw_duration or 0) / 60)
    if distance <= 0 or duration_min <= 0:
        raise ValueError("高德路线接口返回了无效距离或耗时")
    return _base_result(
        first, second, mode, source="amap", distance_m=distance,
        duration_min=duration_min, confidence=0.95, degraded=False,
        departure_time=departure_time,
    )


def fetch_amap_route(first: dict, second: dict, mode: str,
                     departure_time: str | datetime | None = None) -> dict | None:
    """调用高德 v5 路线接口。异常由上层捕获并触发坐标降级。"""
    if not settings.amap_web_key:
        return None
    first_coords = _coords(first)
    second_coords = _coords(second)
    if first_coords is None or second_coords is None:
        return None
    if mode not in {"walking", "driving"}:
        raise ValueError(f"暂不支持的路线模式：{mode}")
    endpoint = f"https://restapi.amap.com/v5/direction/{mode}"
    params = {
        "key": settings.amap_web_key,
        "origin": f"{first_coords[1]},{first_coords[0]}",
        "destination": f"{second_coords[1]},{second_coords[0]}",
    }
    response = httpx.get(endpoint, params=params, timeout=settings.route_timeout)
    response.raise_for_status()
    return _extract_amap_result(response.json(), first, second, mode, departure_time)


def fetch_google_route(first: dict, second: dict, mode: str,
                       departure_time: str | datetime | None = None) -> dict | None:
    """调用 Google Routes API（国外目的地兜底）。异常由上层捕获并触发坐标降级。"""
    if not google_maps.enabled():
        return None
    first_coords = _coords(first)
    second_coords = _coords(second)
    if first_coords is None or second_coords is None:
        return None
    if mode not in {"walking", "driving"}:
        raise ValueError(f"暂不支持的路线模式：{mode}")
    travel_mode = "WALK" if mode == "walking" else "DRIVE"
    raw = google_maps.compute_route(first_coords, second_coords, travel_mode=travel_mode)
    if raw is None:
        return None
    return _base_result(
        first, second, mode, source="google", distance_m=raw["distance_m"],
        duration_min=raw["duration_min"], confidence=0.9, degraded=False,
        departure_time=departure_time,
    )


def _with_peak_factor(result: dict | None,
                      departure_time: str | datetime | None) -> dict | None:
    """对路线结果统一做高峰系数修正（注入的供应商/测试替身同样适用）。"""
    if result is None or not departure_time or "base_duration_min" in result:
        return result
    factor = _peak_factor(departure_time)
    if factor != 1.0:
        result = dict(result)
        result["base_duration_min"] = int(result.get("duration_min") or 0)
        result["peak_factor"] = factor
        result["duration_min"] = math.ceil(result["base_duration_min"] * factor)
    return result


class RouteService:
    """带缓存和降级策略的路线服务，可通过 ``fetcher`` 注入测试/其他供应商。"""

    def __init__(self, fetcher: RouteFetcher | None = None):
        self.fetcher = fetcher or fetch_amap_route
        self._custom_fetcher = fetcher is not None
        self._local = threading.local()

    def get_route(self, first: dict, second: dict, *, mode: str = "walking",
                  departure_time: str | datetime | None = None) -> dict | None:
        first_key, second_key = _item_key(first), _item_key(second)
        cache_key = (
            first_key, second_key, tuple(_coords(first) or ()), tuple(_coords(second) or ()),
            mode, str(departure_time or ""),
        )
        now = time.monotonic()
        cached = _route_cache.get(cache_key)
        if cached and now - cached[0] <= settings.route_cache_ttl:
            return dict(cached[1])

        result: dict | None = None
        if settings.route_service_enabled or self._custom_fetcher:
            calls = getattr(self._local, "calls", 0)
            if calls >= settings.route_max_calls:
                fallback_reason = "route_call_budget_exhausted"
                result = None
            else:
                self._local.calls = calls + 1
                try:
                    result = self.fetcher(first, second, mode, departure_time)
                except Exception as exc:  # noqa: BLE001 - 外部路线服务必须可降级
                    record_event("tool", "route.fetch", status="error", error=str(exc), metadata={"mode": mode})
                    result = None
                    fallback_reason = "route_service_error"
                else:
                    fallback_reason = "route_service_empty"
        else:
            fallback_reason = "route_service_disabled"

        result = _with_peak_factor(result, departure_time)

        # Provider chain：高德（中国境内）失败/为空 → Google Routes（国外兜底）。
        if result is None and google_maps.enabled():
            calls = getattr(self._local, "calls", 0)
            if calls >= settings.route_max_calls:
                fallback_reason = "google_route_budget_exhausted"
            else:
                self._local.calls = calls + 1
                try:
                    result = fetch_google_route(first, second, mode, departure_time)
                except Exception as exc:  # noqa: BLE001 - 外部路线服务必须可降级
                    record_event("tool", "route.fetch", status="error", error=str(exc),
                                 metadata={"mode": mode, "provider": "google"})
                    result = None
                    fallback_reason = "google_route_error"
                else:
                    fallback_reason = "google_route_empty"
                result = _with_peak_factor(result, departure_time)

        if result is None:
            result = coordinate_estimate(
                first, second, mode, departure_time, reason=fallback_reason,
            )
        if result is not None:
            _prune_route_cache(now)
            _route_cache[cache_key] = (now, dict(result))
            record_event("tool", "route.get", metadata={
                "mode": mode,
                "source": result["source"],
                "degraded": result["degraded"],
                "duration_min": result["duration_min"],
            })
        return result

    def matrix(self, items: list[dict], *, mode: str = "walking",
               departure_time: str | datetime | None = None) -> dict[tuple[str, str], dict]:
        # 调用预算属于一次矩阵构建，不应在全局单例生命周期内累计。
        self._local.calls = 0
        matrix: dict[tuple[str, str], dict] = {}
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                result = self.get_route(first, second, mode=mode, departure_time=departure_time)
                reverse = self.get_route(second, first, mode=mode, departure_time=departure_time)
                if result is not None:
                    matrix[(_item_key(first), _item_key(second))] = result
                if reverse is not None:
                    matrix[(_item_key(second), _item_key(first))] = reverse
        return matrix


def clear_route_cache() -> None:
    _route_cache.clear()


default_route_service = RouteService()


def get_route_matrix(items: list[dict], *, mode: str = "walking",
                     departure_time: str | datetime | None = None) -> dict[tuple[str, str], dict]:
    return default_route_service.matrix(items, mode=mode, departure_time=departure_time)
