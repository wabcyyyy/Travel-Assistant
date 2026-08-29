"""Agent 运行指标与安全轨迹收口。

默认使用进程内聚合，适合本地演示和单实例部署；生产多实例时应把同样的计数器
接入 Prometheus/OTel。指标不保存 Prompt、用户原文或完整计划。
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from app.agent.trace import TraceRecorder, trace_run


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts = {
            "runs": 0,
            "successes": 0,
            "degraded_runs": 0,
            "failures": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "validation_retries": 0,
            "fallback_runs": 0,
            "route_violations": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "mcp_calls": 0,
            "mcp_failures": 0,
            "retrieval_calls": 0,
            "retrieval_fallbacks": 0,
        }
        self._latency_ms = 0.0
        self._last_failures: list[dict] = []
        self._traces: dict[str, dict] = {}

    def record(self, trace: dict, *, success: bool) -> None:
        events = trace.get("events") or []
        durations = [float(e.get("duration_ms") or 0) for e in events]
        status_events = [
            e for e in events
            if e.get("kind") == "decision" and e.get("name") == "run_status"
        ]
        run_status = ((status_events[-1].get("metadata") or {}).get("status")
                      if status_events else None)
        is_degraded = run_status == "degraded"
        is_failed = not success or run_status == "failed"
        delta = {
            "runs": 1,
            # 三态互斥：fallback 完成属于 degraded，不计入 successes。
            "successes": int(success and not is_degraded and not is_failed),
            "failures": int(is_failed),
            # llm.generate 是业务层 span，llm.request 才代表一次实际 HTTP 调用。
            "llm_calls": sum(e.get("kind") == "llm" and e.get("name") == "llm.request" for e in events),
            "tool_calls": sum(e.get("kind") == "tool" for e in events),
            "validation_retries": sum(e.get("kind") == "route" and e.get("name") in ("fix", "retry") for e in events),
            "fallback_runs": sum(e.get("kind") == "route" and e.get("name") == "fallback" for e in events),
            "route_violations": sum(
                e.get("kind") == "decision" and e.get("name") in ("reflect_result", "day.reflect_result")
                and (e.get("metadata") or {}).get("needs_fix") is True
                for e in events
            ),
            "prompt_tokens": sum(
                int((e.get("metadata") or {}).get("prompt_tokens") or 0)
                for e in events if e.get("name") == "llm.request"
            ),
            "completion_tokens": sum(
                int((e.get("metadata") or {}).get("completion_tokens") or 0)
                for e in events if e.get("name") == "llm.request"
            ),
            "mcp_calls": sum(e.get("kind") == "mcp" for e in events),
            "mcp_failures": sum(e.get("kind") == "mcp" and e.get("status") == "error" for e in events),
            "retrieval_calls": sum(e.get("kind") == "retrieval" for e in events),
            "retrieval_fallbacks": sum(
                e.get("kind") == "retrieval" and (e.get("metadata") or {}).get("fallback") is True
                for e in events
            ),
            "degraded_runs": int(is_degraded),
        }
        with self._lock:
            for key, value in delta.items():
                self._counts[key] += value
            self._latency_ms += sum(durations)
            run_id = trace.get("run_id")
            if run_id:
                # 只保留最近 100 条脱敏轨迹，避免进程内指标无限增长。
                self._traces[run_id] = trace
                self._traces = dict(list(self._traces.items())[-100:])
            if is_failed:
                self._last_failures.append({
                    "run_id": trace.get("run_id"),
                    "events": [
                        {"kind": e.get("kind"), "name": e.get("name"), "status": e.get("status"),
                         "error": e.get("error")}
                        for e in events if e.get("status") == "error"
                    ],
                })
                self._last_failures = self._last_failures[-20:]

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self._counts)
            data["success_rate"] = round(data["successes"] / data["runs"], 4) if data["runs"] else 0.0
            data["degraded_rate"] = round(data["degraded_runs"] / data["runs"], 4) if data["runs"] else 0.0
            data["failure_rate"] = round(data["failures"] / data["runs"], 4) if data["runs"] else 0.0
            data["mcp_failure_rate"] = round(data["mcp_failures"] / data["mcp_calls"], 4) if data["mcp_calls"] else 0.0
            data["avg_event_latency_ms"] = round(self._latency_ms / data["runs"], 2) if data["runs"] else 0.0
            data["recent_failures"] = list(self._last_failures)
            return data

    def get_trace(self, run_id: str) -> dict | None:
        """按运行 ID 查询最近的脱敏轨迹。"""
        with self._lock:
            trace = self._traces.get(run_id)
            return dict(trace) if trace is not None else None

    def reset(self) -> None:
        with self._lock:
            for key in self._counts:
                self._counts[key] = 0
            self._latency_ms = 0.0
            self._last_failures.clear()
            self._traces.clear()


metrics = MetricsRegistry()


@contextmanager
def observe_run(run_id: str | None = None) -> Iterator[TraceRecorder]:
    with trace_run(run_id) as recorder:
        try:
            yield recorder
        except Exception as exc:
            recorder.record(
                "decision",
                "run_status",
                status="error",
                metadata={"status": "failed", "error_type": type(exc).__name__},
                error=str(exc),
            )
            metrics.record(recorder.to_dict(), success=False)
            raise
        else:
            metrics.record(recorder.to_dict(), success=True)
