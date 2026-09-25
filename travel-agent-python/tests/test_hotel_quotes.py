"""L15 酒店真价单测：名称匹配三分支、观测价切换、窗口校验、回退。

验收对应（SPEC L15）：
- 名称匹配三分支：同名命中 / 近名命中 / 不匹配回退（**不硬凑**）；
- 观测价优先 + price_fact（observed 票）+ reason 口径 + deep_link；
- 窗口对不上不用观测价（价格属于那个窗口）；
- 无 token / 上游挂 → 估价链路原样（零变化）。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.agent.data import hotel_prices
from app.agent.editing.chat_draft import hotel as hotel_module
from app.agent.editing.chat_draft.hotel_intent import HotelIntent
from app.agent.tools import hotel_quotes
from app.common.config import settings
from app.common.http_client import configure_clients
from app.schemas.trip import ChatTurnRequest

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "hotellook_cache.json").read_text(encoding="utf-8"))
CHECK_IN, CHECK_OUT = "2026-11-07", "2026-11-14"


def _mock(payload, status: int = 200) -> None:
    handler = lambda request: httpx.Response(status, json=payload)  # noqa: E731
    configure_clients(api=httpx.Client(transport=httpx.MockTransport(handler)))


def _rows() -> list[dict]:
    """Hotellook 观测行（经 data 层整形，带 deep_link）。"""
    return hotel_prices.fetch_hotel_prices("Barcelona", CHECK_IN, CHECK_OUT) or []


# ---- 名称匹配三分支 -----------------------------------------------------------


def test_same_hotel_exact_after_normalization():
    """分支一：同名命中（归一后相等，含括号注记/大小写/分隔符差异）。"""
    assert hotel_quotes.same_hotel("Sample Hotel Diagonal", "sample hotel  diagonal")
    assert hotel_quotes.same_hotel("Hotel Sakura（新宿店）", "Hotel Sakura")
    assert hotel_quotes.same_hotel("Sakura Hotel", "Hotel Sakura"), "词序不同但字符集一致 → same_entity 命中"


def test_same_hotel_near_name_hits():
    """分支二：近名命中（同一家带后缀/分店修饰，且较短名足够长）。"""
    assert hotel_quotes.same_hotel("Sample Hotel Diagonal Barcelona", "Sample Hotel Diagonal")


def test_same_hotel_rejects_generic_and_short():
    """分支三：不匹配回退——通用词/短名/字符集合相近但实为两家的不得判同一家。"""
    assert not hotel_quotes.same_hotel("Hotel", "Grand Hotel Plaza"), "短通用名必须挡住"
    assert not hotel_quotes.same_hotel("Inn", "Inn on the Park")
    assert not hotel_quotes.same_hotel("东京柏悦酒店", "Park Hyatt Tokyo"), "跨语言名不硬凑"
    assert not hotel_quotes.same_hotel("", "Some Hotel")
    assert not hotel_quotes.same_hotel("Hotel A", None)
    # 回归反例：字符集合几乎相同（旧 same_entity 口径会判 0.857 → 同一家）
    assert not hotel_quotes.same_hotel("Sample Hotel Diagonal", "Hostel Sample Gothic")


# ---- 合并 ---------------------------------------------------------------------


def test_merge_upgrades_matched_row_and_appends_unmatched(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "tp-token")
    _mock(FIXTURE)
    try:
        rows = _rows()
    finally:
        configure_clients(api=None)
    assert len(rows) == 2, "fixture 第 3 行缺 hotelName，必须整行丢弃"

    pool = [
        {"id": 1, "name": "Sample Hotel Diagonal", "ticket_price": 500, "address": "Diagonal 1"},
        {"id": 2, "name": "完全不相关的酒店", "ticket_price": 200},
    ]
    monkeypatch.setattr(hotel_prices, "fetch_hotel_prices", lambda *a, **k: rows)
    merged = hotel_quotes.merge_observed_prices(pool, "Barcelona", check_in=CHECK_IN, check_out=CHECK_OUT)

    assert merged[0]["name"] == "Sample Hotel Diagonal"
    assert merged[0]["observed_nightly_price"] == 96.4, "命中行补上观测价"
    assert merged[0]["address"] == "Diagonal 1", "命中行保留原有坐标/地址等身份字段"
    assert merged[1]["name"] == "完全不相关的酒店"
    assert "observed_nightly_price" not in merged[1], "不匹配的池行保持估价，不硬凑"
    names = [row["name"] for row in merged]
    assert "Hostel Sample Gothic" in names, "未匹配的 Hotellook 行作为新候选追加"
    assert "Sample Hotel Diagonal" not in names[2:], "已并入的行不重复追加"


def test_merge_without_window_or_token_is_noop(monkeypatch):
    pool = [{"id": 1, "name": "Sample Hotel Diagonal", "ticket_price": 500}]

    def _forbidden(*args, **kwargs):
        raise AssertionError("不得外呼")

    monkeypatch.setattr(hotel_prices, "fetch_hotel_prices", _forbidden)
    assert hotel_quotes.merge_observed_prices(pool, "Barcelona", check_in=None, check_out=None) == pool
    monkeypatch.setattr(settings, "travelpayouts_token", "")
    assert hotel_quotes.merge_observed_prices(pool, "Barcelona", check_in=CHECK_IN, check_out=CHECK_OUT) == pool


def test_observed_price_requires_matching_window():
    hotel = {
        "name": "X",
        "observed_nightly_price": 96.4,
        "observed_check_in": CHECK_IN,
        "observed_check_out": CHECK_OUT,
    }
    assert hotel_quotes.observed_price(hotel, check_in=CHECK_IN, check_out=CHECK_OUT) is not None
    assert hotel_quotes.observed_price(hotel, check_in="2026-11-08", check_out=CHECK_OUT) is None, "起始日不符即弃"
    assert hotel_quotes.observed_price(hotel, check_in=CHECK_IN, check_out="2026-11-15") is None, "晚数不符即弃"
    assert hotel_quotes.observed_price(hotel, check_in=None, check_out=None) is None


def test_deep_link_carries_marker_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "travelpayouts_token", "tp-token")
    monkeypatch.setattr(settings, "travelpayouts_marker", "")
    _mock(FIXTURE)
    try:
        bare = (_rows() or [])[0]["deep_link"]
    finally:
        configure_clients(api=None)
    assert bare.startswith("https://search.hotellook.com/hotels?")
    assert "marker=" not in bare, "未配 marker 即裸链"

    monkeypatch.setattr(settings, "travelpayouts_marker", "aff-42")
    hotel_prices._hotel_client.clear_cache()
    _mock(FIXTURE)
    try:
        tagged = (_rows() or [])[0]["deep_link"]
    finally:
        configure_clients(api=None)
    assert "marker=aff-42" in tagged


def test_stars_description_feeds_existing_tier_keywords():
    assert hotel_quotes._stars_description(5) == "五星级酒店"
    assert hotel_quotes._stars_description(4) == "4 星级酒店"
    assert hotel_quotes._stars_description(None) is None
    assert hotel_quotes._stars_description(0) is None


# ---- _hotel_options 价格源 ----------------------------------------------------


def _request(**overrides) -> ChatTurnRequest:
    payload = {
        "city": "Barcelona",
        "days": 3,
        "persons": 2,
        "start_date": "2026-11-07",
        "message": "换个便宜点的酒店",
        "plans": [{"day_no": 1, "items": [{"item_type": "hotel", "poi_name": "旧酒店", "cost": 500}]}],
    }
    payload.update(overrides)
    return ChatTurnRequest(**payload)


def _intent(**overrides) -> HotelIntent:
    payload = {
        "action": "cheaper",
        "target_tier": "舒适型",
        "base_tier": "舒适型",
        "requested_nights": 2,
        "requested_day_nos": (),
    }
    payload.update(overrides)
    return HotelIntent(**payload)


def test_hotel_options_uses_observed_price_and_emits_evidence(monkeypatch):
    hotel = {
        "id": 7,
        "name": "Sample Hotel Diagonal",
        "ticket_price": 500,
        "description": "舒适型酒店",
        "observed_nightly_price": 96.4,
        "observed_currency": "usd",
        "observed_check_in": "2026-11-07",
        "observed_check_out": "2026-11-09",
        "observed_at": "2026-09-25T10:00:00+08:00",
        "observed_expires_at": "2026-09-26T10:00:00+08:00",
        "observed_deep_link": "https://search.hotellook.com/hotels?location=Barcelona",
    }
    monkeypatch.setattr(hotel_module.hotel_quotes, "merge_observed_prices", lambda hotels, city, **kw: [hotel])
    options = hotel_module._hotel_options(_request(), [hotel], _intent())
    assert options, "观测价候选必须能出卡"
    option = options[0]
    assert option.base_price == pytest.approx(96.4), "用观测 nightly 价而非估价 500"
    assert option.season_factor == pytest.approx(1.0), "观测价已含实际日期，不再叠季节系数"
    assert option.price_fact is not None
    assert option.price_fact.value_kind == "observed"
    assert option.price_fact.provider == "hotellook"
    assert option.price_fact.source_url == hotel["observed_deep_link"]
    assert "观测价" in option.reason and "2026-11-07" in option.reason, "reason 注明价格口径与窗口"
    assert option.room_types[0].nightly_breakdown[0]["season_factor"] == pytest.approx(1.0)


def test_hotel_options_falls_back_to_estimate_when_window_mismatches(monkeypatch):
    hotel = {
        "id": 8,
        "name": "Estimate Only Hotel",
        "ticket_price": 500,
        "description": "舒适型酒店",
        "observed_nightly_price": 96.4,
        "observed_check_in": "2026-12-01",
        "observed_check_out": "2026-12-03",
    }
    monkeypatch.setattr(hotel_module.hotel_quotes, "merge_observed_prices", lambda hotels, city, **kw: [hotel])
    options = hotel_module._hotel_options(_request(), [hotel], _intent())
    assert options
    assert options[0].price_fact is None, "窗口不符不得挂 observed 票"
    assert options[0].base_price == pytest.approx(500), "回落到估价"
    assert options[0].season_factor != 1.0 or options[0].reason == "舒适型酒店"


def test_hotel_options_without_observed_keeps_estimate_path(monkeypatch):
    hotel = {"id": 9, "name": "Plain Hotel", "ticket_price": 300, "description": "舒适型酒店"}
    monkeypatch.setattr(hotel_module.hotel_quotes, "merge_observed_prices", lambda hotels, city, **kw: [hotel])
    options = hotel_module._hotel_options(_request(), [hotel], _intent())
    assert options
    assert options[0].base_price == pytest.approx(300)
    assert options[0].price_fact is None
    assert options[0].reason == "舒适型酒店", "估价链路的 reason 口径不变"


def test_observed_window_derivation():
    assert hotel_module._observed_window(date(2026, 11, 7), [1, 2], 2) == ("2026-11-07", "2026-11-09")
    assert hotel_module._observed_window(date(2026, 11, 7), [3], 1) == ("2026-11-09", "2026-11-10")
    assert hotel_module._observed_window(None, [1], 2) == (None, None), "无日期不猜窗口"
    assert hotel_module._observed_window(date(2026, 11, 7), [], 2) == (None, None)
