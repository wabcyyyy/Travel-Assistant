"""输出落地阶段的权威事实回填与溯源标注。

知识库永远只是补充证据：本次候选快照里命中的条目才回填坐标/票价/营业时间并给出
质量背书；未命中的模型自选地点必须如实标为生成值、出发前复核。

背书判定本身不在这里（也不该在这里）：三条链路共用
`grounding_labels.label_for_*`，本模块只负责"回填哪些字段 + 登记来源记录"。

边界形状（G-1.6）：权威行（只读）用 generation_core.PoiFactRow TypedDict
推断已知键类型；item 是**每步可缺键的可变草稿**，开放 dict[str, Any] 才是
它的诚实类型（TypedDict(total=False) 的读写严格度与这条链不匹配）。
"""

from __future__ import annotations

from typing import Any, cast

from app.agent.generation.content.reflect import parse_time
from app.agent.generation.rules.generation_core import PoiFactRow
from app.agent.grounding.facts import has_coord
from app.agent.grounding.grounding_labels import (
    apply_label,
    has_valid_coords,
    is_trusted_row,
    label_for_evidence_row,
    label_for_landed_item,
    source_record_for,
)
from app.schemas.trip import SourceRecord


def build_lookup(
    candidates: list[dict[str, Any]] | None, foods: list[dict[str, Any]] | None, hotels: list[dict[str, Any]] | None
) -> dict[str, PoiFactRow]:
    """名字 → 本次候选快照的权威事实行。

    酒店同样属于权威事实源：若遗漏，格式化阶段会把已知城市的酒店误判为开放模式
    LLM 生成，导致来源和质量状态失真。
    """
    lookup: dict[str, PoiFactRow] = {}
    for poi in (candidates or []) + (foods or []) + (hotels or []):
        name = poi.get("name")
        if name and name not in lookup:
            lookup[name] = cast(PoiFactRow, poi)
    return lookup


def apply_item_facts(
    item: dict[str, Any],
    poi: PoiFactRow | None,
    source_records: dict[str, SourceRecord],
    *,
    city: str = "",
) -> None:
    """按候选快照回填权威字段，并就地质标溯源与质量状态。"""
    label = label_for_evidence_row(poi) if poi else label_for_landed_item(item, city)
    # 来源不可信的行一个字段都不采纳：伪 source 不只让徽章失真，还能把真实景点
    # 指到调用方自选的坐标与 poi_id 上（P6）。
    if poi and is_trusted_row(poi):
        # 0/0 是缺失坐标的哨兵值（store._row_payload 会把 NULL 写成 0.0），
        # 不能作为权威坐标回填，否则幻觉坐标获得权威背书。
        poi_lat = poi.get("latitude")
        poi_lng = poi.get("longitude")
        if (
            not has_coord(item.get("latitude"))
            and has_valid_coords(poi)
            and poi_lat is not None
            and poi_lng is not None
        ):
            item["latitude"] = float(poi_lat)
            item["longitude"] = float(poi_lng)
        if not item.get("poi_id"):
            item["poi_id"] = str(poi.get("id") or "")
        price = poi.get("ticket_price")
        if not item.get("cost") and price is not None:
            item["cost"] = float(price)
        if item.get("open_time") is None:
            item["open_time"] = poi.get("open_time")
    apply_label(item, label)
    # fact_evidence 延迟构建：前端请求详情时再补充，不阻塞生成流程
    source_records.setdefault(label.source, source_record_for(label, poi))


def sync_duration_from_time_window(item: dict[str, Any]) -> None:
    """时间窗优先：库内典型时长可能与已排 start/end 冲突（西湖 480 vs 150）。"""
    start = parse_time(item.get("start_time"))
    end = parse_time(item.get("end_time"))
    if start is not None and end is not None and end > start:
        item["duration_min"] = end - start
