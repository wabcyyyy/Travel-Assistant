"""图像意图理解：用户随手拍/截图 → 一段中文描述 + 可直接发给规划助手的一句话。

模型选择口径（2026-10-02 拍板）：BYOK 路由生效时用 route.model（用户自选网关
须自带视觉能力，设置页有提示）；无路由时用 settings.llm_vision_model（与主
通道同 base_url/key，默认 qwen-vl-plus，免新 key）。图片以 OpenAI 兼容
content 数组 image_url(data URI) 直传——瞬时意图输入不是资产，不落盘
（区别于封面路径，见 services/image_intent.py）。
"""

import json
import logging

from app.common.config import settings
from app.common.llm_client import get_llm_client
from app.common.llm_route import current_route

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是旅行规划助手的图像理解模块。用户上传一张图片，想把它变成规划对话的起点。"
    "看图后只输出 JSON（不要输出任何其他文字）："
    '{"text":"用一段自然的中文描述图片里与旅行相关的内容（地点/美食/风景/玩法等，'
    '看不出旅行相关性就客观描述图片主体）",'
    '"suggestedMessage":"一句可直接发给旅行规划助手的话（例如想去图中的地方、想吃图里的菜、'
    '想安排图中的活动；中文口语，不超过 50 字）"}'
)
_MAX_CONTEXT_CHARS = 600


def run_image_intent(data_uri: str, context: str = "") -> dict:
    """看图产出 {text, suggestedMessage}；解析失败抛 ValueError（轨向上由 service 转 502）。"""
    client = get_llm_client()
    route = current_route()
    model = route.model if route is not None else settings.llm_vision_model
    prompt = _PROMPT
    trimmed = (context or "").strip()
    if trimmed:
        prompt = f"{_PROMPT}\n当前对话背景（仅供理解，不要复述）：{trimmed[:_MAX_CONTEXT_CHARS]}"
    raw = client.chat(
        [
            {
                "role": "user",
                # OpenAI 兼容多模态 content 数组：图在前文本在后（与 dashscope 兼容层一致）
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=0.2,
        max_tokens=512,
        model=model,
        json_mode=True,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("image intent parse failed: %s | raw=%s", exc, raw[:200])
        raise ValueError("没能识别这张图片，请换一张试试") from exc
    if not isinstance(data, dict):
        raise ValueError("没能识别这张图片，请换一张试试")
    description = str(data.get("text") or "").strip()
    if not description:
        raise ValueError("没能识别这张图片，请换一张试试")
    # suggestedMessage 缺失/为空时回落描述本身：前端回填输入框永远有内容可填
    suggested = str(data.get("suggestedMessage") or "").strip() or description
    return {"text": description, "suggestedMessage": suggested}
