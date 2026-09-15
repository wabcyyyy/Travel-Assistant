import app.agent.tools as tools


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_attach_poi_images_skips_hotel_and_keeps_existing(monkeypatch):
    calls = {}

    def fake(name, city):
        calls[(city, name)] = True
        return f"http://img/{name}"

    monkeypatch.setattr(tools, "poi_image", fake)

    plan = [
        {
            "day_no": 1,
            "items": [
                {"item_type": "attraction", "poi_name": "故宫"},
                {"item_type": "food", "poi_name": "全聚德", "image": "http://keep"},
                {"item_type": "hotel", "poi_name": "某酒店"},
            ],
        }
    ]
    tools.attach_poi_images(plan, "北京")

    items = plan[0]["items"]
    assert items[0]["image"] == "http://img/故宫"
    assert items[1]["image"] == "http://keep"  # 已有图片不被覆盖
    assert "image" not in items[2]  # 酒店不补图
    assert ("北京", "故宫") in calls
    assert ("北京", "某酒店") not in calls


def test_poi_image_returns_none_without_external_hit_and_caches(monkeypatch):
    """去高德后：维基/图库都无图即 None（**不再回退高德**），且空结果也进缓存。"""
    calls = []

    def fake_get(*_a, **_k):
        calls.append(1)
        return _FakeResp({})

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    monkeypatch.setattr(tools.settings, "unsplash_access_key", "")
    monkeypatch.setattr(tools.settings, "poi_image_wiki", True)
    tools._poi_image_cache.clear()

    assert tools.poi_image("故宫", "北京") is None
    assert calls, "应至少尝试过维基检索"
    before = len(calls)
    assert tools.poi_image("故宫", "北京") is None
    assert len(calls) == before, "缓存未命中也必须缓存，避免每次开页重放外网链路"


def test_poi_image_prefers_wikipedia_then_unsplash(monkeypatch):
    wiki_payload = {"query": {"pages": {"1": {"thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"}}}}}
    unsplash_payload = {"results": [{"urls": {"regular": "https://images.unsplash.com/abc"}}]}

    monkeypatch.setattr(tools.settings, "poi_image_wiki", True)
    monkeypatch.setattr(tools.settings, "unsplash_access_key", "KEY")
    tools._poi_image_cache.clear()

    def wiki_only(*_a, **_k):
        return _FakeResp(wiki_payload)

    monkeypatch.setattr(tools.httpx, "get", wiki_only)
    assert tools.poi_image("西湖", "杭州") == "https://upload.wikimedia.org/x.jpg"

    tools._poi_image_cache.clear()
    monkeypatch.setattr(tools.settings, "poi_image_wiki", False)
    monkeypatch.setattr(tools.httpx, "get", lambda *_a, **_k: _FakeResp(unsplash_payload))
    assert tools.poi_image("西湖", "杭州") == "https://images.unsplash.com/abc"


def test_unsplash_disabled_returns_none(monkeypatch):
    hits = []

    def fake_get(*_a, **_k):
        hits.append(1)
        raise AssertionError("不应发起请求")

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    monkeypatch.setattr(tools.settings, "unsplash_access_key", "")
    assert tools._unsplash_image("故宫", "北京") is None
    assert hits == []
