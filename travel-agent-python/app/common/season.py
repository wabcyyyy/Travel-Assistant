"""酒店季节定价：与后端 SeasonPrice.java 保持完全一致的规则。"""

from datetime import date

PEAK_FACTOR = 1.8      # 节假日窗口（春节前夜~初八、五一、国庆）
SUMMER_FACTOR = 1.5    # 暑期（7-8月）
OFF_FACTOR = 0.85      # 淡季（12、1、2 月，节假日窗口优先）
NORMAL_FACTOR = 1.0

_HOLIDAY_WINDOWS = [
    ((1, 24), (2, 8)),    # 春节前后（近似）
    ((4, 30), (5, 5)),    # 五一
    ((9, 30), (10, 7)),   # 国庆
]
_SUMMER_MONTHS = {7, 8}
_OFF_MONTHS = {12, 1, 2}


def _in_holiday(d: date) -> bool:
    for (m1, d1), (m2, d2) in _HOLIDAY_WINDOWS:
        start = date(d.year, m1, d1)
        end = date(d.year, m2, d2)
        if start <= d <= end:
            return True
    return False


def season_factor(d: date | None) -> float:
    """返回价格系数；d 为空时按当天计。"""
    if d is None:
        d = date.today()
    if _in_holiday(d):
        return PEAK_FACTOR
    if d.month in _SUMMER_MONTHS:
        return SUMMER_FACTOR
    if d.month in _OFF_MONTHS:
        return OFF_FACTOR
    return NORMAL_FACTOR


def season_label(d: date | None) -> str:
    if d is None:
        d = date.today()
    if _in_holiday(d):
        return "节假日旺季"
    if d.month in _SUMMER_MONTHS:
        return "暑期旺季"
    if d.month in _OFF_MONTHS:
        return "淡季"
    return "平季"
