"""P0-2 深度断流取消：llm_client 行级取消、trip_stream 取消收尾、队列桥接。

覆盖：
- stream_chat_deltas：请求前取消不发起请求；中途取消掐断在途流（关闭响应）；
- run_generate_trip_stream：取消后不产出 done/suggestions，run 记 cancelled_runs；
- _bridge_worker_events：正常收尾送达事件；消费端取消（等价 Starlette 断连）→
  worker 在 5s 内停止且不再产出；
- 端点端到端：NDJSON 契约事件与生产者异常兜底。
"""

import asyncio
import json
import threading
import time

import pytest

from app.agent.observability import metrics, observe_run
from app.agent.trip_stream import run_generate_trip_stream
from app.api.agent import _bridge_worker_events
from app.common import llm_client
from app.common.config import settings
from app.common.llm_client import StreamCancelled
from app.schemas.trip import GenerateDayRequest


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False)


class _FakeStreamResponse:
    """httpx stream 响应替身：记录关闭状态与已消费行数。"""

    def __init__(self, lines: list[str], cancel: threading.Event, cancel_at: int | None) -> None:
        self._lines = lines
        self._cancel = cancel
        self._cancel_at = cancel_at
        self.consumed = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for index, line in enumerate(self._lines):
            if self._cancel_at is not None and index >= self._cancel_at:
                self._cancel.set()
            self.consumed += 1
            yield line


class _FakeHttpClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.stream_calls = 0

    def stream(self, *args, **kwargs):
        self.stream_calls += 1
        return self._response

    def is_closed(self):
        return False


def _llm_lines(count: int = 5) -> list[str]:
    return [_sse({"choices": [{"delta": {"content": f"chunk-{i}"}}]}) for i in range(count)]


class TestStreamChatDeltasCancel:
    def test_cancel_before_request_skips_http_call(self, monkeypatch):
        cancel = threading.Event()
        cancel.set()
        fake = _FakeHttpClient(_FakeStreamResponse([], cancel, None))
        monkeypatch.setattr(llm_client, "_get_http_client", lambda: fake)
        with pytest.raises(StreamCancelled):
            list(llm_client.LLMClient().stream_chat_deltas([{"role": "user", "content": "hi"}], cancel=cancel))
        assert fake.stream_calls == 0

    def test_cancel_mid_stream_aborts_closes_and_skips_usage(self, monkeypatch):
        metrics.reset()
        cancel = threading.Event()
        response = _FakeStreamResponse(_llm_lines(5), cancel, cancel_at=2)
        monkeypatch.setattr(llm_client, "_get_http_client", lambda: _FakeHttpClient(response))
        received: list[str] = []
        with observe_run("cancel-llm-run"):
            with pytest.raises(StreamCancelled):
                for delta in llm_client.LLMClient().stream_chat_deltas(
                    [{"role": "user", "content": "hi"}], cancel=cancel
                ):
                    received.append(delta)
        assert received == ["chunk-0", "chunk-1"]  # 第 3 行到达时取消，未继续消费
        assert response.consumed == 3
        assert response.closed, "退出 with 块应在途 HTTP 流被断开"
        trace = metrics.get_trace("cancel-llm-run")
        assert any(e["name"] == "llm.stream_request" and e["status"] == "cancelled" for e in trace["events"])
        # 用量分片未到：token 未知，不计 llm_calls（避免把取消误计为失败/成功）
        assert metrics.snapshot()["llm_calls"] == 0


class _CancelAfterFirstChunkClient:
    """模拟 llm_client 语义：cancel 置位即抛 StreamCancelled 并统计产出。"""

    def __init__(self, cancel: threading.Event, cancel_at_chunk: int = 1) -> None:
        self._cancel = cancel
        self._cancel_at = cancel_at_chunk
        self.chunks = 0

    def stream_chat_deltas(self, messages, **kwargs):
        first = (
            '{"trip_theme":"测试主题","daily_plans":['
            '{"day_no":1,"items":[{"item_type":"attraction","poi_name":"测试点",'
            '"latitude":30.0,"longitude":120.0}]}'
        )
        yield first
        self.chunks += 1
        for _ in range(100):
            self._cancel.set()
            if self._cancel.is_set():
                raise StreamCancelled("客户端断开，LLM 流已中断")
            self.chunks += 1
            yield ""


