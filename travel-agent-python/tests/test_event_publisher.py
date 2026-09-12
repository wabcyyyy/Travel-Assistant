"""event_publisher 单测：伪造 Redis 客户端验证信封协议与尽力而为语义。

协议契约（与 Java SSE 网关共用，不得偏离）：
- 通道 gen:events:{itineraryId}；信封五键 camelCase；
- seq 取自 Redis INCR gen:seq:{itineraryId}，每次 INCR 后 EXPIRE 7200s；
- ts 为东八区 ISO-8601；
- itineraryId 缺失完全不触碰 Redis；Redis 故障不向上抛异常。
"""

import json

import pytest

from app.common import event_publisher
from app.common.config import settings


class FakeRedis:
    """最小 Redis 桩：记录 incr/expire/publish 调用，可注入故障。"""

    def __init__(self, fail: bool = False):
        self.counters: dict[str, int] = {}
        self.expires: list[tuple[str, int]] = []
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key: str, ttl: int) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.expires.append((key, ttl))

    def publish(self, channel: str, payload: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.published.append((channel, payload))


@pytest.fixture(autouse=True)
def _isolated_publisher():
    """用例前后重置单例，避免跨用例串状态。"""
    event_publisher.reset_event_publisher()
    yield
    event_publisher.reset_event_publisher()


@pytest.fixture()
def fake_redis(monkeypatch) -> FakeRedis:
    """注入伪造客户端并记录其调用，供断言。"""
    fake = FakeRedis()
    monkeypatch.setattr(event_publisher, "_get_client", lambda: fake)
    return fake


def test_publish_event_envelope_and_channel(fake_redis):
    event_publisher.publish_event(123, "research_start", {"domains": ["attraction"]})

    assert len(fake_redis.published) == 1
    channel, payload = fake_redis.published[0]
    assert channel == "gen:events:123"
    envelope = json.loads(payload)
    # 信封五键齐全且全部 camelCase
    assert set(envelope) == {"type", "itineraryId", "seq", "ts", "data"}
    assert envelope["type"] == "research_start"
    assert envelope["itineraryId"] == 123
    assert envelope["data"] == {"domains": ["attraction"]}
    # ts 为东八区 ISO-8601（带 +08:00 偏移）
    assert envelope["ts"].endswith("+08:00")


def test_seq_increments_and_expire_called(fake_redis):
    event_publisher.publish_event(7, "research_start", {})
    event_publisher.publish_event(7, "research_done", {})
    event_publisher.publish_event(8, "research_start", {})

    first = json.loads(fake_redis.published[0][1])
    second = json.loads(fake_redis.published[1][1])
    third = json.loads(fake_redis.published[2][1])
    # 同一行程 seq 单调递增；不同行程使用独立计数键
    assert (first["seq"], second["seq"], third["seq"]) == (1, 2, 1)
    # 每次 INCR 后都续期 EXPIRE 7200s
    assert fake_redis.expires == [
        ("gen:seq:7", 7200), ("gen:seq:7", 7200), ("gen:seq:8", 7200),
    ]


def test_redis_error_never_propagates(monkeypatch):
    monkeypatch.setattr(event_publisher, "_get_client", lambda: FakeRedis(fail=True))
    # 事件是尽力而为通知：Redis 故障只记日志，绝不影响主流程
    event_publisher.publish_event(42, "research_done", {"evidenceCount": 3})


def test_missing_itinerary_id_never_touches_redis(monkeypatch):
    calls: list[str] = []

    def _spy_client():
        calls.append("created")
        return FakeRedis()

    monkeypatch.setattr(event_publisher, "_get_client", _spy_client)
    event_publisher.publish_event(None, "research_start", {"domains": []})
    event_publisher.publish_event(0, "research_start", {"domains": []})
    # 无有效 itineraryId 时不创建客户端、不发出任何命令
    assert calls == []


def test_high_level_helpers_shape(fake_redis):
    event_publisher.publish_research_start(5, ["attraction", "hotel", "food"])
    event_publisher.publish_research_done(5, 9, True,
                                          [{"domain": "attraction", "count": 4},
                                           {"domain": "food", "count": 3},
                                           {"domain": "hotel", "count": 2}])
    event_publisher.publish_degraded(5, "research", "研究失败：x", "以现有证据继续生成")

    types = [json.loads(p)[ "type"] for _c, p in fake_redis.published]
    assert types == ["research_start", "research_done", "degraded"]
    done = json.loads(fake_redis.published[1][1])
    # Python 负责的事件 data 契约：camelCase 键 + 各域计数
    assert done["data"] == {
        "evidenceCount": 9,
        "degraded": True,
        "domains": [{"domain": "attraction", "count": 4},
                    {"domain": "food", "count": 3},
                    {"domain": "hotel", "count": 2}],
    }
    degraded = json.loads(fake_redis.published[2][1])
    assert degraded["data"] == {"scope": "research", "reason": "研究失败：x",
                                "fallback": "以现有证据继续生成"}


def test_publish_event_with_run_id_merges_run_id_and_records_trace(fake_redis, monkeypatch):
    """M5 三向关联：run_id 并入 data 自定义区（runId），并以 scene=stream 落当前 trace。"""
    recorded: list[tuple] = []
    monkeypatch.setattr("app.agent.trace.record_event",
                        lambda kind, name, **kwargs: recorded.append((kind, name, kwargs)))
    data = {"domains": ["attraction"]}
    event_publisher.publish_event(9, "research_start", data, run_id="run-abc")

    envelope = json.loads(fake_redis.published[0][1])
    # 信封仍是五键：runId 只进 data 自定义区，不破坏协议，也不污染调用方 dict
    assert set(envelope) == {"type", "itineraryId", "seq", "ts", "data"}
    assert envelope["data"] == {"domains": ["attraction"], "runId": "run-abc"}
    assert data == {"domains": ["attraction"]}
    # 同一次发布落当前 trace：kind=stream、name=事件类型，元数据带行程与轨迹 ID
    assert recorded == [("stream", "research_start", {
        "metadata": {"event": "research_start", "itinerary_id": 9, "run_id": "run-abc"},
    })]


def test_publish_event_without_run_id_keeps_legacy_shape(fake_redis, monkeypatch):
    """无 run_id 时行为不变：data 无 runId，也不产生 stream 轨迹事件。"""
    recorded: list[tuple] = []
    monkeypatch.setattr("app.agent.trace.record_event", lambda *a, **k: recorded.append((a, k)))
    event_publisher.publish_event(9, "research_start", {"domains": ["attraction"]})

    envelope = json.loads(fake_redis.published[0][1])
    assert envelope["data"] == {"domains": ["attraction"]}
    assert "runId" not in envelope["data"]
    assert recorded == []


def test_research_helpers_forward_run_id(fake_redis):
    """便捷函数把 run_id 原样透传给 publish_event（M5 day_stream 调用形态）。"""
    event_publisher.publish_research_start(5, ["attraction"], run_id="run-1")
    event_publisher.publish_research_done(5, 1, False,
                                          [{"domain": "attraction", "count": 1}], run_id="run-1")
    event_publisher.publish_degraded(5, "research", "r", "f", run_id="run-1")

    assert [json.loads(p)["data"]["runId"] for _c, p in fake_redis.published] == \
        ["run-1", "run-1", "run-1"]


def test_client_lazy_singleton_uses_settings_url(monkeypatch):
    # 用真实工厂验证：from_url 不发起连接，按 settings.redis_url 惰性建单例
    monkeypatch.setattr(settings, "redis_url", "redis://cache-host:6380/2")
    event_publisher.reset_event_publisher()
    client = event_publisher._get_client()
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "cache-host"
    assert kwargs["port"] == 6380
    assert kwargs["db"] == 2
    # decode_responses=True：JSON 字符串直接以 str 收发
    assert kwargs["decode_responses"] is True
    # 单例：二次获取返回同一实例
    assert event_publisher._get_client() is client
