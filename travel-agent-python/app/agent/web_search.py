"""开放联网搜索：基于 DashScope 百炼 enable_search 插件。

研究阶段证据不足、备选池类目缺口、价格核验共用这一层。
失败一律返回空结果，不允许影响主生成流程。
"""

from __future__ import annotations

import json
import logging

from app.agent.run_limits import current_limits
from app.common.config import settings
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def web_search_enabled() -> bool:
    return bool(settings.web_search_enabled and settings.llm_api_key)


def _check_budget() -> bool:
    limits = current_limits()
    if not limits:
        return True
    try:
        limits.check("retrieval")
        limits.record_retrieval(1)
        return True
    except Exception:
        return False


def web_search_text(question: str, *, max_tokens: int = 400) -> str:
    """联网问答，返回纯文本；失败返回空串。"""
    if not web_search_enabled() or not question or not _check_budget():
        return ""
    try:
        client = get_llm_client()
        return client.complete(
            question.strip()[:500],
            system_prompt=(
                "你是旅行资料检索助手。基于联网搜索结果回答，不要编造。只输出可直接使用的事实要点，不要寒暄。"
            ),
            temperature=0.1,
            max_tokens=max_tokens,
            enable_search=True,
            model=settings.llm_fast_model or None,
        ).strip()
    except Exception as exc:
        logger.warning("web search failed: %s", exc)
        return ""


def web_search_json(question: str, *, schema_hint: str, max_tokens: int = 800) -> dict | list | None:
    """联网检索并解析 JSON；失败返回 None。"""
    if not web_search_enabled() or not question or not _check_budget():
        return None
    try:
        client = get_llm_client()
        raw = client.complete(
            question.strip()[:500],
            system_prompt=(f"你是旅行资料检索助手。基于联网搜索结果回答，不要编造。只输出 JSON，结构：{schema_hint}"),
            temperature=0.1,
            max_tokens=max_tokens,
            enable_search=True,
            model=settings.llm_fast_model or None,
            json_mode=True,
        ).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        start, end = raw.find("{"), raw.rfind("}")
        start_arr, end_arr = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1 and (start_arr == -1 or start < start_arr):
            return json.loads(raw[start : end + 1])
        if start_arr != -1 and end_arr != -1:
            return json.loads(raw[start_arr : end_arr + 1])
        return None
    except Exception as exc:
        logger.warning("web search json failed: %s", exc)
        return None


_CATEGORY_PROMPTS = {
    "hotel": "真实存在的正式酒店名（不含已排入行程的）",
    "activity": "体验/游玩项目（演出、SPA、潜水、观景台、主题乐园等）",
    "food": "真实餐厅/小吃店正式店名",
    "attraction": "真实景点正式名称",
    "shopping": "真实商场或知名店铺名",
}


def search_places_via_web(
    city: str,
    category: str,
    limit: int = 4,
    *,
    budget_tier: str | None = None,
    intent_keywords: list[str] | None = None,
) -> list[dict]:
    """按类目联网补池：返回 [{name, category, intro, estimated_cost}]，不保证有坐标。"""
    if not web_search_enabled() or limit <= 0:
        return []
    kind = _CATEGORY_PROMPTS.get(category, "真实存在的地点名")
    tier_hint = f"消费档次参考：{budget_tier}。" if budget_tier else ""
    # M3-②（AD5）最小增量：意图关键词逐词以「city + keyword」追加进 query（只追加不改既有规则）
    intent_pairs = "、".join(f"{city} {str(k).strip()}" for k in (intent_keywords or []) if str(k).strip())
    intent_hint = f"另请优先考虑与这些意图词相关的地点：{intent_pairs}。" if intent_pairs else ""
    data = web_search_json(
        f"{city}有哪些{kind}？请给出 {limit} 个，优先高口碑、有代表性、名称可搜索到的。"
        f"必须全部是目的地「{city}」本地的真实地点，禁止给出中国同名/相似名地点。{tier_hint}{intent_hint}",
        schema_hint='{"items":[{"name":"地点名","intro":"一句话亮点","estimated_cost":人均或每晚人民币数字或null}]}',
        max_tokens=700,
    )
    rows = data.get("items") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        cost = row.get("estimated_cost")
        out.append(
            {
                "name": name,
                "category": category,
                "intro": str(row.get("intro") or "").strip()[:80] or None,
                "estimated_cost": float(cost) if isinstance(cost, (int, float)) and cost > 0 else None,
                "source": "web.search",
            }
        )
    return out
