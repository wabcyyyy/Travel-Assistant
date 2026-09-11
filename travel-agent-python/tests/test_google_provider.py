"""Google 提供商（国外目的地兜底）测试：provider chain 高德→Google。"""

from app.agent import day_stream, tools
from app.agent.route_service import RouteService, clear_route_cache
from app.common.config import settings
from app.integrations import google_maps


def _google_payload():
    return {"places": [
        {"id": "ChIJxyz", "displayName": {"text": "埃菲尔铁塔"},
         "formattedAddress": "Champ de Mars, 75007 Paris",
         "location": {"latitude": 48.8584, "longitude": 2.2945},
         "rating": 4.6,
         "editorialSummary": {"text": "巴黎地标铁塔。"}},
    ]}


def test_google_search_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    assert google_maps.search_pois("埃菲尔铁塔", "巴黎") == []


def test_normalize_google_payload():
    pois = google_maps.normalize_pois(_google_payload(), category="attraction")
    assert len(pois) == 1
    poi = pois[0]
    assert poi["name"] == "埃菲尔铁塔"
    assert poi["source"] == "google.places"
    assert poi["latitude"] == 48.8584 and poi["longitude"] == 2.2945
    assert poi["category"] == "attraction"
    assert poi["id"].startswith("google:")


def test_normalize_nominatim_uses_short_name_not_full_address():
    rows = [{
        "name": "艾菲爾鐵塔",
        "display_name": "艾菲爾鐵塔, 5, Avenue Anatole France, 第七区, 巴黎, 法国",
        "lat": "48.85826",
        "lon": "2.294501",
        "osm_id": 123,
    }]
    pois = google_maps.normalize_nominatim(rows, category="attraction")
    assert pois[0]["name"] == "艾菲爾鐵塔"
    assert "Avenue Anatole" in pois[0]["address"]


def test_search_amap_poi_falls_back_to_google_when_amap_empty(monkeypatch):
    """高德（仅中国）无结果 → provider chain 自动切 Google Places。"""
    monkeypatch.setattr(settings, "amap_mcp_enabled", False)
    monkeypatch.setattr(settings, "amap_web_key", "")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")
    monkeypatch.setattr(google_maps, "search_pois",
                        lambda *a, **k: google_maps.normalize_pois(_google_payload(), category="attraction"))
    hits = tools.search_amap_poi("巴黎", "埃菲尔铁塔", category="attraction")
    assert hits and hits[0]["name"] == "埃菲尔铁塔"
    assert hits[0]["source"] == "google.places"


def test_search_amap_poi_keeps_amap_hits_without_google(monkeypatch):
    """国内命中高德时 Google 不介入（google 未配置 key）。"""
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    monkeypatch.setattr(settings, "amap_mcp_enabled", True)
    google_calls = {"n": 0}

    def fake_search_poi(keywords, city=None, **kwargs):
        return {"pois": [{"name": "西湖", "location": "120.15,30.24"}]}

    def fake_normalize(payload, category=None):
        return [{"id": "amap:1", "name": "西湖", "category": category or "attraction",
                 "latitude": 30.24, "longitude": 120.15, "source": "amap-mcp"}]

    def fake_google(*a, **k):
        google_calls["n"] += 1
        return []

    import app.integrations.amap_mcp as amap_mcp
    monkeypatch.setattr(amap_mcp, "search_poi", fake_search_poi)
    monkeypatch.setattr(amap_mcp, "normalize_pois", fake_normalize)
    monkeypatch.setattr(google_maps, "search_pois", fake_google)

    hits = tools.search_amap_poi("杭州", "西湖", category="attraction")
    assert hits and hits[0]["source"] == "amap-mcp"
    assert google_calls["n"] == 0  # 高德命中即返回，不触发 Google 兜底


