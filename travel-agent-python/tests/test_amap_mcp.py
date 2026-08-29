from app.agent import tools
from app.common.config import settings
from app.integrations import amap_mcp


def test_build_endpoint_adds_server_key_without_logging_or_mutating_url(monkeypatch):
    monkeypatch.setattr(settings, "amap_mcp_url", "https://mcp.amap.com/mcp")
    monkeypatch.setattr(settings, "amap_mcp_key", "secret-key")
    assert amap_mcp.build_endpoint() == "https://mcp.amap.com/mcp?key=secret-key"


def test_normalize_official_poi_payload():
    payload = {
        "pois": [{
            "id": "B0001",
            "name": "西湖",
            "location": "120.149,30.242",
            "address": "杭州市西湖区",
            "type": "风景名胜",
            "photos": [{"url": "https://img.example/x.jpg"}],
        }]
    }
    result = amap_mcp.normalize_pois(payload, category="attraction")
    assert result[0]["id"] == "B0001"
    assert result[0]["longitude"] == 120.149
    assert result[0]["latitude"] == 30.242
    assert result[0]["source"] == "amap-mcp"
    assert result[0]["image"] == "https://img.example/x.jpg"


def test_search_amap_poi_prefers_mcp(monkeypatch):
    monkeypatch.setattr(tools.amap_mcp, "enabled", lambda: True)
    monkeypatch.setattr(
        tools.amap_mcp,
        "search_poi",
        lambda *_args, **_kwargs: {"pois": [{"name": "西湖", "location": "120.149,30.242"}]},
    )
    monkeypatch.setattr(tools, "_search_amap_rest", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("MCP 已返回结果，不应调用旧 REST API")
    ))

    result = tools.search_amap_poi("杭州", "西湖", category="attraction")
    assert result[0]["name"] == "西湖"


def test_search_amap_poi_falls_back_when_mcp_has_no_result(monkeypatch):
    monkeypatch.setattr(tools.amap_mcp, "enabled", lambda: True)
    monkeypatch.setattr(tools.amap_mcp, "search_poi", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tools,
        "_search_amap_rest",
        lambda *_args, **_kwargs: [{"name": "西湖", "source": "amap-rest"}],
    )
    assert tools.search_amap_poi("杭州", "西湖")[0]["source"] == "amap-rest"
