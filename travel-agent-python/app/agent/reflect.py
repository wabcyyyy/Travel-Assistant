"""生成结果的自我校验（reflect）层：纯规则检查行程是否合理。

职责：
- validate_plans：检查每日时间冲突、营业时间覆盖、POI 间可达性、景点过多/行程过满，
  返回 (问题列表, 日志列表)；
- build_feedback：把校验问题拼成可回喂给 LLM 的修复反馈文本。

实现要点：
- 全部为无副作用的确定性规则，配合 workflow 的“生成 → 校验 → 修复”循环；
- 单日饱和度由阈值常量（MAX_DAILY_MINUTES / MAX_DAILY_ATTRACTIONS）控制。

依赖：无内部依赖（叶子模块）。
"""

import math
import re
from typing import Any

from app.agent.geo import haversine_meters

MAX_DAILY_MINUTES = 480
MAX_DAILY_ATTRACTIONS = 4
# 不是实时路况：使用城市道路折算 + 安全余量，避免把行程排到“理论刚好可达”。
ROUTE_SPEED_KMH = 25.0
ROAD_DISTANCE_FACTOR = 1.35
ROUTE_BUFFER_RATIO = 0.25
ROUTE_FIXED_BUFFER_MIN = 10

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(value: str | None) -> int | None:
    if not value:
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _parse_open_window(open_time: str | None) -> tuple[int, int] | None:
    if not open_time:
        return None
    ranges = re.findall(r"(\d{1,2}):(\d{2})\s*[-~至]\s*(\d{1,2}):(\d{2})", open_time)
    if not ranges:
        return None
    start = int(ranges[0][0]) * 60 + int(ranges[0][1])
    end = int(ranges[0][2]) * 60 + int(ranges[0][3])
    return start, end


def _item_start(item: dict) -> int:
    return parse_time(item.get("start_time")) or 0


def _item_end(item: dict) -> int:
    end = parse_time(item.get("end_time"))
    if end is not None:
        return end
    start = _item_start(item)
    duration = item.get("duration_min")
    return start + int(duration or 120)


def estimate_transfer_minutes(first: dict, second: dict) -> int | None:
    """按 POI 坐标估算保守换乘时间；缺坐标时返回 None，不猜路线。"""
    coords = (first.get("latitude"), first.get("longitude"),
              second.get("latitude"), second.get("longitude"))
    if any(value is None for value in coords):
        return None
    try:
        distance_m = haversine_meters(*(float(value) for value in coords))
    except (TypeError, ValueError):
        return None
    base = max(5.0, distance_m * ROAD_DISTANCE_FACTOR / (ROUTE_SPEED_KMH * 1000 / 60))
    # 固定 10 分钟处理离场、找出口/停车点，比例余量处理拥堵和地图误差。
    return math.ceil(base * (1 + ROUTE_BUFFER_RATIO) + ROUTE_FIXED_BUFFER_MIN)


def validate_plans(daily_plans: list[dict]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    log: list[str] = []
    for plan in daily_plans:
        day_no = plan.get("day_no")
        items = plan.get("items") or []
        if not items:
            log.append(f"第 {day_no} 天无行程项")
            continue

        timed = [it for it in items if it.get("item_type") in ("attraction", "food")]
        timed.sort(key=_item_start)
        for i in range(len(timed) - 1):
            prev, nxt = timed[i], timed[i + 1]
            prev_end = _item_end(prev)
            next_start = _item_start(nxt)
            if prev_end > next_start:
                issues.append(
                    f"第 {day_no} 天时间冲突：{prev.get('poi_name')}({prev.get('start_time')}-{prev.get('end_time')}) "
                    f"与 {nxt.get('poi_name')}({nxt.get('start_time')}) 重叠"
                )
                continue
            required_transfer = estimate_transfer_minutes(prev, nxt)
            available_gap = next_start - prev_end
            if required_transfer is not None and available_gap < required_transfer:
                issues.append(
                    f"第 {day_no} 天路线时间不足：{prev.get('poi_name')} → {nxt.get('poi_name')} "
                    f"仅留 {available_gap} 分钟，按坐标估算需约 {required_transfer} 分钟"
                    f"（含 {ROUTE_FIXED_BUFFER_MIN} 分钟固定缓冲和 {ROUTE_BUFFER_RATIO:.0%} 容错）"
                )

        for it in items:
            if it.get("item_type") != "attraction":
                continue
            start = _item_start(it)
            window = _parse_open_window(it.get("open_time"))
            end = _item_end(it)
            if window and not (window[0] <= start and end <= window[1]):
                issues.append(
                    f"第 {day_no} 天开放时间不符：{it.get('poi_name')} 计划 "
                    f"{it.get('start_time')}-{it.get('end_time')}，"
                    f"开放时间 {it.get('open_time')}"
                )

        attractions = [it for it in items if it.get("item_type") == "attraction"]
        active = [it for it in items if it.get("item_type") in ("attraction", "food")]
        total = sum(_item_end(it) - _item_start(it) for it in active)
        if len(attractions) > MAX_DAILY_ATTRACTIONS:
            issues.append(f"第 {day_no} 天景点过多（{len(attractions)} 个，上限 {MAX_DAILY_ATTRACTIONS}）")
        if total > MAX_DAILY_MINUTES:
            issues.append(f"第 {day_no} 天行程过满（约 {total} 分钟，上限 {MAX_DAILY_MINUTES}）")

    if issues:
        log.append(f"发现 {len(issues)} 个问题：")
        log.extend(issues)
    else:
        log.append("校验通过：无时间冲突 / 路线可达 / 营业时间覆盖 / 单日饱和度正常")
    return issues, log


def build_feedback(issues: list[str]) -> str:
    return "；".join(issues) if issues else ""
