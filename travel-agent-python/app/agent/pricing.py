"""实时价格查询：酒店/餐饮均走 DashScope 百炼联网搜索插件（enable_search）。

查询失败一律返回 None，由调用方回退到知识库价或城市均价。
"""

import json
import logging

from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_HOTEL_SYSTEM_PROMPT = (
    "你是酒店价格查询助手。基于联网搜索结果回答，不要编造。只输出 JSON，格式："
    '{"found": true或false, "price_per_night": 每晚人民币数字或null, "note": "价格来源与适用条件，20字内"}'
    "注意 price_per_night 与 note 中出现的价格一律换算成人民币，不要报日元/美元原币数字。"
)

_FOOD_SYSTEM_PROMPT = (
    "你是餐饮价格查询助手。基于联网搜索结果回答，不要编造。只输出 JSON，格式："
    '{"found": true或false, "price_per_person": 人均人民币数字或null, "note": "价格来源与适用条件，20字内"}'
    "注意一律换算成人民币，不要报日元/美元原币。"
)


def _parse_price_json(raw: str, price_key: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    data = json.loads(text[start : end + 1])
    if not data.get("found"):
        return None
    price = data.get(price_key)
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    return {"price": round(float(price), 2), "note": str(data.get("note") or "")[:60]}


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
        raw = client.complete(
            question,
            system_prompt=_HOTEL_SYSTEM_PROMPT,
            temperature=0.1,
            enable_search=True,
        )
        return _parse_price_json(raw, "price_per_night")
    except Exception as e:  # noqa: BLE001 —— 定价失败不允许影响主流程
        logger.warning("live hotel price search failed (%s/%s): %s", city, hotel_name, e)
        return None


def query_live_food_price(city: str, restaurant_name: str) -> dict | None:
    """餐饮人均实时价；失败返回 None，由调用方钳制/回落城市均价。"""
    try:
        client = get_llm_client()
        question = (
            f"{city}「{restaurant_name}」正常一餐人均消费大约多少人民币？"
            "只报一个有代表性的人均价格，已换算人民币。"
        )
        raw = client.complete(
            question,
            system_prompt=_FOOD_SYSTEM_PROMPT,
            temperature=0.1,
            enable_search=True,
        )
        return _parse_price_json(raw, "price_per_person")
    except Exception as e:  # noqa: BLE001
        logger.warning("live food price search failed (%s/%s): %s", city, restaurant_name, e)
        return None
