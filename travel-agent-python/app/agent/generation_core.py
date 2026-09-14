"""生成链路共享内核：产品口径与确定性 helper 的唯一真相源。

架构（已合并为一张图）：

| 模块 | 角色 |
|------|------|
| ``trip_graph`` | **唯一** LangGraph 编排图；``mode=day`` / ``mode=trip`` 分流 |
| ``day_stream`` | 单次生成「事实层」：开放模式 Prompt、坐标/价格落地、ReferencePool |
| ``workflow`` | 整段业务节点实现 + ``run_generate`` 门面 |
| ``day_workflow`` | 逐日门面 + ``_generate_day_once`` 兼容再导出 |
| ``generation_core`` | 产品口径（N-1 晚/草案/重试常量/摊铺） |

改动产品规则只改本模块；改编排拓扑只改 ``trip_graph``。
"""

from __future__ import annotations

import copy
import re
from math import asin, cos, radians, sin, sqrt
from typing import Any

# 单日/兼容路径的校验修复次数
MAX_FIX_ATTEMPTS = 2
# 开放研究失败总尝试（含首次）：失败 → 重试一次 → 待研究草案
MAX_GENERATION_ATTEMPTS = 2
# 逐日 LangGraph 单日修复上限（与 MAX_FIX_ATTEMPTS 对齐，避免两套常量漂移）
MAX_DAY_ATTEMPTS = MAX_FIX_ATTEMPTS
# Supervisor 证据缺口补查次数
MAX_REFILLS = 1

DRAFT_NOTE_SUFFIX = "待研究"

# TripItem 合法类型（与 schemas.trip、Java 落库契约一致）
ALLOWED_ITEM_TYPES = frozenset({"attraction", "food", "hotel", "transport"})

# LLM 开放生成常吐出的扩展类型 → 归一到契约类型，避免 Pydantic 校验 500
_ITEM_TYPE_ALIASES = {
    "souvenir": "attraction",
    "activity": "attraction",
    "experience": "attraction",
    "shopping": "attraction",
    "shop": "attraction",
    "market": "attraction",
    "viewpoint": "attraction",
    "scenic": "attraction",
    "landmark": "attraction",
    "museum": "attraction",
    "park": "attraction",
    "temple": "attraction",
    "restaurant": "food",
    "meal": "food",
    "cafe": "food",
    "bar": "food",
    "snack": "food",
    "lodging": "hotel",
    "hostel": "hotel",
    "stay": "hotel",
    "traffic": "transport",
    "metro": "transport",
    "taxi": "transport",
    "walk": "transport",
}


def normalize_item_type(raw: Any) -> str:
    """把 LLM/客户端 item_type 归一到合法值；未知类型回退 attraction。"""
    t = str(raw or "").strip().lower()
    if t in ALLOWED_ITEM_TYPES:
        return t
    return _ITEM_TYPE_ALIASES.get(t, "attraction")


def sanitize_itinerary_items(items: list[Any] | None) -> list[dict]:
    """过滤脏项并归一 item_type，供 format_output / day_stream 构造 TripItem 前调用。"""
    out: list[dict] = []
    for item in filter_dirty_items(items):
        row = dict(item)
        row["item_type"] = normalize_item_type(row.get("item_type"))
        out.append(row)
    return out


def stay_nights(days: int | None) -> int:
    """产品定稿：N 天行程住 N-1 晚；最后一天不安排入住。"""
    try:
        d = int(days or 1)
    except (TypeError, ValueError):
        d = 1
    return max(d - 1, 0)


def day_needs_hotel(day_no: int, days: int | None, *, override: bool | None = None) -> bool:
    """某一天是否应安排酒店。``override`` 为客户端/上游显式 needs_hotel 时优先生效。"""
    if override is not None:
        return bool(override)
    nights = stay_nights(days)
    try:
        n = int(day_no)
    except (TypeError, ValueError):
        return False
    return 1 <= n <= nights


def hotel_prompt_clause(needs_hotel: bool, days: int | None) -> str:
    """多日/单日酒店 Prompt 条款（与 stay_nights 口径一致）。"""
    d = int(days or 1)
    if needs_hotel and d > 1:
        last_stay = max(d - 1, 0)
        return (
            f"第 1 至第 {last_stay} 天每天都要有同一家酒店的入住项"
            "（全程沿用同一家，默认不换店，仅前往远距离区域转点时可换），最后一天不安排入住"
        )
    if needs_hotel:
        return "安排 1 家酒店"
    return "按需安排酒店"


