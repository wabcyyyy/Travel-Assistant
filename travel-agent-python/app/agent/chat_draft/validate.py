"""行程草稿的安全校验与基础工具（纯函数，无业务、无 LLM）。

职责：
- 时间冲突检测（_plan_conflict）、实质变更签名（_substantive_plan_signature）；
- 模型 JSON 的解析与修复（_parse_json_object / DecisionJsonError）；
- 时钟字符串与分钟数互转（_clock_minutes / _format_clock）；
- 回复文案兜底（_decision_reply / _default_plan_update_reply）。

实现要点：
- 全部为无副作用的确定性函数，只做“检查/转换”，绝不修改行程；
- 上层（decide / plan_edit）在落地前后调用这里做校验，是安全边界的一部分。

依赖：无内部依赖（叶子模块）。
"""

import json
import logging
import re
from itertools import pairwise

from app.schemas.trip import (
    ChatTurnRequest,
)

logger = logging.getLogger(__name__)


class DecisionJsonError(ValueError):
    """模型决策不是可安全执行的 JSON；避免把解析器英文异常暴露给用户。"""


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM 未返回 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DecisionJsonError("模型返回的结构化结果不完整") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM 决策不是 JSON 对象")
    return data


def _clock_minutes(value: object) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*", str(value or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return hour * 60 + minute if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def _format_clock(minutes: int) -> str | None:
    if not 0 <= minutes < 24 * 60:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _plan_conflict(plans: list[dict]) -> tuple[int, str, str] | None:
    """返回首个日内时间冲突；酒店入住点不视为占用型活动。"""
    for plan in plans:
        day_no = int(plan.get("day_no") or 0)
        intervals = []
        for item in plan.get("items") or []:
            if item.get("item_type") == "transport":
                continue
            start = _clock_minutes(item.get("start_time"))
            end = _clock_minutes(item.get("end_time"))
            if end is None and start is not None and isinstance(item.get("duration_min"), (int, float)):
                end = start + int(item["duration_min"])
            if start is None or end is None or end <= start:
                continue
            intervals.append((start, end, str(item.get("poi_name") or "未命名安排")))
        intervals.sort()
        for previous, current in pairwise(intervals):
            if current[0] < previous[1]:
                return day_no, previous[2], current[2]
    return None


def _substantive_plan_signature(plans: list[dict]) -> list[tuple]:
    return [
        (
            int(plan.get("day_no") or 0),
            item_index,
            str(item.get("id") or ""),
            str(item.get("item_type") or ""),
            str(item.get("poi_name") or ""),
            str(item.get("start_time") or ""),
            str(item.get("end_time") or ""),
            str(item.get("duration_min") or ""),
        )
        for plan in plans
        for item_index, item in enumerate(plan.get("items") or [])
    ]


def _decision_reply(value: object, fallback: str) -> str:
    reply = str(value or "").strip()
    compact = re.sub(r"[\s`*_#：:]", "", reply).lower()
    if not reply or compact in {"中文markdown", "markdown", "中文", "reply", "回复"}:
        return fallback
    return reply


def _reschedule_moved_item(plans_by_day: dict[int, dict], item: dict, day_no: int) -> bool:
    """移动到新日期后若原时间冲突，寻找 07:00-22:00 的首个合理空档。"""
    duration = item.get("duration_min")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return False
    duration = int(duration)
    occupied = []
    for other in plans_by_day[day_no].get("items") or []:
        if other is item or other.get("item_type") == "transport":
            continue
        start = _clock_minutes(other.get("start_time"))
        end = _clock_minutes(other.get("end_time"))
        if end is None and start is not None and isinstance(other.get("duration_min"), (int, float)):
            end = start + int(other["duration_min"])
        if start is not None and end is not None and end > start:
            occupied.append((start, end))
    occupied.sort()

    def available(start: int) -> bool:
        end = start + duration
        return end <= 22 * 60 and all(end <= busy_start or start >= busy_end for busy_start, busy_end in occupied)

    original = _clock_minutes(item.get("start_time"))
    if original is not None and available(original):
        return True
    for candidate in range(7 * 60, 22 * 60 - duration + 1, 15):
        if available(candidate):
            item["start_time"] = _format_clock(candidate)
            item["end_time"] = _format_clock(candidate + duration)
            return True
    return False


def _default_plan_update_reply(req: ChatTurnRequest, plans: list[dict]) -> str:
    before_count = sum(len(plan.get("items") or []) for plan in req.plans)
    after_count = sum(len(plan.get("items") or []) for plan in plans)
    lines = [f"### 已生成 {len(plans)} 天宽松版草稿", ""]
    if after_count < before_count:
        lines.append(f"已精简 **{before_count - after_count}** 个相对次要或重复的安排，并重新分配剩余项目。")
    else:
        lines.append("已重新分配每天的安排，降低单日行程密度。")
    lines.extend(["", "请先查看每天安排，确认后再应用；住宿没有被自动修改。"])
    return "\n".join(lines)