def _req(days: int = 3) -> GenerateDayRequest:
    return GenerateDayRequest(city="杭州", persons=1, days=days, day_no=1, needs_hotel=False)


@pytest.fixture
def stream_env(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_generation_web_search", False)
    monkeypatch.setattr("app.agent.landing.local_ground", lambda item, city, cache: None)


class TestTripStreamCancel:
    def test_pre_cancelled_returns_empty_without_llm_call(self, stream_env):
        metrics.reset()
        cancel = threading.Event()
        cancel.set()
        with observe_run("pre-cancel-run"):
            events = list(run_generate_trip_stream(_req(1), cancel=cancel))
        assert events == []
        assert metrics.snapshot()["cancelled_runs"] == 1

    def test_cancel_mid_stream_keeps_emitted_days_and_skips_done(self, stream_env, monkeypatch):
        metrics.reset()
        cancel = threading.Event()
        fake = _CancelAfterFirstChunkClient(cancel)
        monkeypatch.setattr("app.agent.trip_stream.get_llm_client", lambda: fake)
        started = time.monotonic()
        with observe_run("cancel-stream-run"):
            events = list(run_generate_trip_stream(_req(3), cancel=cancel))
        elapsed = time.monotonic() - started
        types = [e["type"] for e in events]
        assert types.count("day") == 1, "取消前已产出的天应保留"
        assert "done" not in types, "取消后不再产出 done/suggestions"
        assert elapsed < 5
        snapshot = metrics.snapshot()
        assert snapshot["cancelled_runs"] == 1
        assert snapshot["failures"] == 0


class TestBridgeWorkerEvents:
    def test_normal_completion_delivers_events_then_ends(self):
        async def scenario():
            def producer(cancel):
                yield {"type": "start", "runId": "r"}
                yield {"type": "done", "complete": True}

            return [line async for line in _bridge_worker_events(producer)]

        lines = asyncio.run(scenario())
        assert [json.loads(line) for line in lines] == [
            {"type": "start", "runId": "r"},
            {"type": "done", "complete": True},
        ]

    def test_consumer_cancel_stops_producer(self):
        """消费端被取消（等价 Starlette 断连取消响应生成器）→ 生产者停止。"""
        produced: list[int] = []
        stopped = threading.Event()

        def producer(cancel):
            try:
                while not cancel.is_set():
                    produced.append(len(produced) + 1)
                    yield {"type": "day", "n": len(produced)}
                    time.sleep(0.01)
            finally:
                stopped.set()

        async def scenario():
            received: list[str] = []

            async def consume():
                async for _line in _bridge_worker_events(producer):
                    received.append(_line)

            task = asyncio.create_task(consume())
            deadline = time.monotonic() + 5
            while len(received) < 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert len(received) >= 2, "桥接应先正常送达事件"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        assert stopped.wait(5), "断连后 worker 应在 5s 内停止"
        frozen = len(produced)
        time.sleep(0.2)
        assert len(produced) == frozen, "取消后不再继续产出"


class TestGenerateStreamEndpoint:
    @staticmethod
    def _post(monkeypatch, fake_stream):
        from fastapi.testclient import TestClient

        from main import app

        monkeypatch.setattr("app.api.agent.run_generate_trip_stream", fake_stream)
        with TestClient(app) as client:
            return client.post("/api/agent/v1/generate-stream", json={"city": "杭州", "days": 1, "persons": 1})

    def test_streams_contract_events(self, monkeypatch):
        def fake_stream(req, cancel=None):
            # start 由端点自身产出（runId 来自 trace），生成器只负责业务事件
            yield {
                "type": "done",
                "daysExpected": 1,
                "daysEmitted": [1],
                "tripTheme": None,
                "complete": True,
                "message": None,
            }

        response = self._post(monkeypatch, fake_stream)
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert [e["type"] for e in events] == ["start", "done"]
        assert events[0]["runId"], "start 事件应携带 runId"

    def test_producer_failure_yields_error_event(self, monkeypatch):
        def boom_stream(req, cancel=None):
            raise RuntimeError("llm down")
            yield  # pragma: no cover - 保持生成器形态

        response = self._post(monkeypatch, boom_stream)
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert [e["type"] for e in events] == ["start", "error"]
        assert events[-1]["message"]