def day_hotel_clause(needs_hotel: bool) -> str:
    """单日 Prompt 中的酒店短句。"""
    return "安排 1 家酒店；" if needs_hotel else "今日无需安排酒店；"


def count_hotel_nights_in_budget(plan_day_no: int, days: int | None, item_type: str) -> bool:
    """预算/落库是否计入该酒店项：末日酒店在多日行程中不计（N-1 晚口径）。"""
    if item_type != "hotel":
        return False
    d = int(days or 1)
    n = int(plan_day_no or 0)
    if d > 1 and n >= d:
        return False
    return True


def spread_hotels(plans: list[dict], nights: int | None = None, days: int | None = None) -> int:
    """全程同一家酒店：把首个酒店项复制到仍缺入住的晚次。

    不改内容来源（仍是 LLM 选的那家店），只做确定性摊铺。
    """
    if nights is None:
        nights = stay_nights(days if days is not None else _max_day_no(plans))
    if nights <= 0 or not plans:
        return 0
    source: dict | None = None
    for plan in plans:
        for item in plan.get("items") or []:
            if item.get("item_type") == "hotel":
                source = item
                break
        if source:
            break
    if not source:
        return 0
    added = 0
    for plan in plans:
        day_no = int(plan.get("day_no") or 0)
        if day_no < 1 or day_no > nights:
            continue
        items = plan.setdefault("items", [])
        if any(it.get("item_type") == "hotel" for it in items):
            continue
        clone = copy.deepcopy(source)
        clone["sort_no"] = len(items)
        items.append(clone)
        added += 1
    return added


def meal_slot_of(start_time: str | None, end_time: str | None = None) -> str | None:
    """按开始时间粗分餐次：lunch(10:30-14:30) / dinner(17:00-21:30) / breakfast(05:00-10:30)。"""
    raw = str(start_time or "").strip()
    if not raw or ":" not in raw:
        return None
    try:
        hour, minute = raw.split(":", 1)
        mins = int(hour) * 60 + int(minute)
    except ValueError:
        return None
    if 5 * 60 <= mins < 10 * 60 + 30:
        return "breakfast"
    if 10 * 60 + 30 <= mins < 14 * 60 + 30:
        return "lunch"
    if 17 * 60 <= mins <= 21 * 60 + 30:
        return "dinner"
    return "other"


def has_double_lunch(foods: list[dict]) -> bool:
    """当日是否出现两顿午餐（两条餐饮都落在午间窗口）。"""
    lunches = [f for f in foods or [] if meal_slot_of(f.get("start_time")) == "lunch"]
    return len(lunches) >= 2


def estimate_plans_total(plans: list[dict], persons: int, days: int | None,
                         consumption: dict | None = None,
                         rooms: int | None = None) -> dict:
    """按与 Java BudgetEngine 对齐的口径估算行程总价（用于超支硬约束）。

    门票/餐饮：单价 × 人数；酒店：单价 × 房间数（默认 2 人间）；交通：城市日均。
    """
    p = max(int(persons or 1), 1)
    d = max(int(days or len(plans or []) or 1), 1)
    room_n = rooms if rooms is not None else max((p + 1) // 2, 1)
    ticket = 0.0
    meal = 0.0
    hotel = 0.0
    for plan in plans or []:
        day_no = int(plan.get("day_no") or 0)
        for item in plan.get("items") or []:
            try:
                cost = float(item.get("cost") or 0)
            except (TypeError, ValueError):
                cost = 0.0
            t = str(item.get("item_type") or "")
            if t == "attraction":
                ticket += cost
            elif t == "food":
                meal += cost
            elif t == "hotel" and count_hotel_nights_in_budget(day_no, days or len(plans or []), "hotel"):
                hotel += cost
    transport = float((consumption or {}).get("transport_price", 35.0) or 35.0)
    total = round(ticket * p + meal * p + hotel * room_n + transport * d * p, 2)
    return {
        "门票": round(ticket * p, 2),
        "餐饮": round(meal * p, 2),
        "酒店": round(hotel * room_n, 2),
        "交通": round(transport * d * p, 2),
        "合计": total,
    }


def draft_day_plans(city: str, days: int, reason: str) -> list[dict]:
    """LLM 失败后的「待研究草案」：如实空日，绝不冒充生成结果。"""
    try:
        n = int(days)
    except (TypeError, ValueError):
        n = 1
    n = max(n, 1)
    return [
        {"day_no": day_no, "note": f"{city}第{day_no}天{DRAFT_NOTE_SUFFIX}", "items": []}
        for day_no in range(1, n + 1)
    ]


def filter_dirty_items(items: list[Any] | None) -> list[dict]:
    """过滤非 dict / 无 poi_name 的脏项，避免下游崩溃。"""
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict) and str(item.get("poi_name") or "").strip():
            out.append(item)
    return out


