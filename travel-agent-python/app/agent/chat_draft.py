"""草稿式行程对话：LLM 直接改写结构化行程草稿，应用时零 LLM 确定性落库。"""

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import ceil
from datetime import date, timedelta

from app.agent import tools
from app.common.llm_client import get_llm_client
from app.common.season import season_factor, season_label
from app.schemas.trip import ChatTurnRequest, ChatTurnResponse, HotelOption, HotelRoomOption

logger = logging.getLogger(__name__)

_PLAN_SCHEMA = (
    '{"plans":[{"day_no":1,"note":"当天主题","items":[{"item_type":"attraction|food|hotel|transport",'
    '"poi_name":"名称","start_time":"HH:mm","end_time":"HH:mm","duration_min":数字或null,'
    '"cost":数字或null,"tag":"标签或null","remark":"备注或null"}]}]}'
)

_TIER_RANK = {"经济型": 1, "舒适型": 2, "高档型": 3, "豪华型": 4, "奢华型": 5}
_TIER_KEYWORDS = {
    "经济型": ("经济", "连锁"),
    "舒适型": ("舒适", "中端", "亚朵", "全季"),
    "高档型": ("高端", "高档", "精品", "五星"),
    "豪华型": ("豪华", "五星", "国宾", "地标"),
    "奢华型": ("奢华", "国宾", "传奇", "地标", "私享"),
}
_TIER_ALIASES = {
    "经济": "经济型", "舒适": "舒适型", "中端": "舒适型",
    "高端": "高档型", "高档": "高档型", "豪华": "豪华型",
    "五星": "豪华型", "奢华": "奢华型", "顶级": "奢华型",
}

_INTENT_LABELS = {
    "cheaper": "下调一档",
    "same": "更换同档酒店",
    "better": "升级一档",
    "best": "查看最高档酒店",
    "specific": "查看指定档次",
}

_HOTEL_BRAND_ALIASES = (
    "安缦", "四季", "柏悦", "君悦", "亚朵", "汉庭", "全季", "桔子", "欢朋",
    "温德姆", "康莱德", "香格里拉", "索菲特", "紫萱", "西子宾馆", "黄龙饭店",
)


@dataclass(frozen=True)
class HotelIntent:
    action: str
    target_tier: str
    base_tier: str
    requested_nights: int = 0
    requested_day_nos: tuple[int, ...] = ()
    requested_hotel_names: tuple[str, ...] = ()


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
    matched = [tier for tier, keywords in _TIER_KEYWORDS.items()
               if any(keyword in text for keyword in keywords)]
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
    if _mentioned_hotel_names(normalized_message, hotels or []):
        return True
    if re.search(
        r"酒店|住宿|宾馆|客栈|换个住|升级|降一档|便宜点|便宜一点|更好|好一点|"
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
        str(item.get("poi_name")) for plan in req.plans
        for item in (plan.get("items") or [])
        if item.get("item_type") == "hotel" and item.get("poi_name")
    }


def _available_hotel_day_nos(req: ChatTurnRequest) -> list[int]:
    return sorted({
        int(plan.get("day_no")) for plan in req.plans
        if isinstance(plan.get("day_no"), int)
        and any(item.get("item_type") == "hotel" for item in (plan.get("items") or []))
    })


def _cn_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return numbers.get(value)


def _with_stay_scope(intent: HotelIntent, req: ChatTurnRequest, hotels: list[dict]) -> HotelIntent:
    available = _available_hotel_day_nos(req)
    day_nos = []
    if available and re.search(r"最后(?:一)?(?:天|晚)|末(?:天|晚)", req.message):
        day_nos.append(available[-1])
    for value in re.findall(r"第\s*([0-9一二两三四五六七八九十]+)\s*(?:天|晚)", req.message):
        day_no = _cn_number(value)
        if day_no in available and day_no not in day_nos:
            day_nos.append(day_no)
    night_match = re.search(r"([0-9一二两三四五六七八九十]+)\s*晚", req.message)
    requested_nights = _cn_number(night_match.group(1)) if night_match else None
    if day_nos:
        requested_nights = len(day_nos)
    requested_nights = max(1, min(requested_nights or len(available) or req.days, len(available) or req.days))

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
    )


