"""酒店实时价格查询：基于 DashScope 百炼联网搜索插件（enable_search）。

查询失败一律返回 None，由调用方回退到"知识库基准价×季节系数"的估算链路。
"""

import json
import logging

from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是酒店价格查询助手。基于联网搜索结果回答，不要编造。只输出 JSON，格式："
    '{"found": true或false, "price_per_night": 数字或null, "note": "价格来源与适用条件，20字内"}'
)


def query_live_price(city: str, hotel_name: str, checkin_date: str | None) -> dict | None:
    """返回 {"price": float, "note": str}（当前挂牌基准价）；查不到或异常返回 None。

    注意：刻意不把未来入住日期放进搜索词——搜索引擎拿不到未来报价，
    查"当前挂牌价"作基准，季节差异由调用方的系数处理。
    """
    try:
        client = get_llm_client()
        question = (
            f"{city}「{hotel_name}」标准房型 目前一晚 网络挂牌价大约多少人民币？"
            "只报一个有代表性的每晚价格。"
        )
        raw = client.complete(question, system_prompt=_SYSTEM_PROMPT, temperature=0.1)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(text[start : end + 1])
        if not data.get("found"):
            return None
        price = data.get("price_per_night")
        if not isinstance(price, (int, float)) or price <= 0:
            return None
        return {
            "price": round(float(price), 2),
            "note": str(data.get("note") or "")[:60],
        }
    except Exception as e:  # noqa: BLE001 —— 定价失败不允许影响主流程
        logger.warning("live price search failed (%s/%s): %s", city, hotel_name, e)
        return None
