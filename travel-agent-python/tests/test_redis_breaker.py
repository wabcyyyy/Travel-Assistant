"""Redis 快失败 + 熔断：连不上 Redis 时，热路径不能每次命令都付连接超时。

钉住三件真实代价很高的事：
1. 共享客户端必须带 `socket_connect_timeout`（本机实测：不带时一次失败命令 2.0s，
   而 `is_revoked` 在每个鉴权请求上、`cache_store` 在每次详情读上）；
2. 一次失败后开熔断窗口，窗口内 `client()` 直接返回 None，各调用方走既有的进程内兜底；
3. 窗口**不因后续失败续期**，否则有持续流量时 Redis 恢复后也永远不会被重试。
"""

from __future__ import annotations

import pytest
import redis

from app.common import redis_client, token_revocation
from app.common.config import settings
from app.services import cache_store, state_and_sessions


@pytest.fixture(autouse=True)
def isolated_dead_redis(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    redis_client.reset_for_tests()
    cache_store.reset_for_tests()
    token_revocation.reset_for_tests()
    yield
    redis_client.reset_for_tests()


def test_shared_client_sets_fast_fail_timeouts():
    client = redis_client.client()
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == redis_client.CONNECT_TIMEOUT_SECONDS
    assert kwargs["socket_timeout"] == redis_client.CONNECT_TIMEOUT_SECONDS
    assert kwargs["decode_responses"] is True
    # 单例：热路径不重复建连接池
    assert redis_client.client() is client


def test_failed_command_opens_breaker_and_client_returns_none():
    with pytest.raises(redis.exceptions.TimeoutError):
        redis_client.client().exists("probe")
    redis_client.note_failure(RuntimeError("connection refused"))
    assert redis_client.is_down() is True
    assert redis_client.client() is None


def test_consumers_degrade_to_local_state_while_breaker_open(monkeypatch):
    redis_client.note_failure(RuntimeError("down"))
    # 缓存：读写都退回进程内，不抛异常
    cache_store.set_json("itinerary:detail", "1", {"id": 1}, 60)
    assert cache_store.get_json("itinerary:detail", "1") == {"id": 1}
    # 黑名单：本地表仍然生效（登出后 token 仍被判为已吊销）
    token_revocation.revoke("tok-1", 60)
    assert token_revocation.is_revoked("tok-1") is True
    # 限流计数：进程内滑动窗口继续计数
    assert state_and_sessions.sliding_hit("auth:login:fail:1.1.1.1|alice", 900) == 1
    assert state_and_sessions.sliding_hit("auth:login:fail:1.1.1.1|alice", 900) == 2


def test_breaker_window_is_not_extended_by_repeated_failures(monkeypatch):
    clock = {"now": 1_000.0}
    monkeypatch.setattr(redis_client.time, "monotonic", lambda: clock["now"])

    redis_client.note_failure(RuntimeError("first"))
    clock["now"] += redis_client.BREAKER_COOLDOWN_SECONDS / 2
    redis_client.note_failure(RuntimeError("second"))
    clock["now"] += redis_client.BREAKER_COOLDOWN_SECONDS
    # 从首次失败起满一个窗口即恢复探测；续期过的话这里仍是 None
    assert redis_client.client() is not None