def _current_hotel_tier(req: ChatTurnRequest, hotels: list[dict]) -> str:
    current_names = _current_hotel_names(req)
    known = [_hotel_tier(hotel) for hotel in hotels if hotel.get("name") in current_names]
    if known:
        return max(known, key=lambda tier: _TIER_RANK[tier])
    return _preference_tier(req.hotel_tier)


def _fallback_hotel_intent(message: str, base_tier: str) -> HotelIntent:
    if re.search(r"最屌|最好|最贵|最高级|最高档|顶级|顶配|天花板|最牛", message):
        action = "best"
    elif re.search(r"便宜|省钱|实惠|降一档|低一档|降低|少花", message):
        action = "cheaper"
    elif re.search(r"其他|其它|别的|换一家|换一个|同档|同级|类似", message):
        action = "same"
    elif re.search(r"更好|好一点|好点|升级|升一档|高一档|贵一点|高级一点", message):
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
    base_tier = _current_hotel_tier(req, hotels)
    fallback = _fallback_hotel_intent(req.message, base_tier)
    history = [
        {"role": item.get("role"), "content": str(item.get("content") or "")[:500]}
        for item in (req.history or [])[-4:]
        if item.get("content")
    ]
    try:
        raw = get_llm_client().complete(
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
        ).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        action = str(data.get("action") or "")
        target = str(data.get("target_tier") or "")
        if action in _INTENT_LABELS and target in _TIER_RANK:
            expected = _fallback_hotel_intent(req.message, base_tier)
            # 明确的边界词优先服从确定性规则，避免分类模型把“最屌”弱化为普通升级。
            if expected.action in {"best", "specific"}:
                return _with_stay_scope(expected, req, hotels)
            return _with_stay_scope(_normalized_hotel_intent(action, target, base_tier), req, hotels)
    except Exception as exc:  # noqa: BLE001
        logger.warning("hotel intent classification failed: %s", exc)
    return _with_stay_scope(fallback, req, hotels)


def _hotel_options(req: ChatTurnRequest, hotels: list[dict], intent: HotelIntent) -> list[HotelOption]:
    if not hotels:
        return []
    current_names = _current_hotel_names(req)
    current_costs = [float(item.get("cost")) for plan in req.plans
                     for item in (plan.get("items") or [])
                     if item.get("item_type") == "hotel" and isinstance(item.get("cost"), (int, float))]
    available_day_nos = list(dict.fromkeys(
        _available_hotel_day_nos(req) + list(intent.requested_day_nos)
    ))
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
            float(item.get("cost")) for item in (plan.get("items") or [])
            if item.get("item_type") == "hotel" and isinstance(item.get("cost"), (int, float))
        ) * rooms
        for plan in req.plans if isinstance(plan.get("day_no"), int)
    }
    if intent.requested_day_nos:
        current_scope_total = sum(current_cost_by_day.get(day_no, 0) for day_no in intent.requested_day_nos)
    elif current_total is not None and available_day_nos:
        current_scope_total = current_total / len(available_day_nos) * intent.requested_nights
    else:
        current_scope_total = sum(current_cost_by_day.values()) / max(len(available_day_nos), 1) * intent.requested_nights

    hotel_ids = [int(hotel["id"]) for hotel in hotels if hotel.get("id") is not None]
    room_rows = tools.search_hotel_room_types(hotel_ids)
    rooms_by_hotel: dict[int, list[dict]] = {}
    for room in room_rows:
        rooms_by_hotel.setdefault(int(room["poi_id"]), []).append(room)
    priced_day_nos = list(intent.requested_day_nos) or available_day_nos[:intent.requested_nights]
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
        if tier != intent.target_tier:
            continue
        if hotel.get("name") in current_names and not intent.requested_hotel_names:
            continue
        if intent.requested_hotel_names and hotel.get("name") not in intent.requested_hotel_names:
            continue
        hotel_room_rows = rooms_by_hotel.get(int(hotel.get("id") or 0)) or [{
            "id": f"base-{hotel.get('id')}", "room_name": "基础房型", "base_price": base_price,
            "capacity": 2, "bed_type": None, "breakfast": None,
            "description": "知识库酒店基础房型参考价", "is_default": 1,
        }]
        room_options: list[HotelRoomOption] = []
        for room in hotel_room_rows:
            room_base = float(room.get("base_price") or base_price)
            capacity = max(int(room.get("capacity") or 2), 1)
            room_count = ceil(req.persons / capacity)
            nightly_breakdown = []
            for day_no in priced_day_nos:
                stay_date = start_date + timedelta(days=day_no - 1) if start_date else None
                day_factor = season_factor(stay_date)
                nightly_breakdown.append({
                    "day_no": day_no,
                    "stay_date": stay_date.isoformat() if stay_date else None,
                    "season_label": season_label(stay_date),
                    "season_factor": day_factor,
                    "nightly_price": round(room_base * day_factor, 2),
                })
            room_total = round(sum(row["nightly_price"] for row in nightly_breakdown) * room_count, 2)
            projected = round((current_total or 0) - current_scope_total + room_total, 2)
            room_options.append(HotelRoomOption(**{
                "id": str(room.get("id")),
                "room_name": room.get("room_name") or "基础房型",
                "base_price": round(room_base, 2),
                "nightly_price": nightly_breakdown[0]["nightly_price"] if nightly_breakdown else round(room_base * factor, 2),
                "nights": intent.requested_nights,
                "rooms": room_count,
                "total_price": room_total,
                "price_delta": round(room_total - current_scope_total, 2),
                "projected_hotel_total": projected,
                "within_budget": budget_capacity is None or projected <= budget_capacity,
                "budget_overage": round(max(projected - budget_capacity, 0), 2)
                if budget_capacity is not None else 0,
                "capacity": capacity,
                "bed_type": room.get("bed_type"),
                "breakfast": room.get("breakfast"),
                "description": room.get("description"),
                "is_default": bool(room.get("is_default")),
                "nightly_breakdown": nightly_breakdown,
            }))
        room_options.sort(key=lambda room: (not room.is_default, room.base_price))
        selected_room = room_options[0]
        candidates.append(HotelOption(**{
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
        }))
    candidates.sort(key=lambda item: (
        item.hotel_name not in intent.requested_hotel_names if intent.requested_hotel_names else False,
        not item.within_budget,
        -float(item.rating or 0),
        item.total_price if intent.action == "cheaper" else -item.total_price,
    ))
    return candidates[:3]


