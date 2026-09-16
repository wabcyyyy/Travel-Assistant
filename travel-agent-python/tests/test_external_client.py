"""ExternalClient 基类测试（G-3.2）。

覆盖卡要求的三条路径 + 另两项能力：
- 缓存命中（含负结果短 TTL：正/负 TTL 不同，验证负结果更快过期）；
- 超时（loader 抛异常 → 降级 None，不打断调用方）；
- 响应超限（clamp_bytes 拒收，不做"截断后当成功"）；
- 自节流（双车道：后台车道超 max_wait 放弃本次调用）；
- key 解析链（env → 实例 → 调用方；全空返回 None，绝不借用他人 key）。
"""

from __future__ import annotations

import pytest

from app.common.external_client import BACKGROUND, INTERACTIVE, ExternalClient


def test_cache_hit_avoids_second_call():
    client = ExternalClient(name="t", ttl_seconds=60, max_wait_seconds=0)
    calls = []

    def loader():
        calls.append(1)
        return {"v": 1}

    assert client.call("k", loader) == {"v": 1}
    assert client.call("k", loader) == {"v": 1}
    assert len(calls) == 1, "第二次必须命中缓存，不再打外部"


def test_negative_result_uses_shorter_ttl(monkeypatch):
    """负结果走 negative_ttl：正结果 TTL 更短时不影响负结果，反之亦然。"""
    client = ExternalClient(name="t", ttl_seconds=3600, negative_ttl_seconds=10, max_wait_seconds=0)
    calls = []

    def missing():
        calls.append("miss")
        return None

    assert client.call("n", missing) is None
    assert client.call("n", missing) is None
    assert len(calls) == 1, "负结果同样进缓存（避免反复打空）"

    # 时间推进超过负 TTL → 允许重试
    import time

    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + 11)
    assert client.call("n", missing) is None
    assert len(calls) == 2, "负 TTL 过期后必须能再试（否则一次失败锁死整天）"


def test_positive_and_negative_ttl_are_independent(monkeypatch):
    """正结果 TTL=0（禁用缓存）时，负结果仍按自己的 TTL 缓存。"""
    client = ExternalClient(name="t", ttl_seconds=0, negative_ttl_seconds=60, max_wait_seconds=0)
    calls = []

    def flaky():
        calls.append(1)
        return None if len(calls) == 1 else {"ok": True}

    assert client.call("k", flaky) is None
    assert client.call("k", flaky) is None, "负结果仍在缓存期内"
    assert len(calls) == 1


def test_loader_exception_degrades_to_none():
    """超时/网络异常一律降级 None：外部依赖失败不得打断生成（INV-9/降级纪律）。"""
    client = ExternalClient(name="t", max_wait_seconds=0)

    def boom():
        raise TimeoutError("read timeout")

    assert client.call("k", boom) is None


def test_clamp_bytes_rejects_oversized_response():
    client = ExternalClient(name="t", max_response_bytes=16)
    assert client.clamp_bytes(b"small") == b"small"
    assert client.clamp_bytes("x" * 100) is None, "超限必须拒收，不能截断后当成功"
    assert client.clamp_bytes(None) is None


def test_background_lane_throttles_and_gives_up():
    """后台车道最小间隔 1s；超过 max_wait 即放弃（返回 None 且不打外部）。"""
    client = ExternalClient(name="t", max_wait_seconds=0.01)
    calls = []

    def loader():
        calls.append(1)
        return "v"

    assert client.call("a", loader, lane=BACKGROUND) == "v"
    # 紧接的第二次：需要等 ~1s 但只允许等 0.01s → 放弃
    assert client.call("b", loader, lane=BACKGROUND) is None
    assert len(calls) == 1, "被节流放弃时不得执行 loader"


def test_interactive_lane_waits_within_budget():
    """前台车道间隔短（0.2s），在 max_wait 内应等待并通过。"""
    client = ExternalClient(name="t", max_wait_seconds=1.0)
    calls = []

    def loader():
        calls.append(1)
        return "v"

    assert client.call("a", loader, lane=INTERACTIVE) == "v"
    assert client.call("b", loader, lane=INTERACTIVE) == "v"
    assert len(calls) == 2, "前台可在等待预算内完成，而非被放弃"


def test_resolve_key_chain_never_borrows_others():
    assert ExternalClient.resolve_key(None, "  ", "caller") == "caller"
    assert ExternalClient.resolve_key("env", "instance", "caller") == "env", "env 优先"
    assert ExternalClient.resolve_key(None, "instance", "caller") == "instance"
    assert ExternalClient.resolve_key(None, None, None) is None, "全空即无 key，不回落到他人凭据"


def test_clear_cache_allows_refetch():
    client = ExternalClient(name="t", ttl_seconds=3600, max_wait_seconds=1.0)
    calls = []

    def loader():
        calls.append(1)
        return {"v": 1}

    client.call("k", loader)
    client.clear_cache()
    client.call("k", loader)
    assert len(calls) == 2


@pytest.mark.parametrize("lane", [INTERACTIVE, BACKGROUND])
def test_lane_names_are_registered(lane):
    """车道名必须在表内（防拼错导致永远走默认间隔）。"""
    from app.common.external_client import _LANE_MIN_INTERVAL

    assert lane in _LANE_MIN_INTERVAL
