"""轻量 GraphRAG：同城坐标网格近邻 + 标签相邻（P2）。

设计取向是"轻"：不引入图数据库或图索引库，只用内存里的两级结构——

* 空间层：城市 → 0.02° 网格（约 2km）→ POI id；近邻查询只扫描半径覆盖
  的网格环，再用 haversine 精确过滤，复杂度与候选密度无关而与半径有关；
* 标签层：城市 → 标签词 → POI id，支持"同类推荐"。

图只在 set_documents/索引同步时重建（进程内、线程安全读），坐标缺失
（0/None）的 POI 不进入空间层，避免种子期伪造坐标式的错误近邻。
供"附近推荐"类查询与检索结果扩展使用，不改变权威数据边界。
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from app.agent.geo import haversine_meters
from app.common.config import settings

_CELL_DEG = 0.02
# 中国境内纬度范围一格经度约 1.55~2.22km；按最小值估算需要扫描的网格环。
_CELL_MIN_METERS = 1550.0
_TAG_SPLIT = (" ", ",", "，", "、", ";", "；", "/", "|")


def _valid_coords(latitude: Any, longitude: Any) -> bool:
    try:
        lat, lng = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return False
    # 0/0 不是中国境内坐标：视为缺失（_row_payload 会把 NULL 坐标写成 0.0）。
    # 必须两轴都非零：lat=0 而 lng 有值的坏行若入图，haversine 会算出
    # 跨千里的错误"近邻"。
    return abs(lat) > 1e-6 and abs(lng) > 1e-6


class PoiGraph:
    """进程内 POI 近邻图：空间网格 + 标签倒排，索引同步时全量重建。"""

    def __init__(self, *, radius_m: int | None = None) -> None:
        self.radius_m = int(radius_m or settings.rag_graph_radius_m)
        self._nodes: dict[str, dict[str, Any]] = {}
        self._grid: dict[tuple[str, int, int], list[str]] = {}
        self._tags: dict[tuple[str, str], list[str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _split_tags(tags: Any) -> list[str]:
        tokens = _split_by(str(tags or ""), (*_TAG_SPLIT, "|"))
        return sorted({token.strip() for token in tokens if token.strip()})

    def rebuild(self, documents: dict[str, dict[str, Any]]) -> dict[str, int]:
        """从检索器文档目录重建图；文档结构为 pid -> {metadata: {...}}。"""
        nodes: dict[str, dict[str, Any]] = {}
        grid: dict[tuple[str, int, int], list[str]] = {}
        tags: dict[tuple[str, str], list[str]] = {}
        for pid, item in documents.items():
            meta = item.get("metadata") or {}
            if meta.get("id") is None or not str(meta.get("name") or "").strip():
                continue
            city = str(meta.get("city") or "")
            nodes[pid] = meta
            if _valid_coords(meta.get("latitude"), meta.get("longitude")):
                lat, lng = float(meta["latitude"]), float(meta["longitude"])
                grid.setdefault((city, int(lat / _CELL_DEG), int(lng / _CELL_DEG)), []).append(pid)
            for tag in self._split_tags(meta.get("tags")):
                tags.setdefault((city, tag), []).append(pid)
        with self._lock:
            self._nodes, self._grid, self._tags = nodes, grid, tags
        return self.stats()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "nodes": len(self._nodes),
                "cities": len({city for city, _, _ in self._grid} | {city for city, _ in self._tags}),
                "grid_cells": len(self._grid),
                "tag_edges": sum(len(pids) for pids in self._tags.values()),
            }

    def neighbors(
        self, poi_id: str | int, *, limit: int | None = None, radius_m: int | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        """给定 POI 的同城近邻：距离升序，不含自身。"""
        with self._lock:
            meta = self._nodes.get(str(poi_id))
            if not meta or not _valid_coords(meta.get("latitude"), meta.get("longitude")):
                return []
            return self._spatial_query(
                str(meta.get("city") or ""),
                float(meta["latitude"]),
                float(meta["longitude"]),
                exclude={str(poi_id)},
                limit=limit,
                radius_m=radius_m,
                category=category,
            )

    def nearby(
        self,
        city: str,
        latitude: float,
        longitude: float,
        *,
        limit: int | None = None,
        radius_m: int | None = None,
        category: str | None = None,
        exclude: str | int | None = None,
    ) -> list[dict[str, Any]]:
        """给定坐标的同城近邻（供地图点位/“附近推荐”使用）。

        ``exclude`` 用于锚点 POI 自身的 id：按名称解析锚点坐标后查询时，
        “西湖附近”不应把西湖自己排进结果。
        """
        if not _valid_coords(latitude, longitude):
            return []
        with self._lock:
            return self._spatial_query(
                str(city or ""),
                float(latitude),
                float(longitude),
                exclude={str(exclude)} if exclude is not None else set(),
                limit=limit,
                radius_m=radius_m,
                category=category,
            )

    def same_tag(self, poi_id: str | int, *, limit: int | None = None) -> list[dict[str, Any]]:
        """同城市、标签重合度最高的同类 POI（标签相邻层）。"""
        with self._lock:
            meta = self._nodes.get(str(poi_id))
            if not meta:
                return []
            city = str(meta.get("city") or "")
            own_tags = set(self._split_tags(meta.get("tags")))
            if not own_tags:
                return []
            candidate_counter: Counter[str] = Counter()
            for tag in own_tags:
                for pid in self._tags.get((city, tag), []):
                    if pid != str(poi_id):
                        candidate_counter[pid] += 1
            top_n = max(limit or settings.rag_graph_nearby_limit, 1)
            # 标签重合度优先（图的边语义），评分其次，id 保持稳定序。
            ranked = sorted(
                candidate_counter.items(),
                key=lambda pair: (-pair[1], -(float(self._nodes[pair[0]].get("rating") or 0.0)), pair[0]),
            )[:top_n]
            results: list[dict[str, Any]] = []
            for pid, shared in ranked:
                row = dict(self._nodes[pid])
                row["_shared_tags"] = shared
                results.append(row)
            return results

    def _spatial_query(
        self,
        city: str,
        latitude: float,
        longitude: float,
        *,
        exclude: set[str],
        limit: int | None,
        radius_m: int | None,
        category: str | None,
    ) -> list[dict[str, Any]]:
        radius = float(radius_m or self.radius_m)
        top_n = max(int(limit or settings.rag_graph_nearby_limit), 1)
        ring = max(int(radius / _CELL_MIN_METERS) + 1, 1)
        cx, cy = int(latitude / _CELL_DEG), int(longitude / _CELL_DEG)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                for pid in self._grid.get((city, cx + dx, cy + dy), []):
                    if pid in exclude:
                        continue
                    meta = self._nodes[pid]
                    if category and meta.get("category") != category:
                        continue
                    distance = haversine_meters(latitude, longitude, float(meta["latitude"]), float(meta["longitude"]))
                    if distance <= radius:
                        scored.append((distance, pid, meta))
        scored.sort(key=lambda value: (value[0], value[1]))
        results: list[dict[str, Any]] = []
        for distance, _, meta in scored[:top_n]:
            row = dict(meta)
            row["_distance_m"] = round(distance)
            results.append(row)
        return results


def _split_by(text: str, separators: tuple[str, ...]) -> list[str]:
    for separator in separators:
        text = text.replace(separator, "|")
    return text.split("|")
