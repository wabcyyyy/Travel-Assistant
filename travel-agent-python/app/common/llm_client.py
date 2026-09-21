"""LLM 网关客户端。

职责：
- 封装对 OpenAI 兼容聊天接口的调用，供 agent 层以最少参数发起结构化/普通对话。

实现要点：
- 进程内共享 httpx.Client（连接池 + keep-alive），避免每次请求新建 TCP；
- connect/read 超时分层：连接超时短、读超时对齐 LLM_TIMEOUT / run deadline；
- LLMClient.chat 支持 system/user 消息、temperature、max_tokens、
  enable_search（百炼联网搜索）与 json_mode（response_format=json_object）；
- complete 是单轮 user 提示的便捷封装；get_llm_client 提供进程内单例；
- 结构化意图/草稿编辑优先使用低延迟模型 llm_fast_model（见 config）；
- stream_chat 支持流式输出，适用于多日整段生成场景。

依赖：
- app.common.config.settings；httpx；外部 LLM 服务。
"""

import contextlib
import json
import threading
import time
from collections.abc import Iterator

import httpx

from app.agent.observability import current_scene, metrics
from app.agent.run_limits import RunLimitExceeded, current_limits
from app.agent.trace import record_event
from app.agent.usage_store import usage_store
from app.common.config import settings

_http_client: httpx.Client | None = None
_http_lock = threading.Lock()


def _build_timeout(read: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.llm_connect_timeout,
        read=read,
        write=settings.llm_connect_timeout,
        pool=settings.llm_connect_timeout,
    )