def _explain_hotel_options(
    req: ChatTurnRequest, options: list[HotelOption], intent: HotelIntent,
) -> str:
    intent_text = _INTENT_LABELS[intent.action]
    available_nights = len(options[0].available_day_nos) if options else req.days
    if intent.requested_day_nos:
        chosen_nights = "、".join(f"第{day_no}晚" for day_no in intent.requested_day_nos)
        next_step = f"入住晚次已确定为 **{chosen_nights}**，请选择酒店和房型。"
        scope_instruction = f"入住晚次已明确为{chosen_nights}，结尾只追问酒店和房型，不得再次追问入住晚次。"
    elif intent.requested_nights >= available_nights:
        next_step = f"本次默认覆盖 **全部 {available_nights} 晚**，请选择酒店和房型。"
        scope_instruction = f"用户未限定晚次，已默认全选全部{available_nights}晚，结尾只追问酒店和房型。"
    else:
        next_step = f"请选择酒店、房型和 {intent.requested_nights} 个具体入住晚次。"
        scope_instruction = f"用户要求住{intent.requested_nights}晚但未说明哪晚，结尾需追问具体入住晚次和房型。"
    if intent.requested_hotel_names:
        requested_hotels = "、".join(intent.requested_hotel_names)
        if intent.requested_day_nos:
            next_step = f"酒店已确定为 **{requested_hotels}**，入住晚次为 **{chosen_nights}**，请选择具体房型。"
            scope_instruction = (
                f"用户已明确指定{requested_hotels}和{chosen_nights}，结尾只追问具体房型，"
                "不得再次追问酒店或入住晚次。"
            )
        elif intent.requested_nights >= available_nights:
            next_step = f"酒店已确定为 **{requested_hotels}**，默认覆盖全部 {available_nights} 晚，请选择具体房型。"
            scope_instruction = (
                f"用户已明确指定{requested_hotels}，未限定晚次时默认全选全部{available_nights}晚，"
                "结尾只追问具体房型。"
            )
        else:
            next_step = f"酒店已确定为 **{requested_hotels}**，请选择具体房型和 {intent.requested_nights} 个入住晚次。"
            scope_instruction = (
                f"用户已明确指定{requested_hotels}并要求住{intent.requested_nights}晚，但未说明哪晚，"
                "结尾只追问具体房型和入住晚次。"
            )
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
        status = "预算内" if room and room.within_budget else f"预计超出总预算约 ￥{money(room.budget_overage if room else 0)}"
        room_text = f"{room.room_name}约 ￥{money(room.total_price)}" if room else "暂无可用房型"
        lines.append(f"- **{option.hotel_name}**：{option.reason}；默认房型{room_text}，{status}。")
    lines.extend([
        "",
        "### 下一步",
        "",
        next_step,
        "确认后只替换所选住宿，其他行程保持不变。",
    ])
    return "\n".join(lines)


