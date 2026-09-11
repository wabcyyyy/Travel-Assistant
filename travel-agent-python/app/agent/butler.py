"""管家式讲解与景点详细介绍生成。

景点介绍（poi_intros）使用受限 Function Calling Loop：
模型可调用 Tool Registry 只读工具（search_pois）补充事实后再写介绍，
避免纯凭空编造；写入型工具不在 Registry 中，不可被调用。
"""

import json
import logging

from app.agent.function_calling import FunctionCallingError, run_tool_call_loop
from app.common.config import settings
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def run_butler_note(req: dict) -> str:
    client = get_llm_client()
    preferences = "、".join(req.get("preferences") or []) or "无特别偏好"
    system = (
        "你是一对一专属旅游管家。行程已按用户偏好与特别要求安排完毕，请用管家的口吻向用户讲解你的安排思路："
        "为什么根据TA的偏好选这些点（若用户最初输入的是省份，先自然说明为什么首选该城市，"
        "并提到想去省内其他城市可随时调整）、特别要求是如何落实的、节奏如何张弛、酒店怎么考虑、以及一条实用贴士。"
        "亲切专业，250 字以内，分成 3~4 个自然段（段与段之间空一行），"
        "不要用 markdown 标题符号，不要输出字面的反斜杠n或转义符。"
    )
    user = (
        f"用户最初输入的区域：{req.get('region_hint') or '同目的地'}。\n"
        f"用户画像：{req.get('city')} {req.get('days')} 天 {req.get('persons')} 人，"
        f"偏好：{preferences}，住宿档次：{req.get('hotel_tier') or '未指定'}，"
        f"预算：{req.get('budget') or '未设'}\n"
        f"用户额外要求：{req.get('requirements') or '无'}\n"
        f"最终行程：{json.dumps(req.get('plans') or [], ensure_ascii=False)}\n"
        f"系统校验日志：{json.dumps(req.get('validation_log') or [], ensure_ascii=False)}"
    )
    raw = client.complete(user, system_prompt=system, temperature=0.5, max_tokens=800)
    note = raw.strip().replace("\\n", "\n")
    if not note:
        raise ValueError("butler note empty")
    return note


def run_poi_intros(city: str, names: list[str]) -> dict:
    """为行程内景点写介绍；允许模型通过 Function Calling 检索只读 POI 事实。

    契约：最终仍只输出 `{intros: {name: text}}`；工具结果只作为中间证据，
    不写库、不改行程。FC 失败时回退为无工具的单轮 complete（保持可用性）。
    """
    client = get_llm_client()
    system = (
        "你是目的地百科编辑。为每个地点写一段 60~90 字的详细介绍：涵盖特色亮点、"
        "历史/文化背景一句话、实用游玩建议（如最佳时段/玩法）。"
        "若对某地点事实不确定，可先调用 search_pois 工具检索该城市候选再写；"
        "工具只读，禁止编造具体价格。只输出 JSON："
        '{"intros":{"名称":"介绍",...}}，必须覆盖给出的所有名称。'
    )
    user = f"城市：{city}\n地点列表：{json.dumps(names, ensure_ascii=False)}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = ""
    try:
        loop = run_tool_call_loop(
            client, messages, max_rounds=2,
            model=settings.llm_fast_model or None,
        )
        message = loop.get("message") or {}
        raw = str(message.get("content") or "")
    except FunctionCallingError as exc:
        # FC 超轮/协议失败：降级单轮生成，不拖垮介绍接口
        logger.warning("poi_intros function calling fallback: %s", exc)
        raw = ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("poi_intros FC unexpected error, fallback: %s", exc)
        raw = ""
    if not raw.strip():
        raw = client.complete(
            user, system_prompt=system, temperature=0.3, max_tokens=2000,
            model=settings.llm_fast_model or None,
        )
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return {}
    intros = data.get("intros")
    if not isinstance(intros, dict) and isinstance(data.get("plans"), dict):
        intros = data.get("plans")
    return intros if isinstance(intros, dict) else {}