def _get_http_client() -> httpx.Client:
    """共享连接池客户端；timeout 在单次请求上覆盖（read 可随 deadline 变化）。"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        with _http_lock:
            if _http_client is None or _http_client.is_closed:
                limits = httpx.Limits(
                    max_connections=settings.llm_pool_max_connections,
                    max_keepalive_connections=settings.llm_pool_max_keepalive,
                    keepalive_expiry=30.0,
                )
                _http_client = httpx.Client(
                    timeout=_build_timeout(settings.llm_timeout),
                    limits=limits,
                    follow_redirects=True,
                )
    return _http_client


def close_http_client() -> None:
    """测试/进程退出：关闭共享客户端。"""
    global _http_client
    with _http_lock:
        if _http_client is not None and not _http_client.is_closed:
            _http_client.close()
        _http_client = None


def _record_usage(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    started: float,
    success: bool,
    error: str | None = None,
) -> None:
    """把一次调用明细写入用量库（场景由 contextvar 推断）。"""
    # 用量记录失败不影响主流程
    with contextlib.suppress(Exception):
        usage_store.record(
            scene=current_scene(),
            model=model or settings.llm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            success=success,
            error=error,
        )


DEFAULT_SYSTEM_PROMPT = "你是一个专业的旅游行程规划助手，请用中文回答，只输出结构化结果。"

# 可重试的 HTTP 状态：限流与网关/服务端瞬时错误。4xx（除 429）是请求本身
# 的问题，重试只会放大失败，不重试。
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_LLM_MAX_ATTEMPTS = 2  # 含首次，即对可重试错误额外重试一次


class StreamCancelled(Exception):
    """流式生成被取消（客户端断开）。

    语义：在途 HTTP 流随即中断（退出 with 块即断开连接，网关侧停止生成），
    不属于服务故障——不重试、不计入失败指标。
    """


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


def _retry_sleep(attempt: int) -> None:
    # 指数退避 + 少量抖动，避免同步 LLM 网关的瞬时过载被放大。
    time.sleep(min(2.0**attempt * 0.3, 2.0))


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout

    def chat_response(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
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
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        limits = current_limits()
        try:
            if limits:
                limits.check("llm")
            timeout = self._timeout
            if limits and limits.deadline_seconds > 0:
                remaining = limits.deadline_seconds - (time.monotonic() - limits.started_at)
                timeout = min(timeout, max(0.1, remaining))
            started = time.monotonic()
            for attempt in range(_LLM_MAX_ATTEMPTS):
                try:
                    # 每次真实 HTTP 调用都消耗 run 预算，重试同样受限额约束。
                    if limits and attempt > 0:
                        limits.check("llm")
                    resp = _get_http_client().post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=_build_timeout(timeout),
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except Exception as exc:
                    # 瞬时错误（超时/429/5xx）指数退避后重试一次；其余直接上抛。
                    if attempt + 1 >= _LLM_MAX_ATTEMPTS or not _is_retryable(exc):
                        raise
                    record_event("llm", "llm.retry", status="error", error=str(exc), metadata={"attempt": attempt + 1})
                    _retry_sleep(attempt)
        except RunLimitExceeded as exc:
            record_event("llm", "llm.request", status="error", error=str(exc), metadata={"budget_exhausted": True})
            raise
        except Exception as exc:
            _record_usage(model, 0, 0, started, False, str(exc))
            raise
        usage = body.get("usage") or {}
        # 全局 token 统计收口：无论是否处于 trace 上下文，每次真实调用都上报。
        metrics.record_llm_call(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        _record_usage(
            model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), started, True
        )
        if limits:
            try:
                limits.record_llm(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            except RunLimitExceeded as exc:
                record_event(
                    "llm",
                    "llm.request",
                    status="error",
                    error=str(exc),
                    metadata={
                        "budget_exhausted": True,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                    },
                )
                raise
        record_event(
            "llm",
            "llm.request",
            metadata={
                "model": model or self._model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )
        choices = body.get("choices") or []
        if not choices:
            # 内容审查/风控等场景网关会返回空 choices；抛语义化 ValueError
            # 而不是 IndexError，上层降级链按普通失败处理。
            raise ValueError(f"LLM 未返回任何候选（finish_reason={body.get('finish_reason')}）")
        return {"message": choices[0]["message"], "usage": usage, "finish_reason": choices[0].get("finish_reason")}

    def stream_chat_deltas(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
        cancel: threading.Event | None = None,
    ) -> Iterator[str]:
        """流式调用 LLM，逐段 yield 内容增量（不做重试；异常在迭代时抛出）。

        适用于整段多日生成的「边流边解析」场景：调用方增量喂给 JSON 解析器，
        每解析出一个完整对象即可开始处理，无需等全部 token 生成完毕。
        成功结束时在本生成器内完成一次用量上报（与 stream_chat 成功路径一致）。

        cancel：客户端断开的取消信号（可选）。置位后：请求前直接拒绝发起；
        请求中在每行到达时检查并抛 StreamCancelled——退出 with 块即断开在途
        HTTP 流。取消时 token 用量未知，不写 usage 行（避免把取消误计为失败），
        只落一条 cancelled 轨迹事件。
        """
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
            "stream": True,
        }
        if enable_search:
            payload["enable_search"] = True
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # 让网关在最后一个分片返回 usage，用于 token 统计。
        payload["stream_options"] = {"include_usage": True}

        if cancel is not None and cancel.is_set():
            # 已取消：连请求都不发起（调用方已在取消态）
            raise StreamCancelled("客户端已断开，未发起 LLM 请求")

        limits = current_limits()
        if limits:
            limits.check("llm")
        timeout = self._timeout
        if limits and limits.deadline_seconds > 0:
            remaining = limits.deadline_seconds - (time.monotonic() - limits.started_at)
            timeout = min(timeout, max(0.1, remaining))

        started = time.monotonic()
        stream_usage: dict = {}
        content_length = 0
        with _get_http_client().stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=_build_timeout(timeout),
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if cancel is not None and cancel.is_set():
                    # 深度取消：抛异常退出 with 块即断开在途 HTTP 流（网关侧停止生成）。
                    # 用量分片未到（token 未知）故不写 usage 行；轨迹事件供成本排查。
                    record_event(
                        "llm",
                        "llm.stream_request",
                        status="cancelled",
                        metadata={
                            "model": model or self._model,
                            "content_length": content_length,
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
                    raise StreamCancelled("客户端断开，LLM 流已中断")
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    stream_usage = chunk["usage"]
                # usage-only 末分片的 choices 为空列表，注意防空。
                delta = chunk.get("choices", [{}])[0].get("delta", {}) if chunk.get("choices") else {}
                content = delta.get("content")
                if content:
                    content_length += len(content)
                    yield content

        prompt = int(stream_usage.get("prompt_tokens") or 0)
        completion = int(stream_usage.get("completion_tokens") or 0)
        metrics.record_llm_call(prompt, completion)
        _record_usage(model, prompt, completion, started, True)
        # 流式与阻塞式共用同一份 RunLimits：不记这一次，max_llm_calls / max_tokens
        # 在产品主路径（逐日流式）上永远读不到消耗，额度门等于只装了非流式那半边。
        # 顺序照抄 `chat_response`：**先**记用量与账单，**后**扣额度——
        # 否则恰好触发上限的那一次调用（最贵的一次）从用量表里消失，成本报表偏低。
        if limits:
            try:
                limits.record_llm(prompt, completion)
            except RunLimitExceeded as exc:
                record_event(
                    "llm",
                    "llm.stream_request",
                    status="error",
                    error=str(exc),
                    metadata={"budget_exhausted": True, "prompt_tokens": prompt, "completion_tokens": completion},
                )
                raise
        record_event(
            "llm",
            "llm.stream_request",
            metadata={
                "model": model or self._model,
                "content_length": content_length,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
            },
        )

    def stream_chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """流式调用 LLM，返回完整响应文本。适用于多日整段生成等长响应场景。"""
        started = time.monotonic()
        content_parts: list[str] = []
        try:
            for delta in self.stream_chat_deltas(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                enable_search=enable_search,
                model=model,
                json_mode=json_mode,
            ):
                content_parts.append(delta)
        except RunLimitExceeded as exc:
            record_event(
                "llm", "llm.stream_request", status="error", error=str(exc), metadata={"budget_exhausted": True}
            )
            raise
        except Exception as exc:
            _record_usage(model, 0, 0, started, False, str(exc))
            raise
        return "".join(content_parts)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        response = self.chat_response(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_search=enable_search,
            model=model,
            json_mode=json_mode,
        )
        return str(response["message"].get("content") or "")

    def complete(
        self,
        user_prompt: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            enable_search=enable_search,
            model=model,
            json_mode=json_mode,
        )

    def stream_complete(
        self,
        user_prompt: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        enable_search: bool = False,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """流式单轮调用的便捷封装。"""
        return self.stream_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            enable_search=enable_search,
            model=model,
            json_mode=json_mode,
        )


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