def _trip_plan_document(req: ChatTurnRequest) -> dict:
    """每轮都把关系型行程投影成一份完整 JSON，作为 LLM 唯一可编辑的计划状态。"""
    return {
        "schema_version": 1,
        "trip": {
            "city": req.city,
            "days": req.days,
            "persons": req.persons,
            "budget": req.budget,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "preferences": req.preferences,
            "hotel_tier": req.hotel_tier,
        },
        "days": req.plans,
        "pending_action": None,
    }


def _hotel_catalog(hotels: list[dict]) -> list[dict]:
    return [{
        "id": str(hotel.get("id") or ""),
        "name": hotel.get("name"),
        "tier": _hotel_tier(hotel),
        "description": hotel.get("description"),
    } for hotel in hotels]


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM 未返回 JSON 对象")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM 决策不是 JSON 对象")
    return data


def _decide_plan_change(req: ChatTurnRequest, hotels: list[dict]) -> dict:
    document = _trip_plan_document(req)
    system = (
        "你是旅行计划 JSON 编辑器。你必须先理解用户自然语言，再从四种模式中选择一种，且只输出JSON。"
        "mode只能是 hotel_proposal、plan_update、clarify、no_change。"
        "凡是涉及住宿、酒店、宾馆、房型或某个酒店品牌，无论用户如何措辞，都必须使用hotel_proposal，"
        "绝不能直接修改days里的hotel项目。hotel_proposal时填写hotel_request，不修改plan_document。"
        "普通景点、餐饮、时间、顺序修改使用plan_update，并返回修改后的完整plan_document；"
        "只改用户要求的部分，其余字段逐字保留，禁止修改trip元数据，禁止自行计算或改写cost。"
        "信息不足且无法安全推断时使用clarify。酒店名称必须优先从hotel_catalog中选择完整名称。"
        "day_numbers必须把‘最后一天、返程前一晚、第二晚’等自然语言换算成当前计划中的具体日序号。"
        "hotel_request.action只能是specific、cheaper、same、better、best；"
        "candidate_mode只能是exact或recommend，明确指定酒店时用exact，否则用recommend。"
        "输出结构："
        '{"mode":"hotel_proposal|plan_update|clarify|no_change","reply":"中文Markdown",'
        '"hotel_request":{"action":"specific","hotel_names":["目录完整名称"],"hotel_query":"用户说法",'
        '"target_tier":"经济型|舒适型|高档型|豪华型|奢华型|null","day_numbers":[4],'
        '"night_count":1,"candidate_mode":"exact|recommend","candidate_count":3},'
        '"operations":[{"action":"动作","day_numbers":[1],"summary":"说明"}],'
        '"plan_document":{"schema_version":1,"trip":{},"days":[],"pending_action":null}}'
    )
    messages = [{"role": "system", "content": system}]
    for item in (req.history or [])[-6:]:
        role = "user" if item.get("role") == "user" else "assistant"
        content = str(item.get("content") or "")[:1500]
        if content:
            messages.append({"role": role, "content": content})
    messages.append({
        "role": "user",
        "content": (
            f"当前计划JSON：{json.dumps(document, ensure_ascii=False)}\n"
            f"hotel_catalog：{json.dumps(_hotel_catalog(hotels), ensure_ascii=False)}\n"
            f"用户本轮要求：{req.message}"
        ),
    })
    raw = get_llm_client().chat(messages, temperature=0.1, max_tokens=5000)
    return _parse_json_object(raw)


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
    day_numbers = tuple(dict.fromkeys(
        int(day_no) for day_no in (raw_days if isinstance(raw_days, list) else [])
        if isinstance(day_no, int) and day_no in valid_day_nos
    ))
    try:
        night_count = int(hotel_request.get("night_count"))
    except (TypeError, ValueError):
        night_count = 0
    if day_numbers:
        night_count = len(day_numbers)
    night_count = max(1, min(night_count or len(available) or req.days, len(available) or req.days))
    return HotelIntent(
        action=intent.action,
        target_tier=intent.target_tier,
        base_tier=base_tier,
        requested_nights=night_count,
        requested_day_nos=day_numbers,
        requested_hotel_names=names,
    )


