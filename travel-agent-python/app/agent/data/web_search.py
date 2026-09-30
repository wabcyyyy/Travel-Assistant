"""开放联网搜索：基于 DashScope 百炼 enable_search 插件。

研究阶段证据不足、备选池类目缺口、价格核验共用这一层。
失败一律返回空结果，不允许影响主生成流程。
"""

from __future__ import annotations

import json
import logging
import re

from app.agent.runtime.run_limits import current_limits
from app.agent.runtime.trace import record_event
from app.common.addons import addons
from app.common.config import settings
from app.common.external_client import BACKGROUND, ExternalClient, redact_secrets
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# 联网搜索的补池通道（G-3.2）：成功缓存 30min（同一 query 短期会反复出现），
# 负结果 2min（搜不到要能较快重试）。
#
# retry_attempts 保持 0（审查 P2-8 评估结论：**不改**）：本车道底层是
# `llm_client.complete(enable_search=True)`，而 LLM 通道自身已对 408/409/425/
# 429/5xx 重试一次（llm_client._LLM_MAX_ATTEMPTS=2）。在这之上再开一层重试 =
# 单次逻辑检索最多 4 次**付费**（token + 联网搜索插件）调用；web 补池是证据增强
# 通道（池满与否只影响候选丰富度，不决定用户可见的 draft_only），用 2× 成本换
# 边际证据不值。失败已有痕迹：负缓存 120s 后可自然重探，且预算耗尽与失败都记事件。
_search_client: ExternalClient = ExternalClient(
    name="web_search",
    ttl_seconds=1800,
    negative_ttl_seconds=120,
    timeout_seconds=60,
)


def web_search_enabled() -> bool:
    # G-3.1：env 是默认值来源，addon 是运行时开关（管理端可关）
    return bool(settings.web_search_enabled and settings.llm_api_key and addons.is_enabled("web_search"))


def _check_budget(caller: str) -> bool:
    """检索预算检查。耗尽必须**响亮**：静默返回空会被上层当成"搜了但没有"，
    于是"证据为零"与"预算没了"在报表里长成同一个样子（PLAN-A1 P4 的成因之一）。
    """
    limits = current_limits()
    if not limits:
        return True
    try:
        limits.check("retrieval")
        limits.record_retrieval(1)
        return True
    except Exception as exc:
        record_event(
            "decision",
            "web_search_budget_exhausted",
            status="error",
            metadata={"caller": caller, "error": str(exc)[:120]},
        )
        return False


def web_search_text(question: str, *, max_tokens: int = 400) -> str:
    """联网问答，返回纯文本；失败返回空串。"""
    if not web_search_enabled() or not question or not _check_budget("web_search_text"):
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
    if not web_search_enabled() or not question:
        return None
    prompt = question.strip()[:500]

    def _load() -> dict | list | None:
        if not _check_budget("web_search_json"):
            return None
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
        try:
            return _parse_llm_json(raw)
        except ValueError as exc:
            # 可观测（2026-09-30 UI 评审遗留）：此前解析失败只留 external_client 一行
            # `Expecting value`，原始响应（HTML 错误页/截断/夹 prose）完全不可见。
            # 头尾截取足矣定位病因；脱敏走 redact_secrets（响应体可能回显请求 URL）。
            logger.warning(
                "web_search: unparseable answer (%s); head=%r tail=%r",
                exc,
                redact_secrets(raw[:200]),
                redact_secrets(raw[-80:]),
            )
            raise

    return _search_client.call(f"json:{prompt}", _load, lane=BACKGROUND)


#: 尾逗号是 LLM 产 JSON 最常见的轻微畸变（json_mode 也挡不住模型在截断处补逗号）
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _parse_llm_json(raw: str) -> dict | list | None:
    """LLM 联网回答 → JSON：围栏剥离 + 括号截取（既有语义不变）+ 尾逗号修复。

    - 找不到任何 JSON 结构：warning 留痕后返回 None（负结果语义，负缓存 120s）；
    - 有结构但解析不动：抛 ValueError（失败语义，计入 external_client 熔断计数）——
      谁调用谁留痕，`_load` 负责补原始响应头尾日志。
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    start_arr, end_arr = text.find("["), text.rfind("]")
    candidates: list[str] = []
    if start != -1 and end != -1 and (start_arr == -1 or start < start_arr):
        candidates.append(text[start : end + 1])
    if start_arr != -1 and end_arr != -1:
        candidates.append(text[start_arr : end_arr + 1])
    if not candidates:
        logger.warning("web_search: answer has no JSON structure, head=%r", redact_secrets(text[:160]))
        return None
    last: Exception | None = None
    for candidate in candidates:
        # dict.fromkeys 去重：候选无尾逗号时避免同一串解析两遍
        for attempt in dict.fromkeys((candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate))):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as exc:
                last = exc
    raise ValueError(f"unparseable JSON payload: {last}") from last


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
