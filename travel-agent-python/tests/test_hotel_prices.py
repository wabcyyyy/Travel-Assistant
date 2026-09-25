"""hotel_prices 单测（L12）：无 key 零外呼 / 行容错 / token 泄漏面收口。

token 走 query 参数是 Hotellook 官方示例口径——本层兜不住 URL 里的密钥，
但必须兜住两件事：token 不进缓存键（失败日志打键）、异常消息进日志前被
`external_client._redact_secrets` 脱敏。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.agent.data import hotel_prices
from app.common.config import settings
from app.common.http_client import configure_clients

pytest_plugins = ["_fake_clock"]

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "hotellook_cache.json").read_text(encoding="utf-8"))


def test_no_token_means_zero_calls(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json=FIXTURE)

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        assert hotel_prices.fetch_hotel_prices("Barcelona", "2026-11-01", "2026-11-08") is None
        assert requests == [], "无 token 必须零外呼"
    finally:
        configure_clients(api=None)


def test_fetch_returns_price_rows_and_drops_incomplete(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "tp-token-abc")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["location"] == "Barcelona"
        assert request.url.params["checkIn"] == "2026-11-01"
        return httpx.Response(200, json=FIXTURE)

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        rows = hotel_prices.fetch_hotel_prices("Barcelona", "2026-11-01", "2026-11-08", currency="usd", limit=5)
    finally:
        configure_clients(api=None)
    assert rows is not None and len(rows) == 2, "fixture 第 3 行缺 hotelName，必须整行丢弃"
    assert rows[0]["hotelId"] == 271200482 and rows[0]["priceAvg"] == 96.4
    assert rows[1]["hotelName"] == "Hostel Sample Gothic"


def test_token_never_reaches_logs_on_http_error(fake_clock, monkeypatch, caplog):
    """token 在 URL query 里（官方口径）：HTTP 异常进日志前必须脱敏。"""
    monkeypatch.setattr(settings, "travelpayouts_token", "tp-secret-token-42")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        with caplog.at_level("WARNING", logger="app.common.external_client"):
            assert hotel_prices.fetch_hotel_prices("Barcelona", "2026-11-01", "2026-11-08") is None
    finally:
        configure_clients(api=None)
    assert "tp-secret-token-42" not in caplog.text, "token 不得泄漏进日志"
    assert "token=<redacted>" in caplog.text, "脱敏后仍保留参数名，便于排障"


def test_non_list_envelope_degrades_to_none(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "tp-token-abc")
    configure_clients(
        api=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"oops": 1})))
    )
    try:
        assert hotel_prices.fetch_hotel_prices("Barcelona", "2026-11-01", "2026-11-08") is None
    finally:
        configure_clients(api=None)


def test_hotel_prices_enabled_reflects_token(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "")
    assert hotel_prices.hotel_prices_enabled() is False
