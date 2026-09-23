"""意图确认节点：多轮对话收集行程条件与偏好。"""

import json
import logging
from datetime import date

from app.common.llm_client import get_llm_client
from app.schemas.trip import ClarifyRequest, ClarifyResponse

logger = logging.getLogger(__name__)

_REQUIRED = ["city", "days", "persons"]
_KNOWN = [*_REQUIRED, "start_date", "stay_nights", "budget", "hotel_tier", "preferences"]
_LABELS = {"city": "目的地城市", "days": "出行天数", "persons": "出行人数"}


def run_clarify(req: ClarifyRequest) -> ClarifyResponse:
    client = get_llm_client()
    system = (
        "你是旅行规划的信息收集助手。从用户最新一句话中抽取槽位，与已有槽位合并。"
        '只输出 JSON：{"city":"城市名或null","start_date":"YYYY-MM-DD或null",'
        '"days":数字或null,"stay_nights":数字或null,"persons":数字或null,'
        '"budget":数字或null,"hotel_tier":"经济型/舒适型/高档型/豪华型/奢华型或null",'
        '"preferences":["偏好"]或null}。没提到的字段一律 null，不要猜测。'
    )
    raw = client.complete(
        f"今天是 {date.today().isoformat()}。\n"
        f"已有槽位：{json.dumps(req.slots, ensure_ascii=False)}\n用户说：{req.message}",
        system_prompt=system,
        temperature=0,
    )
    slots = dict(req.slots or {})
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        for k in _KNOWN:
            v = data.get(k)
            if v not in (None, "", "null"):
                slots[k] = v
    except Exception as e:
        logger.warning("clarify parse failed: %s | raw=%s", e, raw[:200])

    missing = [k for k in _REQUIRED if k not in slots or slots[k] in (None, "")]
    question = None
    if missing:
        question = f"还想确认一下{_LABELS[missing[0]]}～"
    return ClarifyResponse(slots=slots, missing=missing, question=question, ready=not missing)