def _max_day_no(plans: list[dict]) -> int:
    m = 0
    for plan in plans:
        try:
            m = max(m, int(plan.get("day_no") or 0))
        except (TypeError, ValueError):
            continue
    return m or 1


# 归一化去重键：剥括号注记（"圣家堂（Sagrada Família）"→"圣家堂"）、
# 去空白与常见分隔标点、小写。模型对同一地点常输出名称变体（中英混注、
# 带括号别名），精确字符串比对会漏判跨天重复。
_BRACKET_ANNOTATION_RE = re.compile(r"[（(【\[〔].*?[）)】\]〕]", re.S)
_NAME_SEPARATOR_RE = re.compile(r"[\s·・、,，。．.\-—_]+")

_EARTH_RADIUS_M = 6371000.0


def norm_poi_key(name) -> str:
    """POI 名称归一化键：同名判定（同日/跨天去重）与 used 比对共用。"""
    s = _BRACKET_ANNOTATION_RE.sub("", str(name or ""))
    s = _NAME_SEPARATOR_RE.sub("", s)
    return s.lower().casefold()


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    """两点球面距离（米）；坐标无效返回 inf（0/0 是缺失哨兵）。"""

    def _v(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if abs(f) > 1e-6 else None

    a, b, c, d = _v(lat1), _v(lng1), _v(lat2), _v(lng2)
    if None in (a, b, c, d):
        return float("inf")
    p1, p2 = radians(a), radians(c)
    dp = radians(c - a)
    dl = radians(d - b)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(min(1.0, sqrt(h)))


class PoiSeenRegistry:
    """跨天/同日重复点位登记表：归一化同名 + 同类型近距离坐标双通道。

    名称变体（"圣家堂" vs "圣家堂大教堂"）光靠字符串归一抓不住；落地
    （引用背书/高德/Google）补上真实坐标后，同类型点位相距 <80m 即视为
    同一地点。坐标缺失时退化为纯名称判定。
    酒店不参与判重：全程同一家酒店跨天重复是摊铺语义（N-1 晚口径）。
    """

    def __init__(self, max_proximity_m: float = 80.0) -> None:
        self.max_proximity_m = max_proximity_m
        self._keys: set[str] = set()
        self._coords: list[tuple[str, float, float]] = []

    def is_duplicate(self, name, item_type, latitude=None, longitude=None) -> bool:
        if str(item_type or "") == "hotel":
            # 酒店全程同一家是摊铺语义：跨天同名合法，不参与判重
            return False
        key = norm_poi_key(name)
        if key and key in self._keys:
            return True
        dist = min(
            (haversine_m(latitude, longitude, la, ln) for _t, la, ln in self._coords),
            default=float("inf"),
        )
        return dist < self.max_proximity_m

    def register(self, name, item_type, latitude=None, longitude=None) -> None:
        if str(item_type or "") == "hotel":
            return
        key = norm_poi_key(name)
        if key:
            self._keys.add(key)
        try:
            lat, lng = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return
        if abs(lat) > 1e-6 and abs(lng) > 1e-6:
            self._coords.append((str(item_type or ""), lat, lng))


def drop_cross_day_duplicates(plans: list[dict],
                              *, max_proximity_m: float = 80.0) -> list[dict]:
    """对整组日计划做跨天重复清洗（原地修改），返回被丢弃项的遥测列表。

    用于整段一次生成的后处理：同名/同地不同名的重复只保留首次出现。
    """
    registry = PoiSeenRegistry(max_proximity_m=max_proximity_m)
    dropped: list[dict] = []
    for plan in sorted(plans, key=lambda p: int(p.get("day_no") or 0)):
        kept: list[dict] = []
        for item in plan.get("items") or []:
            name = str(item.get("poi_name") or "").strip()
            item_type = str(item.get("item_type") or "")
            if name and registry.is_duplicate(name, item_type,
                                              item.get("latitude"), item.get("longitude")):
                dropped.append({"day_no": plan.get("day_no"), "poi_name": name})
                continue
            if name:
                registry.register(name, item_type, item.get("latitude"), item.get("longitude"))
            kept.append(item)
        plan["items"] = kept
    return dropped
