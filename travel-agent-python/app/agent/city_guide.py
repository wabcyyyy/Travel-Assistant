"""城市引导：管家式自然对话，推断偏好并引导选择目的地城市。"""

import json
import logging

from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def run_city_guide(req: dict) -> dict:
    client = get_llm_client()
    supported = req.get("supported") or []
    system = (
        "你是一位见多识广的旅行管家，正在和用户聊天帮他确定目的地。"
        "用户可能输入省份、区域、模糊想法或具体城市。你的任务："
        "1. 用户明确想去某个具体城市（无论是否在支持列表，如「我想去绍兴」）→ kind=city，"
        "city 填该城市名，message 用一句话确认（非支持列表城市补一句「价格与开放时间为智能参考」），"
        "suggestions 留空，不要反问；"
        "2. 省份/区域 → 严格在该省/区域内推荐：kind=city，city 填该省最热门的旅游城市"
        "（如福建→厦门/福州/泉州这种；浙江→杭州/宁波/乌镇所在的嘉兴；广东→广州/深圳/潮汕的汕头等）；"
        "若该省没有任何一个支持列表中的城市（如福建当前没有支持城市），则 kind=unclear，"
        "message 诚实说明「XX 省暂时没在我们的热门缓存里，不过开放模式同样能为你安排，"
        "想去的话直接点生成即可」，suggestions 留空——绝对不要跨省硬塞其他城市；"
        "message 用 2~3 句说明为什么首选这里，结尾加一句「想去省内的其他城市，生成后随时告诉我调整」；"
        "suggestions 给 1~2 个省内备选城市 {name,reason} 供改选，每个附一句有画面感的卖点；"
        "3. 实在无法判断 → kind=unclear，友好地请TA说更多。"
        "语气要求：自然、热情、有画面感，禁止出现「支持列表」「暂未开通」「服务」这类系统腔。"
        "只输出 JSON：{\"kind\":\"province|city|unclear\",\"city\":null或规范城市名,"
        "\"message\":\"2~3句自然对话\",\"suggestions\":[{\"name\":\"城市\",\"reason\":\"一句话卖点\"}]}"
    )
    messages = [{"role": "system", "content": system}]
    for h in (req.get("history") or [])[-8:]:
        role = "user" if h.get("role") == "user" else "assistant"
        if h.get("content"):
            messages.append({"role": role, "content": str(h["content"])[:600]})
    messages.append({
        "role": "user",
        "content": (
            f"用户输入：{req.get('input')}\n"
            f"当前缓存可直接安排行程的城市：{json.dumps(supported, ensure_ascii=False)}"
        ),
    })
    raw = client.chat(messages, temperature=0.6, max_tokens=800)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(text[text.find("{") : text.rfind("}") + 1])

    suggestions = []
    for s in data.get("suggestions") or []:
        if isinstance(s, dict) and s.get("name"):
            suggestions.append({"name": str(s["name"]), "reason": str(s.get("reason") or "")[:60]})
        elif isinstance(s, str):
            suggestions.append({"name": s, "reason": ""})

    return {
        "kind": str(data.get("kind") or "unclear"),
        "city": data.get("city"),
        "message": str(data.get("message") or "想去哪里玩？说说你的想法～"),
        "suggestions": suggestions[:3],
    }
