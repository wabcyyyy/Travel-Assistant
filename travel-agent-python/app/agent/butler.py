"""管家式讲解与景点详细介绍生成。"""

import json
import logging

from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def run_butler_note(req: dict) -> str:
    client = get_llm_client()
    preferences = "、".join(req.get("preferences") or []) or "无特别偏好"
    system = (
        "你是一对一专属旅游管家。行程已按用户偏好安排完毕，请用管家的口吻向用户讲解你的安排思路："
        "为什么根据TA的偏好选这些点、节奏如何张弛、酒店怎么考虑、以及一条实用贴士。"
        "亲切专业，250 字以内，分段用 \\n，不要用 markdown 标题符号。"
    )
    user = (
        f"用户画像：{req.get('city')} {req.get('days')} 天 {req.get('persons')} 人，"
        f"偏好：{preferences}，住宿档次：{req.get('hotel_tier') or '未指定'}，"
        f"预算：{req.get('budget') or '未设'}\n"
        f"最终行程：{json.dumps(req.get('plans') or [], ensure_ascii=False)}\n"
        f"系统校验日志：{json.dumps(req.get('validation_log') or [], ensure_ascii=False)}"
    )
    raw = client.complete(user, system_prompt=system, temperature=0.5, max_tokens=800)
    return raw.strip()


def run_poi_intros(city: str, names: list[str]) -> dict:
    client = get_llm_client()
    system = (
        "你是目的地百科编辑。为每个地点写一段 60~90 字的详细介绍：涵盖特色亮点、"
        "历史/文化背景一句话、实用游玩建议（如最佳时段/玩法）。基于常识客观描述，"
        "不要编造具体价格。只输出 JSON：{\"intros\":{\"名称\":\"介绍\",...}}，"
        "必须覆盖给出的所有名称。"
    )
    raw = client.complete(
        f"城市：{city}\n地点列表：{json.dumps(names, ensure_ascii=False)}",
        system_prompt=system,
        temperature=0.3,
        max_tokens=2000,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    intros = data.get("intros")
    if not isinstance(intros, dict) and isinstance(data.get("plans"), dict):
        intros = data.get("plans")
    return intros if isinstance(intros, dict) else {}
