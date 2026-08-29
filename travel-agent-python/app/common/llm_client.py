"""LLM 网关客户端。

职责：
- 封装对 OpenAI 兼容聊天接口的调用，供 agent 层以最少参数发起结构化/普通对话。

实现要点：
- LLMClient.chat 支持 system/user 消息、temperature、max_tokens、
  enable_search（百炼联网搜索）与 json_mode（response_format=json_object）；
- complete 是单轮 user 提示的便捷封装；get_llm_client 提供进程内单例；
- 结构化意图/草稿编辑优先使用低延迟模型 llm_fast_model（见 config）。

依赖：
- app.common.config.settings；httpx；外部 LLM 服务。
"""

import httpx

from app.common.config import settings
from app.agent.trace import record_event

DEFAULT_SYSTEM_PROMPT = "你是一个专业的旅游行程规划助手，请用中文回答，只输出结构化结果。"


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048,
             enable_search: bool = False, model: str | None = None,
             json_mode: bool = False) -> str:
        url = self._base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if enable_search:
            # dashscope 兼容层：顶层 enable_search 开启百炼联网搜索插件
            payload["enable_search"] = True
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        body = resp.json()
        usage = body.get("usage") or {}
        record_event("llm", "llm.request", metadata={
            "model": model or self._model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        })
        return body["choices"][0]["message"]["content"]

    def complete(self, user_prompt: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                 temperature: float = 0.7, max_tokens: int = 2048,
                 enable_search: bool = False) -> str:
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            enable_search=enable_search,
        )


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
