"""自然语言意图与天数解析（纯正则，不调用 LLM）。

职责：
- 把用户口语里的天数变化翻译成结构化参数：减少 N 天、增加/延长 N 天、改成 N 天；
- 识别“只想浏览其他景点”这类不应触发改写的模糊请求（_is_vague_poi_browse_request）。

实现要点：
- 用一组针对性正则（_REDUCE_BY_RE / _INCREASE_BY_RE / _REDUCTION_PHRASE_RE 等）
  配合中文数字识别（_cn_number / _CHINESE_DAY_NUMBERS）解析出目标天数或增减量；
- _requested_day_count(message, current_days) 是核心入口，返回“目标天数”或 None；
- 这些解析只作为“用户意图”的辅助信号，最终由 decide 层结合模型输出共同决定，
  避免正则与模型互相打架（这也是此前“加一天”被误读成“改成 1 天”的教训）。

依赖：无内部依赖（叶子模块）；对外暴露 _requested_day_count / _is_reduction_request 等。
"""

import logging
import re

from app.schemas.trip import (
    MAX_TRIP_DAYS,
    ChatTurnRequest,
)

logger = logging.getLogger(__name__)


_CHINESE_DAY_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
}

_REDUCE_BY_RE = re.compile(r"(?:减少|缩短|压缩|减掉|去掉|缩减|砍掉)\s*([0-9]+|[一二两三四五六七八九十]+)\s*天")

_INCREASE_BY_RE = re.compile(
    r"(?:加|增加|延长|多|补|追加|添)(?:了|上|再)?[^天]{0,4}?([0-9]+|[一二两三四五六七八九十]+)?\s*天"
)

_REDUCTION_PHRASE_RE = re.compile(
    r"删除|删掉|去掉|移除|替换|换成|换掉|减少|精简|不重要|重复|宽松|轻松|别太赶|不要太赶|少一点"
)


def _cn_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return numbers.get(value)


def _parse_reduce_by_days(message: str) -> int | None:
    """解析“减少/缩短 N 天”中的 N（要减去的天数）；非此类表达返回 None。"""
    match = _REDUCE_BY_RE.search(message or "")
    if not match:
        return None
    raw = match.group(1)
    value = _cn_number(raw)
    if value is None and raw:
        # “一两/两三”这类范围表述，取首个数字作为保守减量。
        value = _cn_number(raw[0])
    return value


def _parse_increase_by_days(message: str) -> int | None:
    """解析“加/增加/延长 N 天”中的 N（要加上的天数）；非此类表达返回 None。"""
    match = _INCREASE_BY_RE.search(message or "")
    if not match:
        return None
    raw = match.group(1)
    if raw:
        value = _cn_number(raw)
        if value is None:
            value = _cn_number(raw[0])
        if value:
            return value
    return 1


def _requested_day_count(message: str, current_days: int | None = None) -> int | None:
    """提取用户明确提出的总天数；“第五天”不视为把行程改成五天。

    “减少/缩短 N 天”优先解析为“在现有天数上减去 N 天”，“加/增加/延长 N 天”解析为加上 N 天，
    二者均需传入 current_days。
    """
    reduce_by = _parse_reduce_by_days(message)
    if reduce_by is not None and current_days is not None:
        return max(1, current_days - reduce_by)
    increase_by = _parse_increase_by_days(message)
    if increase_by is not None and current_days is not None:
        # 保留超限目标，交由上层统一返回“最多 7 天”，不能静默截断成原天数。
        return current_days + increase_by
    text = re.sub(r"第\s*(?:\d{1,2}|十[一二三四]?|[一二两三四五六七八九])\s*(?:天|日)", "", message or "")
    matches = re.findall(r"(\d{1,2}|十[一二三四]?|[一二两三四五六七八九十])\s*(?:天|日游)", text)
    if not matches:
        return None
    raw = matches[-1]
    value = int(raw) if raw.isdigit() else _CHINESE_DAY_NUMBERS.get(raw)
    return value if value is not None and value >= 1 else None


def _is_reduction_request(message: str) -> bool:
    return bool(_REDUCTION_PHRASE_RE.search(message or ""))


def _reduce_target_days(req: ChatTurnRequest) -> int | None:
    """用户明确要求“减少/缩短 N 天”时返回目标天数，否则返回 None。"""
    reduce_by = _parse_reduce_by_days(req.message)
    if reduce_by:
        return max(1, req.days - reduce_by)
    return None


def _increase_target_days(req: ChatTurnRequest) -> int | None:
    """用户明确要求“加/增加/延长 N 天”时返回目标天数，否则返回 None。"""
    increase_by = _parse_increase_by_days(req.message)
    if increase_by:
        target = req.days + increase_by
        return target if target <= MAX_TRIP_DAYS else None
    return None


def _is_vague_poi_browse_request(message: str) -> bool:
    """识别只想浏览其他景点/餐饮的模糊请求，避免模型把它当成删除草稿。"""
    text = message or ""
    has_poi_object = bool(re.search(r"景点|景区|餐厅|餐饮|美食|吃什么", text))
    has_browse_word = bool(re.search(r"其他|其它|别的|还有|看看|推荐|浏览|想去看看", text))
    has_mutation = bool(
        re.search(
            r"增加|添加|加入|换成|替换|换掉|删除|删掉|去掉|移到|挪到|安排到|改成|改为|保留|取消",
            text,
        )
    )
    return has_poi_object and has_browse_word and not has_mutation