def test_amap_ground_lands_foreign_coords_via_google(monkeypatch):
    """国外地点生成后落坐标：_amap_ground 经高德空 → Google 拿到真实坐标。"""
    monkeypatch.setattr(settings, "amap_mcp_enabled", False)
    monkeypatch.setattr(settings, "amap_web_key", "")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")
    monkeypatch.setattr(google_maps, "search_pois",
                        lambda *a, **k: google_maps.normalize_pois(_google_payload(), category="attraction"))

    item = {"item_type": "attraction", "poi_name": "埃菲尔铁塔", "cost": 25}
    day_stream._amap_ground(item, "巴黎", {})
    assert item.get("latitude") == 48.8584
    assert item.get("longitude") == 2.2945
    assert item.get("address") == "Champ de Mars, 75007 Paris"


def test_route_falls_back_to_google(monkeypatch):
    """高德路线失败 → Google Routes 兜底（source=google）。"""
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")
    monkeypatch.setattr(google_maps, "compute_route",
                        lambda *a, **k: {"distance_m": 1200, "duration_min": 18})
    clear_route_cache()
    service = RouteService(fetcher=lambda *a, **k: None)
    first = {"poi_name": "A", "latitude": 48.85, "longitude": 2.29}
    second = {"poi_name": "B", "latitude": 48.86, "longitude": 2.30}
    result = service.get_route(first, second, mode="walking")
    assert result is not None
    assert result["source"] == "google"
    assert result["duration_min"] == 18
    assert result["degraded"] is False


def test_route_without_google_key_uses_coordinate_estimate(monkeypatch):
    """未配置 Google key → 保持原坐标估算降级（source=coordinate-estimate）。"""
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    clear_route_cache()
    service = RouteService(fetcher=lambda *a, **k: None)
    first = {"poi_name": "A", "latitude": 48.85, "longitude": 2.29}
    second = {"poi_name": "B", "latitude": 48.86, "longitude": 2.30}
    result = service.get_route(first, second, mode="walking")
    assert result["source"] == "coordinate-estimate"
    assert result["degraded"] is True


def test_search_amap_poi_falls_back_to_nominatim_when_google_unavailable(monkeypatch):
    """无 Google key（未绑卡）→ 高德空后自动切 OSM Nominatim 免 key 兜底。"""
    monkeypatch.setattr(settings, "amap_mcp_enabled", False)
    monkeypatch.setattr(settings, "amap_web_key", "")
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    monkeypatch.setattr(settings, "nominatim_enabled", True)
    monkeypatch.setattr(google_maps, "search_pois", lambda *a, **k: [])
    monkeypatch.setattr(google_maps, "search_pois_nominatim",
                        lambda *a, **k: google_maps.normalize_nominatim(
                            [{"lat": "48.8584", "lon": "2.2945",
                              "display_name": "Eiffel Tower, Champ de Mars, 75007 Paris, France"}],
                            category="attraction"))
    hits = tools.search_amap_poi("巴黎", "埃菲尔铁塔", category="attraction")
    assert hits and hits[0]["name"] == "Eiffel Tower"
    assert hits[0]["source"] == "nominatim"
    assert hits[0]["latitude"] == 48.8584


def test_nominatim_normalize_and_failure(monkeypatch):
    """Nominatim 契约归一化；检索失败返回空列表（上层如实降级）。"""
    rows = [{"osm_id": 123, "lat": "48.8584", "lon": "2.2945",
             "display_name": "埃菲尔铁塔, 巴黎, 法国", "name": "埃菲尔铁塔"}]
    pois = google_maps.normalize_nominatim(rows, category="attraction")
    assert pois[0]["source"] == "nominatim"
    assert pois[0]["id"].startswith("nominatim:")
    assert pois[0]["latitude"] == 48.8584
    assert pois[0]["name"] == "埃菲尔铁塔"

    def boom(*_a, **_k):
        raise RuntimeError("nominatim down")

    monkeypatch.setattr(google_maps, "search_nominatim", boom)
    assert google_maps.search_pois_nominatim("埃菲尔铁塔", "巴黎") == []
