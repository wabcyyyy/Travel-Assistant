"""DeepSeek 官方 API 适配与思考强度控制单测。

验收点：
1. 对齐 DeepSeek 官方规范：
   - model: deepseek-flash
   - thinking: {"type": "enabled"}
   - reasoning_effort: "low"
   - 不发送非标准的 enable_search 和 enable_thinking（防 400 Bad Request）
2. 保持 DashScope 百炼兼容：
   - enable_search / enable_thinking 正常发送
3. 流式解析隔离：
   - delta 中的 reasoning_content 不会泄露到 content 迭代器
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

import app.agent  # noqa: F401 先完成 agent 门面导入
from app.common import llm_client
from app.common.config import settings
from app.common.llm_client import LLMClient, _apply_provider_options


def test_deepseek_official_payload_options(monkeypatch):
    monkeypatch.setattr(settings, "llm_reasoning_effort", "low")
    monkeypatch.setattr(settings, "llm_enable_thinking", True)

    payload = {"model": "deepseek-flash", "messages": []}
    _apply_provider_options(
        payload,
        base_url="https://api.deepseek.com",
        enable_search=True,
    )

    assert payload.get("reasoning_effort") == "low"
    assert payload.get("thinking") == {"type": "enabled"}
    # 非标参数不得混入官方请求
    assert "enable_search" not in payload
    assert "enable_thinking" not in payload


def test_deepseek_official_disabled_thinking(monkeypatch):
    monkeypatch.setattr(settings, "llm_reasoning_effort", None)
    monkeypatch.setattr(settings, "llm_enable_thinking", False)

    payload = {"model": "deepseek-flash", "messages": []}
    _apply_provider_options(
        payload,
        base_url="https://api.deepseek.com/v1",
        enable_search=False,
    )

    assert payload.get("thinking") == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_dashscope_payload_options(monkeypatch):
    monkeypatch.setattr(settings, "llm_reasoning_effort", "low")
    monkeypatch.setattr(settings, "llm_enable_thinking", True)

    payload = {"model": "qwen-plus", "messages": []}
    _apply_provider_options(
        payload,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        enable_search=True,
    )

    assert payload.get("enable_search") is True
    assert payload.get("enable_thinking") is True
    assert payload.get("reasoning_effort") == "low"
    assert "thinking" not in payload


def test_chat_response_sends_deepseek_parameters(monkeypatch):
    monkeypatch.setattr(settings, "llm_reasoning_effort", "low")
    captured_payloads = []

    class _MockHttpClient:
        def post(self, url, json_payload=None, **kwargs):
            captured_payloads.append(json_payload or kwargs.get("json"))
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "旅程规划完成",
                            "reasoning_content": "先分析天数与偏好...",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
            return resp

        def is_closed(self):
            return False

    monkeypatch.setattr(llm_client, "_get_http_client", lambda: _MockHttpClient())

    client = LLMClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-flash",
    )
    result = client.chat_response(
        messages=[{"role": "user", "content": "你好"}],
        enable_search=True,
    )

    assert len(captured_payloads) == 1
    sent = captured_payloads[0]
    assert sent["model"] == "deepseek-flash"
    assert sent["reasoning_effort"] == "low"
    assert sent["thinking"] == {"type": "enabled"}
    assert "enable_search" not in sent
    assert result["message"]["content"] == "旅程规划完成"


def test_stream_chat_deltas_filters_reasoning_content(monkeypatch):
    class _MockStreamContext:
        def __init__(self, lines):
            self.lines = lines

        def __enter__(self):
            resp = MagicMock()
            resp.iter_lines.return_value = self.lines
            return resp

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class _MockHttpClient:
        def stream(self, method, url, **kwargs):
            sse_lines = [
                'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"深度思考第1步"}}]}',
                'data: {"choices":[{"delta":{"reasoning_content":"深度思考第2步"}}]}',
                'data: {"choices":[{"delta":{"content":"正式"}}]}',
                'data: {"choices":[{"delta":{"content":"内容"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20}}',
                "data: [DONE]",
            ]
            return _MockStreamContext(sse_lines)

        def is_closed(self):
            return False

    monkeypatch.setattr(llm_client, "_get_http_client", lambda: _MockHttpClient())

    client = LLMClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-flash",
    )
    deltas = list(client.stream_chat_deltas([{"role": "user", "content": "你好"}]))
    assert deltas == ["正式", "内容"]
