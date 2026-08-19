import httpx

from app.common.config import settings

DEFAULT_SYSTEM_PROMPT = "你是一个专业的旅游行程规划助手，请用中文回答，只输出结构化结果。"


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048) -> str:
        url = self._base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def complete(self, user_prompt: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                 temperature: float = 0.7) -> str:
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client