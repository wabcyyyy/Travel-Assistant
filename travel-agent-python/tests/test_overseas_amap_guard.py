"""海外目的地禁止走高德，防止国内同名 POI 污染。"""

from app.agent.tools import is_overseas_destination, search_amap_poi, _search_amap_rest
from app.agent.day_stream import _amap_ground


def test_overseas_city_detection():
    assert is_overseas_destination("京都")
    assert is_overseas_destination("东京")
    assert is_overseas_destination("日本京都")
    assert not is_overseas_destination("杭州")
    assert not is_overseas_destination("北京")
    assert not is_overseas_destination("厦门")


def test_amap_rest_skips_overseas():
    assert _search_amap_rest("岚山", "京都") == []
    assert _search_amap_rest("岚山", "京都", category="attraction") == []


def test_amap_ground_skips_overseas(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("amap must not be called for overseas")

    monkeypatch.setattr("app.agent.tools.search_amap_poi", boom)
    item = {"poi_name": "岚山", "item_type": "attraction"}
    cache: dict = {}
    _amap_ground(item, "京都", cache)
    assert item.get("latitude") is None
    assert item.get("longitude") is None


def test_search_amap_overseas_no_china_hits(monkeypatch):
    # 即使 REST 被误调用，overseas 也应短路为空
    monkeypatch.setattr(
        "app.agent.tools._search_amap_rest",
        lambda *a, **k: [{"name": "岚山收费站", "latitude": 30.0, "longitude": 120.0}],
    )
    hits = search_amap_poi("京都", "岚山")
    assert hits == []
