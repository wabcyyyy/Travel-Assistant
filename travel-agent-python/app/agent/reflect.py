import re
from typing import Any

MAX_DAILY_MINUTES = 480
MAX_DAILY_ATTRACTIONS = 4

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
            if _item_end(prev) > _item_start(nxt):
                issues.append(
                    f"第 {day_no} 天时间冲突：{prev.get('poi_name')}({prev.get('start_time')}-{prev.get('end_time')}) "
                    f"与 {nxt.get('poi_name')}({nxt.get('start_time')}) 重叠"
                )

        for it in items:
            if it.get("item_type") != "attraction":
                continue
            start = _item_start(it)
            window = _parse_open_window(it.get("open_time"))
            if window and not (window[0] <= start <= window[1]):
                issues.append(
                    f"第 {day_no} 天开放时间不符：{it.get('poi_name')} 计划 {it.get('start_time')} 进入，"
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
        log.append("校验通过：无时间冲突 / 开放时间匹配 / 单日饱和度正常")
    return issues, log


def build_feedback(issues: list[str]) -> str:
    return "；".join(issues) if issues else ""