"""城市引导：用户输入省份/区域时，LLM 推断偏好并引导选择支持的城市。"""

import json
import logging

from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def run_city_guide(req: dict) -> dict:
    client = get_llm_client()
    supported = req.get("supported") or []
    system = (
        "你是旅行城市引导助手。判断用户输入的地名："
        "1. 若是具体旅游城市且在支持列表→ {\"kind\":\"city\",\"city\":\"规范名\",\"question\":null,\"suggestions\":[]}"
        "2. 若是省份/区域/不明确→ 结合对话推断用户旅行喜好，优先推荐支持列表中"
        "同省或体验最接近的 1~3 个城市，并提一个帮助缩小范围的问题："
        "{\"kind\":\"province\",\"city\":null,\"question\":\"问题\",\"suggestions\":[\"城市\",...]}"
        "3. 无法判断→ {\"kind\":\"unclear\",\"city\":null,\"question\":\"请说出你想去的城市或省份\",\"suggestions\":[]}"
        "只输出 JSON。若该省没有任何支持城市，就推荐支持列表中体验类型最接近的，"
        "并在 question 里说明该省暂未开通。"
    )
    messages = [{"role": "system", "content": system}]
    for h in (req.get("history") or [])[-6:]:
        role = "user" if h.get("role") == "user" else "assistant"
        if h.get("content"):
            messages.append({"role": role, "content": str(h["content"])[:500]})
    messages.append({
        "role": "user",
        "content": f"用户输入：{req.get('input')}\n支持城市列表：{json.dumps(supported, ensure_ascii=False)}",
    })
    raw = client.chat(messages, temperature=0.2, max_tokens=600)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    return {
        "kind": str(data.get("kind") or "unclear"),
        "city": data.get("city"),
        "question": data.get("question"),
        "suggestions": [s for s in (data.get("suggestions") or []) if isinstance(s, str)][:3],
    }