def _extract_document_plans(data: dict, req: ChatTurnRequest) -> list[dict] | None:
    document = data.get("plan_document")
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return None
    trip = document.get("trip")
    if not isinstance(trip, dict):
        return None
    # 行程元数据由业务系统维护，模型不得借修改内容之名改变预算、人数或城市。
    expected = _trip_plan_document(req)["trip"]
    if any(trip.get(key) != value for key, value in expected.items()):
        return None
    plans = document.get("days")
    if not isinstance(plans, list) or len(plans) != req.days:
        return None
    valid_days = {int(plan.get("day_no")) for plan in plans if isinstance(plan, dict)
                  and isinstance(plan.get("day_no"), int)}
    if valid_days != set(range(1, req.days + 1)):
        return None
    return plans


def _hotel_signature(plans: list[dict]) -> list[tuple[int, str]]:
    return sorted(
        (int(plan.get("day_no")), str(item.get("poi_name")))
        for plan in plans if isinstance(plan, dict) and isinstance(plan.get("day_no"), int)
        for item in (plan.get("items") or []) if item.get("item_type") == "hotel"
    )


def run_chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    hotels = tools.search_hotels(req.city, limit=30)
    try:
        decision = _decide_plan_change(req, hotels)
    except Exception as exc:  # noqa: BLE001
        logger.warning("unified plan decision failed: %s", exc)
        # 仅在模型不可用时启用旧规则兜底；正常语义路由不依赖关键词。
        if _is_hotel_request(req, hotels):
            intent = _understand_hotel_intent(req, hotels)
            options = _hotel_options(req, hotels, intent)
            return ChatTurnResponse(
                reply=_explain_hotel_options(req, options, intent) if options else "暂无可用酒店候选。",
                plans=[], changed=False, hotel_options=options,
                requires_confirmation=bool(options),
                plan_document=_trip_plan_document(req),
            )
        raise

    mode = str(decision.get("mode") or "no_change")
    operations = decision.get("operations") if isinstance(decision.get("operations"), list) else []
    if mode == "hotel_proposal":
        intent = _hotel_intent_from_decision(req, hotels, decision)
        options = _hotel_options(req, hotels, intent)
        pending_action = {
            "type": "replace_hotel",
            "hotel_names": list(intent.requested_hotel_names),
            "target_tier": intent.target_tier,
            "day_numbers": list(intent.requested_day_nos),
            "night_count": intent.requested_nights,
            "requires_confirmation": True,
        }
        return ChatTurnResponse(
            reply=_explain_hotel_options(req, options, intent) if options
            else str(decision.get("reply") or "没有找到符合条件的酒店候选。"),
            plans=[], changed=False, hotel_options=options,
            requires_confirmation=bool(options),
            plan_document=_trip_plan_document(req),
            operations=operations,
            pending_action=pending_action,
        )

    if mode == "plan_update":
        plans = _extract_document_plans(decision, req)
        if plans is None:
            return ChatTurnResponse(
                reply="### 无法生成安全草稿\n\n模型返回的计划结构或行程元数据不合法，本次未修改任何内容。",
                plans=[], changed=False, plan_document=_trip_plan_document(req),
            )
        if _hotel_signature(plans) != _hotel_signature(req.plans):
            return ChatTurnResponse(
                reply="### 需要先确认住宿\n\n检测到酒店发生变化。请选择酒店和房型后再应用，本次没有直接修改行程。",
                plans=[], changed=False, plan_document=_trip_plan_document(req),
            )
        updated_document = _trip_plan_document(req)
        updated_document["days"] = plans
        return ChatTurnResponse(
            reply=str(decision.get("reply") or "### 行程草稿已更新\n\n请确认后应用。"),
            plans=plans,
            changed=plans != req.plans,
            plan_document=updated_document,
            operations=operations,
        )

    return ChatTurnResponse(
        reply=str(decision.get("reply") or "本次没有需要修改的内容。"),
        plans=[], changed=False,
        plan_document=_trip_plan_document(req),
        operations=operations,
    )
