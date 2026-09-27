"""意图确认节点：多轮对话收集行程条件与偏好。"""

import json
import logging
from datetime import date

from app.common.llm_client import get_llm_client
from app.schemas.trip import MAX_TRIP_DAYS, ClarifyRequest, ClarifyResponse

logger = logging.getLogger(__name__)

_REQUIRED = ["city", "days", "persons"]
_KNOWN = [
    *_REQUIRED,
    "start_date",
    "stay_nights",
    "budget",
    "hotel_tier",
    "preferences",
    "origin_city",
]
_LABELS = {"city": "目的地城市", "days": "出行天数", "persons": "出行人数"}
_INT_SLOTS = ("days", "persons")
_DEFAULT_OPTIONS = {
    "city": ["帮我推荐目的地"],
    "days": ["3 天", "5 天", "7 天"],
    "persons": ["2 人", "4 人", "一家人"],
}
_BLOCKED_OPTIONS = [f"改成 {MAX_TRIP_DAYS} 天以内", "拆成两段行程"]
_NEGOTIATION = f"单次行程最多排 {MAX_TRIP_DAYS} 天哦～要不要改成 {MAX_TRIP_DAYS} 天以内，或者拆成两段分开规划？"
_EXTRACT_SPEC = (
    '只输出 JSON：{"city":"城市名或null","origin_city":"出发城市或null",'
    '"start_date":"YYYY-MM-DD或null",'
    '"days":数字或null,"stay_nights":数字或null,"persons":数字或null,'
    '"budget":数字或null,"hotel_tier":"经济型/舒适型/高档型/豪华型/奢华型或null",'
    '"preferences":["偏好"]或null,'
    '"question":"用自然口语说的下一句追问，没有要问的就给null",'
    '"options":["配合question的2~4个短选项，让用户可以点选回答，没有就null"]}。'
)
_SYSTEM_PROMPT = (
    "你是旅行规划的信息收集助手。从用户最新一句话中抽取槽位，与已有槽位合并。"
    f"{_EXTRACT_SPEC}"
    "没提到的字段一律 null，不要猜测。"
    f"单次行程天数上限 {MAX_TRIP_DAYS} 天：用户要超过时 days 照实抽取，"
    f"但 question 必须说明最多 {MAX_TRIP_DAYS} 天，并协商改天数或拆成两段。"
)


def _normalize_int(slots: dict, key: str) -> None:
    """LLM 偶尔把数字槽位吐成「两周」这类词；洗不成正整数就当没抽到，让追问接手。"""
    if key not in slots:
        return
    value = slots[key]
    if isinstance(value, bool):
        slots.pop(key)
        return
    try:
        number = int(value)
    except (TypeError, ValueError):
        slots.pop(key)
        return
    if number < 1:
        slots.pop(key)
    else:
        slots[key] = number


def _ask(req: ClarifyRequest) -> str:
    """LLM 抽取；通道挂了返回空串走模板兜底，对话不得因追问失败而卡死。"""
    client = get_llm_client()
    try:
        return client.complete(
            f"今天是 {date.today().isoformat()}。\n"
            f"已有槽位：{json.dumps(req.slots, ensure_ascii=False)}\n用户说：{req.message}",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0,
        )
    except Exception as e:
        logger.warning("clarify llm call failed: %s", e)
        return ""


def _extract(raw: str, slots: dict) -> tuple[str | None, list[str] | None]:
    """解析 LLM 输出：槽位并入 slots，返回 (question, options)；解析失败等同没抽到。"""
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        for k in _KNOWN:
            v = data.get(k)
            if v not in (None, "", "null"):
                slots[k] = v
        raw_options = data.get("options")
        options = None
        if isinstance(raw_options, list):
            options = [str(o).strip() for o in raw_options if str(o).strip()][:4] or None
        return data.get("question") or None, options
    except Exception as e:
        logger.warning("clarify parse failed: %s | raw=%s", e, raw[:200])
        return None, None


def _respond(slots: dict, missing: list[str], question: str | None, options: list[str] | None) -> ClarifyResponse:
    """三级出口：超天协商 > 缺槽追问 > 就绪（就绪时不带追问，选择交给确认条）。"""
    if isinstance(slots.get("days"), int) and slots["days"] > MAX_TRIP_DAYS:
        # 上限是产品红线：不静默截断，天数原样保留、协商话术交回对话
        return ClarifyResponse(
            slots=slots,
            missing=missing,
            question=question or _NEGOTIATION,
            ready=False,
            options=options or _BLOCKED_OPTIONS,
            blocked=True,
        )
    if missing:
        slot = missing[0]
        return ClarifyResponse(
            slots=slots,
            missing=missing,
            question=question or f"还想确认一下{_LABELS[slot]}～",
            ready=False,
            options=options or _DEFAULT_OPTIONS.get(slot, []),
        )
    return ClarifyResponse(slots=slots, missing=[], question=None, ready=True, options=[])


def run_clarify(req: ClarifyRequest) -> ClarifyResponse:
    slots = dict(req.slots or {})
    question, options = _extract(_ask(req), slots)
    for key in _INT_SLOTS:
        _normalize_int(slots, key)
    missing = [k for k in _REQUIRED if k not in slots or slots[k] in (None, "")]
    return _respond(slots, missing, question, options)
