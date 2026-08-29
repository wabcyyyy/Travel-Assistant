"""Agent 运行轨迹采集。

轨迹只记录节点/工具的名称、状态、耗时和脱敏摘要，不保存完整 Prompt、密钥或用户原文。
它既可用于离线评测，也可在 API 层接入日志/指标系统；没有开启采集时不会改变业务行为。
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator


_active_recorder: contextvars.ContextVar["TraceRecorder | None"] = contextvars.ContextVar(
    "active_agent_trace", default=None
)


def _summary(value: Any) -> Any:
    """生成小而安全的结构摘要，避免把 Prompt/计划全文写入轨迹。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 80:
            return value[:77] + "..."
        return value
    if isinstance(value, dict):
        return {"keys": sorted(str(k) for k in value.keys())[:30], "size": len(value)}
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        if len(values) <= 20 and all(isinstance(item, (str, int, float, bool)) for item in values):
            return values
        return {"type": type(value).__name__, "size": len(value)}
    return type(value).__name__


class TraceRecorder:
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, name: str, *, status: str = "ok",
               duration_ms: float | None = None, metadata: dict[str, Any] | None = None,
               error: str | None = None) -> None:
        event: dict[str, Any] = {
            "kind": kind,
            "name": name,
            "status": status,
        }
        if duration_ms is not None:
            event["duration_ms"] = round(duration_ms, 2)
        if metadata:
            event["metadata"] = {str(k): _summary(v) for k, v in metadata.items()}
        if error:
            event["error"] = error[:200]
        self.events.append(event)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "events": list(self.events)}


@contextmanager
def trace_run(run_id: str | None = None) -> Iterator[TraceRecorder]:
    recorder = TraceRecorder(run_id)
    token = _active_recorder.set(recorder)
    try:
        yield recorder
    finally:
        _active_recorder.reset(token)


def record_event(kind: str, name: str, *, status: str = "ok",
                 metadata: dict[str, Any] | None = None, error: str | None = None) -> None:
    recorder = _active_recorder.get()
    if recorder is not None:
        recorder.record(kind, name, status=status, metadata=metadata, error=error)


@contextmanager
def trace_span(kind: str, name: str, *, metadata: dict[str, Any] | None = None) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        recorder = _active_recorder.get()
        if recorder is not None:
            recorder.record(kind, name, status="error",
                            duration_ms=(time.perf_counter() - started) * 1000,
                            metadata=metadata, error=str(exc))
        raise
    else:
        recorder = _active_recorder.get()
        if recorder is not None:
            recorder.record(kind, name, duration_ms=(time.perf_counter() - started) * 1000,
                            metadata=metadata)


def traced(kind: str, name: str) -> Callable:
    """给同步 LangGraph 节点或工具增加统一轨迹事件。"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            metadata = {"arg_count": len(args), "kwarg_names": sorted(kwargs)}
            with trace_span(kind, name, metadata=metadata):
                return func(*args, **kwargs)
        return wrapper
    return decorator
