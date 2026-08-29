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

    plan = [{
        "day_no": 1,
        "items": [
            {"item_type": "attraction", "poi_name": "故宫"},
            {"item_type": "food", "poi_name": "全聚德", "image": "http://keep"},
            {"item_type": "hotel", "poi_name": "某酒店"},
        ],
    }]
    tools.attach_poi_images(plan, "北京")

    items = plan[0]["items"]
    assert items[0]["image"] == "http://img/故宫"
    assert items[1]["image"] == "http://keep"  # 已有图片不被覆盖
    assert "image" not in items[2]             # 酒店不补图
    assert ("北京", "故宫") in calls
    assert ("北京", "某酒店") not in calls


def test_poi_image_parses_amap_photos(monkeypatch):
    payload = {"pois": [{"photos": [{"title": "t", "url": "http://photo/x.jpg"}]}]}

    def fake_get(*_a, **_k):
        return _FakeResp(payload)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    monkeypatch.setattr(tools.settings, "amap_web_key", "KEY")
    monkeypatch.setattr(tools.settings, "unsplash_access_key", "")
    tools._poi_image_cache.clear()

    assert tools.poi_image("故宫", "北京") == "http://photo/x.jpg"

    # 缓存命中：不应再次请求网络
    hits = []

    def fake_get2(*_a, **_k):
        hits.append(1)
        return _FakeResp(payload)

    monkeypatch.setattr(tools.httpx, "get", fake_get2)
    assert tools.poi_image("故宫", "北京") == "http://photo/x.jpg"
    assert hits == []


def test_poi_image_prefers_unsplash(monkeypatch):
    amap_payload = {"pois": [{"photos": [{"title": "地图位置图", "url": "http://map/x.jpg"}]}]}
    unsplash_payload = {"results": [{"urls": {"regular": "https://images.unsplash.com/abc"}}]}
    responses = [unsplash_payload, amap_payload]

    def fake_get(*_a, **_k):
        return _FakeResp(responses.pop(0))

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    monkeypatch.setattr(tools.settings, "unsplash_access_key", "KEY")
    monkeypatch.setattr(tools.settings, "amap_web_key", "KEY")
    monkeypatch.setattr(tools.settings, "poi_image_wiki", False)
    tools._poi_image_cache.clear()

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
