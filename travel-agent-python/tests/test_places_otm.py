"""OTM 通道纪律单测（L1 补充 1 + PR-11 验收「降级链事件可见」）。

- 三客户端显式限速与重试登记（geo/radius 0.35s 不重试、detail 1.0s 重试 1 次、
  Nominatim 1.1s 重试 1 次——政策口径直接钉在字段上）；
- 请求必须带可联系 UA（OTM 同 Nominatim 先例）；
- fake clock 断言相邻外呼 ≥ min_interval；
- 供应商连挂 → 熔断开窗（warning 日志可见）→ 检索降级为空池且零外呼。
"""

from __future__ import annotations

import httpx
import pytest

from app.agent.data import places
from app.common.config import settings
from app.common.http_client import configure_clients

pytest_plugins = ["_fake_clock"]


def test_otm_clients_declare_rate_limits_and_retry_policy():
    """限速与重试是政策，不是实现细节：直接钉字段值（L1 补充 1）。"""
    assert places._otm_geo_client.min_interval_seconds == pytest.approx(0.35)
    assert places._otm_radius_client.min_interval_seconds == pytest.approx(0.35)
    assert places._otm_detail_client.min_interval_seconds == pytest.approx(1.0)
    assert places._nominatim_client.min_interval_seconds == pytest.approx(1.1), "Nominatim 公共实例 1 rps 政策"
    # 重试只上幂等 GET：detail（enrich 高频）与 Nominatim 各 1 次，geo/radius 不重试
    assert places._otm_detail_client.retry_attempts == 1
    assert places._nominatim_client.retry_attempts == 1
    assert places._otm_geo_client.retry_attempts == 0
    assert places._otm_radius_client.retry_attempts == 0


def test_otm_requests_carry_contact_user_agent(monkeypatch):
    monkeypatch.setattr(settings, "otm_api_key", "test-key")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, json={"name": "Paris", "country": "France", "lat": 48.85, "lon": 2.35})

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        row = places.resolve_city_center("Paris")
    finally:
        configure_clients(api=None)
    assert row is not None
    assert seen["ua"].startswith("TravelAssistantDemo/1.0")
    assert "contact=" in seen["ua"], "UA 必须带联系方式（免费源礼貌纪律）"


def test_otm_throttle_enforces_min_interval(fake_clock, monkeypatch):
    """fake clock 断言相邻外呼间隔 ≥ min_interval（PR-11 验收口径）。"""
    places._otm_geo_client.reset_runtime_state()  # 清掉此前用例留下的真实时钟车道戳
    monkeypatch.setattr(settings, "otm_api_key", "test-key")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={"name": "x", "country": "y", "lat": 1.0, "lon": 2.0})

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        assert places.resolve_city_center("Paris") is not None
        assert places.resolve_city_center("Lyon") is not None
        assert len(requests) == 2
        # 第二次调用必须预约到 +0.35s 的时间槽（假钟把 sleep 换成时钟推进）
        assert any(s == pytest.approx(0.35, abs=1e-6) for s in fake_clock.sleeps), (
            f"相邻外呼必须间隔 0.35s，实际 sleeps={fake_clock.sleeps}"
        )
    finally:
        configure_clients(api=None)


def test_provider_outage_trips_breaker_and_degrades_pool_visibly(fake_clock, monkeypatch, caplog):
    """供应商连挂 → 熔断开窗有 warning 日志（降级不静默），检索降级为空池且零外呼。

    对应 PR-11 验收「供应商连挂 → 降级链（OTM→联网→LLM 世界知识）事件可见」
    的第一环：OTM 池降级为空后，联网补池与 LLM 世界知识照既有 research 链路
    接手（EvidencePack.gaps 如实记录），本测钉住的是"OTM 这一环的缺席可见"。
    """
    places._otm_radius_client.reset_runtime_state()  # 清掉此前用例留下的真实时钟车道戳
    monkeypatch.setattr(settings, "otm_api_key", "test-key")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        raise httpx.ConnectError("provider down")

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        with caplog.at_level("WARNING", logger="app.common.external_client"):
            # radius 客户端熔断阈值 5：连挂 5 次后开窗
            for i in range(5):
                assert places.search_places_near(48.85 + i, 2.35, city="Paris") == []
            assert "breaker OPEN" in caplog.text, "熔断开窗必须留 warning 日志"
            assert len(requests) == 5, "5 次真实失败后熔断开窗"
            # 窗口内：零外呼、快速降级为空池
            assert places.search_places_near(99.0, 99.0, city="Nowhere") == []
            assert len(requests) == 5, "熔断窗口内不得再打外部"
    finally:
        configure_clients(api=None)


def test_enrich_preserves_order_and_merges_details(monkeypatch):
    """并行 enrich 保序：输出顺序与串行版一致（eval/快照零 diff 的前提）。"""
    monkeypatch.setattr(settings, "otm_api_key", "k")  # 无 key 时 enrich 按纪律早退
    rows = [
        {"xid": f"x{i}", "name": f"spot{i}", "point": {"lat": 48.0 + i, "lon": 2.0}, "rate": 9 - i} for i in range(4)
    ]

    def fake_detail(xid: str) -> dict | None:
        return {"xid": xid, "image": f"img-{xid}"} if xid == "x1" else None

    monkeypatch.setattr(places, "place_detail", fake_detail)
    out = places.enrich_with_details(rows, top=3)
    assert [p["name"] for p in out] == ["spot0", "spot1", "spot2", "spot3"], "顺序必须与输入一致"
    assert out[1]["image"] == "img-x1", "详情字段仍按 xid 对号入座"
    assert "image" not in out[0] and "image" not in out[2], "无详情的行原地保留"


def test_enrich_handles_empty_pool():
    assert places.enrich_with_details([]) == []
