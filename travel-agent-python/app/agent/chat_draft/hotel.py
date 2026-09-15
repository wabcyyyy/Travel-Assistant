"""酒店子系统：意图识别、档次解析、候选生成与签名校验。

职责：
- 识别“换酒店/升级/降价/指定品牌”等住宿类意图（_is_hotel_request / _understand_hotel_intent）；
- 把口语映射到档次与入住晚次（_hotel_tier / _with_stay_scope / _resolve_hotel_names）；
- 生成可展示的酒店/房型候选卡片（_hotel_options / _explain_hotel_options）；
- 用 _hotel_signature 校验草稿中的酒店是否被偷偷改动。

实现要点：
- 酒店是高风险操作，必须走独立确认流程（hotel_proposal），绝不直接进 plan_document；
- 品牌别名（_HOTEL_BRAND_ALIASES）、档次关键词（_TIER_KEYWORDS）等做口语归一；
- 本模块相对独立，是 chat_draft 中体量最大的部分，单独成文件便于维护。

依赖：document（读取行程投影）；被 decide 层在酒店分支调用。HotelIntent 为 @dataclass。
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from math import ceil

from app.agent import tools
from app.agent.memory import recent_turns
from app.common.llm_client import get_llm_client
from app.common.season import season_factor, season_label
from app.schemas.trip import (
    ChatTurnRequest,
    ChatTurnResponse,
    HotelOption,
    HotelRoomOption,
)

from .document import _trip_plan_document
from .intent import _cn_number

logger = logging.getLogger(__name__)

_TIER_RANK = {"经济型": 1, "舒适型": 2, "高档型": 3, "豪华型": 4, "奢华型": 5}

_TIER_KEYWORDS = {
    "经济型": ("经济", "连锁"),
    "舒适型": ("舒适", "中端", "亚朵", "全季"),
    "高档型": ("高端", "高档", "精品", "五星"),
    "豪华型": ("豪华", "五星", "国宾", "地标"),
    "奢华型": ("奢华", "国宾", "传奇", "地标", "私享"),
}

_TIER_ALIASES = {
    "经济": "经济型",
    "舒适": "舒适型",
    "中端": "舒适型",
    "高端": "高档型",
    "高档": "高档型",
    "豪华": "豪华型",
    "五星": "豪华型",
    "奢华": "奢华型",
    "顶级": "奢华型",
}

_INTENT_LABELS = {
    "cheaper": "下调一档",
    "same": "更换同档酒店",
    "better": "升级一档",
    "best": "查看最高档酒店",
    "specific": "查看指定档次",
}

_HOTEL_BRAND_ALIASES = (
    "安缦",
    "四季",
    "柏悦",
    "君悦",
    "亚朵",
    "汉庭",
    "全季",
    "桔子",
    "欢朋",
    "温德姆",
    "康莱德",
    "香格里拉",
    "索菲特",
    "紫萱",
    "西子宾馆",
    "黄龙饭店",
)


@dataclass
class HotelIntent:
    action: str
    target_tier: str
    base_tier: str
    requested_nights: int = 0
    requested_day_nos: tuple[int, ...] = ()
    requested_hotel_names: tuple[str, ...] = ()
    invalid_scope: bool = False


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _tiers_in_text(value: str | None) -> list[str]:
    text = value or ""
    found = {tier for tier in _TIER_RANK if tier in text}
    for alias, tier in _TIER_ALIASES.items():
        if alias in text:
            found.add(tier)
    return sorted(found, key=lambda tier: _TIER_RANK[tier])


def _preference_tier(value: str | None) -> str:
    tiers = _tiers_in_text(value)
    return tiers[-1] if tiers else "舒适型"


def _hotel_tier(hotel: dict) -> str:
    text = (hotel.get("name") or "") + (hotel.get("description") or "") + (hotel.get("tags") or "")
    explicit = [tier for tier in _TIER_RANK if tier in text]
    if explicit:
        return max(explicit, key=lambda tier: _TIER_RANK[tier])
    matched = [tier for tier, keywords in _TIER_KEYWORDS.items() if any(keyword in text for keyword in keywords)]
    return max(matched, key=lambda tier: _TIER_RANK[tier], default="舒适型")


def _mentioned_hotel_names(message: str, hotels: list[dict]) -> tuple[str, ...]:
    normalized = message.replace("安曼", "安缦")
    matched = []
    for hotel in hotels:
        name = str(hotel.get("name") or "")
        city = str(hotel.get("city") or "")
        short_name = name.removeprefix(city) if city else name
        alias_hit = any(alias in normalized and alias in name for alias in _HOTEL_BRAND_ALIASES)
        if name and (name in normalized or (len(short_name) >= 4 and short_name in normalized) or alias_hit):
            matched.append(name)
    return tuple(matched)


def _is_hotel_request(req: ChatTurnRequest, hotels: list[dict] | None = None) -> bool:
    normalized_message = req.message.replace("安曼", "安缦")
    # 当前轮明确谈景点/餐饮/行程时，不能被前几轮酒店上下文中的“其他、便宜”等词劫持。
    if re.search(r"景点|景区|餐厅|餐饮|美食|行程|安排|路线|路线", normalized_message) and not re.search(
        r"酒店|住宿|宾馆|客栈|房型|入住|住一晚|住几晚", normalized_message
    ):
        return False
    if _mentioned_hotel_names(normalized_message, hotels or []):
        return True
    if re.search(
        r"酒店|住宿|宾馆|客栈|民宿|旅馆|住处|住的地方|下榻|过夜|换个住|换住宿|"
        r"升级|降一档|档次低|低一点|低些|便宜点|便宜一点|便宜些|省钱|预算友好|"
        r"更好|好一点|好些|贵一点|贵些|高级些|档次高|"
        r"高端|高档|豪华|奢华|五星|顶级|顶配|最屌|最高级|最牛",
        req.message,
    ):
        return True
    recent = " ".join(str(item.get("content") or "") for item in (req.history or [])[-2:])
    return bool(
        re.search(r"酒店|住宿|宾馆", recent)
        and re.search(r"其他|其它|别的|还有|换一个|换一家|便宜|贵点|好点|更好|同档|同级", req.message)
    )


def _current_hotel_names(req: ChatTurnRequest) -> set[str]:
    return {
        str(item.get("poi_name"))
        for plan in req.plans
        for item in (plan.get("items") or [])
        if item.get("item_type") == "hotel" and item.get("poi_name")
    }


def _available_hotel_day_nos(req: ChatTurnRequest) -> list[int]:
    return sorted(
        {
            int(plan.get("day_no"))
            for plan in req.plans
            if isinstance(plan.get("day_no"), int)
            and any(item.get("item_type") == "hotel" for item in (plan.get("items") or []))
        }
    )


def _has_explicit_stay_scope(message: str) -> bool:
    return bool(
        re.search(
            r"最后(?:一)?(?:天|晚)|末(?:天|晚)|第\s*[0-9一二两三四五六七八九十]+\s*(?:天|晚)|"
            r"[0-9一二两三四五六七八九十]+\s*晚",
            message or "",
        )
    )


def _with_stay_scope(intent: HotelIntent, req: ChatTurnRequest, hotels: list[dict]) -> HotelIntent:
    available = _available_hotel_day_nos(req)
    valid_day_nos = set(range(1, req.days + 1))
    scope_mentioned = _has_explicit_stay_scope(req.message)
    # 入住范围只认用户本轮原话：未提晚次时默认当前全部住宿晚次；明确说
    # “住一晚”但没说哪晚时留空供前端选择；“第 N 晚/最后一晚”则精确选中。
    day_nos = [] if scope_mentioned else list(available)
    invalid_scope = False
    if re.search(r"最后(?:一)?天|末天", req.message):
        day_nos.append(req.days)
    elif re.search(r"最后(?:一)?晚|末晚", req.message):
        day_nos.append(available[-1] if available else req.days)
    day_values = re.findall(r"第\s*([0-9一二两三四五六七八九十]+)\s*(?:天|晚)", req.message)
    for value in day_values:
        day_no = _cn_number(value)
        if day_no in valid_day_nos and day_no not in day_nos:
            day_nos.append(day_no)
        elif day_no is not None and day_no not in valid_day_nos:
            invalid_scope = True
    night_match = re.search(r"([0-9一二两三四五六七八九十]+)\s*晚", req.message)
    if night_match and re.search(r"第\s*$", req.message[: night_match.start()]):
        night_match = None
    requested_nights = (
        _cn_number(night_match.group(1))
        if night_match
        else (len(available) if not scope_mentioned and available else intent.requested_nights)
    )
    if requested_nights and requested_nights > len(valid_day_nos):
        invalid_scope = True
    if day_nos:
        requested_nights = len(day_nos)
    max_scope_nights = req.days if scope_mentioned else (len(available) or req.days)
    requested_nights = max(1, min(requested_nights or len(available) or req.days, max_scope_nights))

    named = _mentioned_hotel_names(req.message, hotels)
    if named:
        named_tiers = [_hotel_tier(hotel) for hotel in hotels if hotel.get("name") in named]
        target = max(named_tiers, key=lambda tier: _TIER_RANK[tier])
        intent = HotelIntent(action="specific", target_tier=target, base_tier=intent.base_tier)
    return HotelIntent(
        action=intent.action,
        target_tier=intent.target_tier,
        base_tier=intent.base_tier,
        requested_nights=requested_nights,
        requested_day_nos=tuple(day_nos),
        requested_hotel_names=named,
        invalid_scope=invalid_scope,
    )


def _current_hotel_tier(req: ChatTurnRequest, hotels: list[dict]) -> str:
    current_names = _current_hotel_names(req)
    known = [_hotel_tier(hotel) for hotel in hotels if hotel.get("name") in current_names]
    if known:
        return max(known, key=lambda tier: _TIER_RANK[tier])
    return _preference_tier(req.hotel_tier)


def _previous_proposed_hotel_tier(req: ChatTurnRequest) -> str | None:
    for turn in reversed(req.history or []):
        if turn.get("role") not in {"ai", "assistant"}:
            continue
        content = str(turn.get("content") or "").replace("*", "")
        match = re.search(
            r"本次提供\s*\d+\s*家\s*(经济型|舒适型|高档型|豪华型|奢华型)酒店",
            content,
        )
        if match:
            return match.group(1)
    return None


def _hotel_comparison_base_tier(req: ChatTurnRequest, hotels: list[dict]) -> str:
    if re.search(r"再|继续|还要更|还想更", req.message):
        return _previous_proposed_hotel_tier(req) or _current_hotel_tier(req, hotels)
    return _current_hotel_tier(req, hotels)


def _fallback_hotel_intent(message: str, base_tier: str) -> HotelIntent:
    if re.search(r"最屌|最好|最贵|最高级|最高档|顶级|顶配|天花板|最牛", message):
        action = "best"
    elif re.search(r"便宜|省钱|实惠|预算友好|降一档|低一档|档次低|低一点|低些|降低|少花", message):
        action = "cheaper"
    elif re.search(r"其他|其它|别的|换一家|换一个|换(?:个|一家)?酒店|换住宿|换住处|同档|同级|类似", message):
        action = "same"
    elif re.search(r"更好|好一点|好点|好些|升级|升一档|高一档|贵一点|贵些|高级一点|高级些|档次高", message):
        action = "better"
    else:
        explicit = _tiers_in_text(message)
        action = "specific" if explicit else "same"

    base_rank = _TIER_RANK[base_tier]
    explicit = _tiers_in_text(message)
    if action == "best":
        target = "奢华型"
    elif action == "cheaper":
        target = next(tier for tier, rank in _TIER_RANK.items() if rank == max(base_rank - 1, 1))
    elif action == "better":
        target = next(tier for tier, rank in _TIER_RANK.items() if rank == min(base_rank + 1, 5))
    elif action == "specific" and explicit:
        target = explicit[-1]
    else:
        target = base_tier
    return HotelIntent(action=action, target_tier=target, base_tier=base_tier)


def _has_explicit_hotel_comparison(message: str) -> bool:
    return bool(
        re.search(
            r"便宜|省钱|实惠|预算友好|降一档|低一档|档次低|低一点|低些|降低|少花|"
            r"其他|其它|别的|换一家|换一个|换(?:个|一家)?酒店|换住宿|换住处|"
            r"同档|同级|类似|更好|好一点|好点|好些|升级|升一档|高一档|贵一点|贵些|高级一点|高级些|档次高|"
            r"最屌|最好|最贵|最高级|最高档|顶级|顶配|天花板|最牛|安缦|安曼|四季|希尔顿|"
            r"香格里拉|亚朵|汉庭|如家",
            message,
        )
    )


def _normalized_hotel_intent(action: str, target: str, base_tier: str) -> HotelIntent:
    """不信任模型计算档次，只采纳语义动作；档次移动由代码确定，避免跨错档。"""
    base_rank = _TIER_RANK[base_tier]
    if action == "cheaper":
        target_rank = max(base_rank - 1, 1)
    elif action == "same":
        target_rank = base_rank
    elif action == "better":
        target_rank = min(base_rank + 1, 5)
    elif action == "best":
        target_rank = 5
    else:
        target_rank = _TIER_RANK.get(target, base_rank)
    normalized = next(tier for tier, rank in _TIER_RANK.items() if rank == target_rank)
    return HotelIntent(action=action, target_tier=normalized, base_tier=base_tier)


def _understand_hotel_intent(req: ChatTurnRequest, hotels: list[dict]) -> HotelIntent:
    """先理解相对当前酒店的换房意图，再把它收敛为一个明确目标档次。"""
    base_tier = _hotel_comparison_base_tier(req, hotels)
    fallback = _fallback_hotel_intent(req.message, base_tier)
    history = recent_turns(req.history, turns=4, max_chars=500)
    try:
        raw = (
            get_llm_client()
            .complete(
                "请识别用户更换酒店的真实意图，并只输出JSON。\n"
                "action只能是 cheaper、same、better、best、specific 之一："
                "便宜一点是cheaper；看看其他/换一家是same；更好一点/升级是better；"
                "最好/最顶级/最屌是best；明确说某档次是specific。\n"
                "档次从低到高：经济型、舒适型、高档型、豪华型、奢华型。"
                "cheaper和better都只移动一档，same保持当前档，best为奢华型。"
                "如果用户用“再”承接上文，可结合最近对话判断最终目标。\n"
                f"当前酒店档次：{base_tier}；初始住宿偏好：{req.hotel_tier or '未指定'}；"
                f"最近对话：{json.dumps(history, ensure_ascii=False)}；用户原话：{req.message}\n"
                '格式：{"action":"better","target_tier":"豪华型"}',
                system_prompt="你是酒店换房意图分类器。理解口语和相对比较，不推荐酒店，不输出解释。",
                temperature=0.0,
            )
            .strip()
        )
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        action = str(data.get("action") or "")
        target = str(data.get("target_tier") or "")
        if action in _INTENT_LABELS and target in _TIER_RANK:
            expected = _fallback_hotel_intent(req.message, base_tier)
            # 明确比较词优先服从确定性规则，避免模型把“看看其他酒店”错误继承成
            # 上一轮的“便宜一点”，或把“最好的”弱化为普通升级。
            if _has_explicit_hotel_comparison(req.message):
                return _with_stay_scope(expected, req, hotels)
            return _with_stay_scope(_normalized_hotel_intent(action, target, base_tier), req, hotels)
    except Exception as exc:
        logger.warning("hotel intent classification failed: %s", exc)
    return _with_stay_scope(fallback, req, hotels)


def _hotel_options(req: ChatTurnRequest, hotels: list[dict], intent: HotelIntent) -> list[HotelOption]:
    if not hotels:
        return []
    current_names = _current_hotel_names(req)
    current_costs = [
        float(item.get("cost"))
        for plan in req.plans
        for item in (plan.get("items") or [])
        if item.get("item_type") == "hotel" and isinstance(item.get("cost"), (int, float))
    ]
    existing_hotel_day_nos = _available_hotel_day_nos(req)
    if intent.requested_day_nos:
        available_day_nos = list(dict.fromkeys(existing_hotel_day_nos + list(intent.requested_day_nos)))
    elif _has_explicit_stay_scope(req.message):
        available_day_nos = list(range(1, req.days + 1))
    else:
        available_day_nos = existing_hotel_day_nos
    rooms = ceil(req.persons / 2)
    start_date = _parse_date(req.start_date)
    factor = season_factor(start_date)
    label = season_label(start_date)
    current_total = req.current_hotel_total
    if current_total is None and current_costs:
        current_total = sum(current_costs) * rooms
    budget_capacity = None
    if req.budget is not None:
        non_hotel_total = max((req.current_total or 0) - (req.current_hotel_total or 0), 0)
        budget_capacity = max(req.budget - non_hotel_total, 0)
    current_cost_by_day = {
        int(plan.get("day_no")): sum(
            float(item.get("cost"))
            for item in (plan.get("items") or [])
            if item.get("item_type") == "hotel" and isinstance(item.get("cost"), (int, float))
        )
        * rooms
        for plan in req.plans
        if isinstance(plan.get("day_no"), int)
    }
    if intent.requested_day_nos:
        current_scope_total = sum(current_cost_by_day.get(day_no, 0) for day_no in intent.requested_day_nos)
    elif current_total is not None and available_day_nos:
        current_scope_total = current_total / len(available_day_nos) * intent.requested_nights
    else:
        current_scope_total = (
            sum(current_cost_by_day.values()) / max(len(available_day_nos), 1) * intent.requested_nights
        )

    hotel_ids = [int(hotel["id"]) for hotel in hotels if hotel.get("id") is not None]
    room_rows = tools.search_hotel_room_types(hotel_ids)
    rooms_by_hotel: dict[int, list[dict]] = {}
    for room in room_rows:
        rooms_by_hotel.setdefault(int(room["poi_id"]), []).append(room)
    priced_day_nos = list(intent.requested_day_nos) or available_day_nos[: intent.requested_nights]
    # 泛化“换个酒店”优先保持当前档次；若该档次没有除当前酒店外的可报价候选，
    # 自动退到最近档次，避免只返回一段没有卡片的空话。
    non_current_tiers = set()
    for hotel in hotels:
        try:
            has_price = float(hotel.get("ticket_price") or 0) > 0
        except (TypeError, ValueError):
            has_price = False
        if (
            has_price
            and hotel.get("name") not in current_names
            and hotel.get("name") not in intent.requested_hotel_names
        ):
            non_current_tiers.add(_hotel_tier(hotel))
    allowed_tiers = {intent.target_tier}
    if not intent.requested_hotel_names and intent.target_tier not in non_current_tiers:
        target_rank = _TIER_RANK[intent.target_tier]
        nearest = sorted(non_current_tiers, key=lambda tier: abs(_TIER_RANK[tier] - target_rank))
        if nearest:
            allowed_tiers.add(nearest[0])
    candidates = []
    for hotel in hotels:
        base = hotel.get("ticket_price")
        try:
            base_price = float(base)
        except (TypeError, ValueError):
            continue
        if base_price <= 0:
            continue
        tier = _hotel_tier(hotel)
        if tier not in allowed_tiers:
            continue
        if hotel.get("name") in current_names and not intent.requested_hotel_names:
            continue
        if intent.requested_hotel_names and hotel.get("name") not in intent.requested_hotel_names:
            continue
        hotel_room_rows = rooms_by_hotel.get(int(hotel.get("id") or 0)) or [
            {
                "id": f"base-{hotel.get('id')}",
                "room_name": "基础房型",
                "base_price": base_price,
                "capacity": 2,
                "bed_type": None,
                "breakfast": None,
                "description": "知识库酒店基础房型参考价",
                "is_default": 1,
            }
        ]
        room_options: list[HotelRoomOption] = []
        for room in hotel_room_rows:
            room_base = float(room.get("base_price") or base_price)
            capacity = max(int(room.get("capacity") or 2), 1)
            room_count = ceil(req.persons / capacity)
            nightly_breakdown = []
            for day_no in priced_day_nos:
                stay_date = start_date + timedelta(days=day_no - 1) if start_date else None
                day_factor = season_factor(stay_date)
                nightly_breakdown.append(
                    {
                        "day_no": day_no,
                        "stay_date": stay_date.isoformat() if stay_date else None,
                        "season_label": season_label(stay_date),
                        "season_factor": day_factor,
                        "nightly_price": round(room_base * day_factor, 2),
                    }
                )
            room_total = round(sum(row["nightly_price"] for row in nightly_breakdown) * room_count, 2)
            projected = round((current_total or 0) - current_scope_total + room_total, 2)
            room_options.append(
                HotelRoomOption(
                    **{
                        "id": str(room.get("id")),
                        "room_name": room.get("room_name") or "基础房型",
                        "base_price": round(room_base, 2),
                        "nightly_price": nightly_breakdown[0]["nightly_price"]
                        if nightly_breakdown
                        else round(room_base * factor, 2),
                        "nights": intent.requested_nights,
                        "rooms": room_count,
                        "total_price": room_total,
                        "price_delta": round(room_total - current_scope_total, 2),
                        "projected_hotel_total": projected,
                        "within_budget": budget_capacity is None or projected <= budget_capacity,
                        "budget_overage": round(max(projected - budget_capacity, 0), 2)
                        if budget_capacity is not None
                        else 0,
                        "capacity": capacity,
                        "bed_type": room.get("bed_type"),
                        "breakfast": room.get("breakfast"),
                        "description": room.get("description"),
                        "is_default": bool(room.get("is_default")),
                        "nightly_breakdown": nightly_breakdown,
                    }
                )
            )
        room_options.sort(key=lambda room: (not room.is_default, room.base_price))
        selected_room = room_options[0]
        candidates.append(
            HotelOption(
                **{
                    "id": str(hotel.get("id") or hotel.get("name")),
                    "hotel_name": hotel.get("name"),
                    "tier": tier,
                    "address": hotel.get("address"),
                    "rating": hotel.get("rating"),
                    "base_price": selected_room.base_price,
                    "season_factor": factor,
                    "season_label": label,
                    "nightly_price": selected_room.nightly_price,
                    "nights": intent.requested_nights,
                    "rooms": selected_room.rooms,
                    "total_price": selected_room.total_price,
                    "price_delta": selected_room.price_delta,
                    "within_budget": selected_room.within_budget,
                    "budget_capacity": round(budget_capacity, 2) if budget_capacity is not None else None,
                    "budget_overage": selected_room.budget_overage,
                    "is_current": False,
                    "reason": hotel.get("description") or "来自城市酒店知识库",
                    "requested_nights": intent.requested_nights,
                    "requested_day_nos": list(intent.requested_day_nos),
                    "available_day_nos": available_day_nos,
                    "room_types": room_options,
                }
            )
        )
    candidates.sort(
        key=lambda item: (
            item.hotel_name not in intent.requested_hotel_names if intent.requested_hotel_names else False,
            not item.within_budget,
            -float(item.rating or 0),
            item.total_price if intent.action == "cheaper" else -item.total_price,
        )
    )
    return candidates[:3]


def _explain_hotel_options(
    req: ChatTurnRequest,
    options: list[HotelOption],
    intent: HotelIntent,
) -> str:
    intent_text = _INTENT_LABELS[intent.action]
    available_nights = len(options[0].available_day_nos) if options else req.days
    if intent.requested_day_nos:
        chosen_nights = "、".join(f"第{day_no}晚" for day_no in intent.requested_day_nos)
        next_step = f"入住晚次已确定为 **{chosen_nights}**，请选择酒店和房型。"
    elif intent.requested_nights >= available_nights:
        next_step = f"本次默认覆盖 **全部 {available_nights} 晚**，请选择酒店和房型。"
    else:
        next_step = f"请选择酒店、房型和 {intent.requested_nights} 个具体入住晚次。"
    if intent.requested_hotel_names:
        requested_hotels = "、".join(intent.requested_hotel_names)
        if intent.requested_day_nos:
            next_step = f"酒店已确定为 **{requested_hotels}**，入住晚次为 **{chosen_nights}**，请选择具体房型。"
        elif intent.requested_nights >= available_nights:
            next_step = f"酒店已确定为 **{requested_hotels}**，默认覆盖全部 {available_nights} 晚，请选择具体房型。"
        else:
            next_step = f"酒店已确定为 **{requested_hotels}**，请选择具体房型和 {intent.requested_nights} 个入住晚次。"

    def money(value: float | None) -> str:
        if value is None:
            return "未设置"
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}".rstrip("0").rstrip(".")

    lines = [
        "### 我理解你的需求",
        "",
        f"你希望以当前的 **{intent.base_tier}** 酒店为基准{intent_text}，"
        f"本次提供 **{len(options)} 家{intent.target_tier}酒店** 供比较。",
        "",
        "### 推荐对比",
        "",
    ]
    for option in options:
        room = option.room_types[0] if option.room_types else None
        status = (
            "预算内"
            if room and room.within_budget
            else f"预计超出总预算约 ￥{money(room.budget_overage if room else 0)}"
        )
        room_text = f"{room.room_name}约 ￥{money(room.total_price)}" if room else "暂无可用房型"
        lines.append(f"- **{option.hotel_name}**：{option.reason}；默认房型{room_text}，{status}。")
    lines.extend(
        [
            "",
            "### 下一步",
            "",
            next_step,
            "确认后只替换所选住宿，其他行程保持不变。",
        ]
    )
    return "\n".join(lines)


def _hotel_catalog(hotels: list[dict]) -> list[dict]:
    return [
        {
            "id": str(hotel.get("id") or ""),
            "name": hotel.get("name"),
            "tier": _hotel_tier(hotel),
            "description": hotel.get("description"),
        }
        for hotel in hotels
    ]


def _resolve_hotel_names(values: list, query: str, hotels: list[dict]) -> tuple[str, ...]:
    known = [str(hotel.get("name")) for hotel in hotels if hotel.get("name")]
    resolved = []
    for value in values:
        name = str(value or "").strip()
        if name in known and name not in resolved:
            resolved.append(name)
    if resolved or not query:
        return tuple(resolved)
    normalized = query.replace("安曼", "安缦").strip()
    substring = [name for name in known if normalized in name or name in normalized]
    if substring:
        return (substring[0],)
    scored = sorted(
        ((SequenceMatcher(None, normalized, name).ratio(), name) for name in known),
        reverse=True,
    )
    return (scored[0][1],) if scored and scored[0][0] >= 0.35 else ()


def _hotel_intent_from_decision(req: ChatTurnRequest, hotels: list[dict], data: dict) -> HotelIntent:
    hotel_request = data.get("hotel_request") if isinstance(data.get("hotel_request"), dict) else {}
    base_tier = _current_hotel_tier(req, hotels)
    action = str(hotel_request.get("action") or "same")
    if action not in _INTENT_LABELS:
        action = "same"
    target = str(hotel_request.get("target_tier") or "")
    intent = _normalized_hotel_intent(action, target, base_tier)
    candidate_mode = str(hotel_request.get("candidate_mode") or "recommend")
    names = _resolve_hotel_names(
        hotel_request.get("hotel_names") if isinstance(hotel_request.get("hotel_names"), list) else [],
        str(hotel_request.get("hotel_query") or ""),
        hotels,
    )
    explicitly_mentioned = _mentioned_hotel_names(req.message, hotels)
    # 推荐类请求不能让模型把上下文中的当前酒店误当成用户本轮明确指定的酒店。
    # 只有本轮原话确实出现酒店名，且模型选择 exact/specific 时才收窄为唯一候选。
    if candidate_mode != "exact" or action != "specific" or not explicitly_mentioned:
        names = ()
    else:
        names = tuple(name for name in names if name in explicitly_mentioned) or explicitly_mentioned
    if names:
        tiers = [_hotel_tier(hotel) for hotel in hotels if hotel.get("name") in names]
        intent = HotelIntent("specific", max(tiers, key=lambda tier: _TIER_RANK[tier]), base_tier)

    available = _available_hotel_day_nos(req)
    valid_day_nos = set(range(1, req.days + 1))
    raw_days = hotel_request.get("day_numbers")
    day_numbers = tuple(
        dict.fromkeys(
            int(day_no)
            for day_no in (raw_days if isinstance(raw_days, list) else [])
            if isinstance(day_no, int) and day_no in valid_day_nos
        )
    )
    try:
        night_count = int(hotel_request.get("night_count"))
    except (TypeError, ValueError):
        night_count = 0
    if day_numbers:
        night_count = len(day_numbers)
    night_count = max(1, min(night_count or len(available) or req.days, len(available) or req.days))
    intent = HotelIntent(
        action=intent.action,
        target_tier=intent.target_tier,
        base_tier=base_tier,
        requested_nights=night_count,
        requested_day_nos=day_numbers,
        requested_hotel_names=names,
    )
    # 入住晚次以用户本轮原话为准，不信任模型可能臆测的 day_numbers；同时
    # 统一检查“最后一晚/第 N 晚/住 N 晚”是否落在实际有住宿安排的晚次内。
    return _with_stay_scope(intent, req, hotels)


def _hotel_signature(plans: list[dict]) -> list[tuple[int, str]]:
    return sorted(
        (int(plan.get("day_no")), str(item.get("poi_name")))
        for plan in plans
        if isinstance(plan, dict) and isinstance(plan.get("day_no"), int)
        for item in (plan.get("items") or [])
        if item.get("item_type") == "hotel"
    )


def _hotel_proposal_response(
    req: ChatTurnRequest,
    hotels: list[dict],
    intent: HotelIntent,
    operations: list[dict] | None = None,
    fallback_reply: str | None = None,
) -> ChatTurnResponse:
    # 最终边界：无论意图来自 LLM 还是确定性兜底，都再次用本轮原话校正
    # 入住晚次，防止模型输出的 day_numbers 覆盖“最后一晚/第 N 晚”等明确表达。
    intent = _with_stay_scope(intent, req, hotels)
    if not _available_hotel_day_nos(req) and not _has_explicit_stay_scope(req.message):
        return ChatTurnResponse(
            reply=(
                "### 当前没有可替换的住宿\n\n"
                "当前行程中没有已安排的住宿晚次，因此无法直接执行换酒店。"
                "请先补充入住日期或延长行程，本次没有修改。"
            ),
            plans=[],
            changed=False,
            hotel_options=[],
            requires_confirmation=False,
            plan_document=_trip_plan_document(req),
            operations=operations or [],
        )
    if intent.invalid_scope:
        return ChatTurnResponse(
            reply=(
                "### 入住晚次超出当前行程\n\n"
                f"当前行程只有 **{len(_available_hotel_day_nos(req))} 晚住宿安排**，"
                "请先延长行程，或改为当前行程中的具体入住晚次。行程没有被修改。"
            ),
            plans=[],
            changed=False,
            hotel_options=[],
            requires_confirmation=False,
            plan_document=_trip_plan_document(req),
            operations=operations or [],
        )
    options = _hotel_options(req, hotels, intent)
    pending_action = {
        "type": "replace_hotel",
        "hotel_names": list(intent.requested_hotel_names),
        "target_tier": intent.target_tier,
        "day_numbers": list(intent.requested_day_nos),
        "night_count": intent.requested_nights,
        "requires_confirmation": True,
    }
    if options:
        reply = _explain_hotel_options(req, options, intent)
    else:
        reply = fallback_reply or (
            "### 暂时没有可展示的酒店候选\n\n"
            "当前城市的酒店参考数据不足，暂时无法生成可选择的酒店和房型卡片；"
            "行程没有被修改，请稍后重试或换一个住宿档次。"
        )
    return ChatTurnResponse(
        reply=reply,
        plans=[],
        changed=False,
        hotel_options=options,
        requires_confirmation=bool(options),
        plan_document=_trip_plan_document(req),
        operations=operations or [],
        pending_action=pending_action,
    )
