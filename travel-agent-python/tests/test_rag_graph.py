"""P2 轻量 GraphRAG 测试：空间网格近邻、标签相邻、store/tools/registry 接入。"""

from unittest.mock import patch

from app.agent import poi_repository, tools
from app.agent.tool_registry import registry
from app.rag.graph import PoiGraph
from app.rag.retriever import HashedEmbeddingProvider
from app.rag.store import PoIKnowledgeStore


def _meta(pid, name, lat, lng, tags="自然", category="attraction", rating=4.5):
    return {
        "metadata": {
            "id": pid,
            "name": name,
            "city": "上海" if pid == 4 else "杭州",
            "category": category,
            "latitude": lat,
            "longitude": lng,
            "tags": tags,
            "rating": rating,
            "address": f"{name}地址",
            "ticket_price": 0,
        }
    }


def _documents():
    return {
        "1": _meta(1, "西湖", 30.2400, 120.1500, tags="自然 拍照", rating=4.9),
        "2": _meta(2, "苏堤", 30.2410, 120.1510, tags="自然", rating=4.7),  # ~130m
        "3": _meta(3, "灵隐寺", 30.2410, 120.1530, tags="人文 历史", rating=4.8),  # ~280m
        "4": _meta(4, "外滩", 31.2400, 121.4900, tags="地标", rating=4.8),  # 上海，不同城
        "5": _meta(5, "无坐标POI", 0.0, 0.0, tags="自然", rating=4.0),  # 缺坐标
    }


def test_neighbors_are_same_city_distance_ordered_and_exclude_self():
    graph = PoiGraph()
    graph.rebuild(_documents())
    rows = graph.neighbors(1, limit=5)
    names = [row["name"] for row in rows]
    assert names == ["苏堤", "灵隐寺"]  # 近邻升序；跨城与缺坐标不进空间层
    assert all(row["_distance_m"] > 0 for row in rows)
    assert graph.neighbors(5) == []  # 缺坐标 POI 无近邻


def test_radius_filters_far_neighbors():
    graph = PoiGraph()
    graph.rebuild(_documents())
    assert [row["name"] for row in graph.neighbors(1, radius_m=200)] == ["苏堤"]
    assert len(graph.neighbors(1, radius_m=500)) == 2


def test_nearby_by_coords_with_category_filter_and_anchor_exclude():
    graph = PoiGraph()
    graph.rebuild(_documents())
    # 原始坐标语义：包含该坐标点上的 POI（西湖本身距离 0）
    rows = graph.nearby("杭州", 30.2400, 120.1500, limit=5)
    assert [row["name"] for row in rows] == ["西湖", "苏堤", "灵隐寺"]
    # 名称解析锚点后应排除自身
    rows = graph.nearby("杭州", 30.2400, 120.1500, limit=5, exclude=1)
    assert [row["name"] for row in rows] == ["苏堤", "灵隐寺"]
    assert graph.nearby("杭州", 30.2400, 120.1500, limit=5, exclude=1, category="food") == []


def test_same_tag_prefers_shared_tag_count():
    graph = PoiGraph()
    docs = _documents()
    docs["2"]["metadata"]["tags"] = "自然 拍照 休闲"  # 与西湖共享 2 个标签
    graph.rebuild(docs)
    rows = graph.same_tag(1)
    assert rows[0]["name"] == "苏堤"
    assert rows[0]["_shared_tags"] == 2


def test_stats_counts_nodes_and_grid():
    graph = PoiGraph()
    stats = graph.rebuild(_documents())
    assert stats["nodes"] == 5
    assert stats["cities"] == 2  # 杭州 + 上海（外滩在标签层）
    assert stats["grid_cells"] >= 2


# ---------- store / tools / registry 接入 ----------


def _poi(pid=1, name="西湖", lat=30.24, lng=120.15, tags="自然"):
    return {
        "id": pid,
        "city": "杭州",
        "name": name,
        "category": "attraction",
        "address": "西湖区",
        "latitude": lat,
        "longitude": lng,
        "ticket_price": 0,
        "duration_min": 120,
        "open_time": "08:00-18:00",
        "tags": tags,
        "rating": 4.9,
        "description": "适合休闲游览",
        "source": "mysql.poi_knowledge",
        "source_updated_at": "2026-09-01 10:00:00",
    }


def _store(tmp_path):
    pois = [
        _poi(1, "西湖", 30.2400, 120.1500),
        _poi(2, "苏堤", 30.2410, 120.1510),
        _poi(3, "灵隐寺", 30.2410, 120.1530, tags="人文"),
    ]
    with patch.object(poi_repository, "list_all_pois_with_status", return_value=(pois, True)):
        store = PoIKnowledgeStore(tmp_path, embedding_provider=HashedEmbeddingProvider())
        store.ensure_loaded()
    return store


def test_store_nearby_and_graph_stats(tmp_path):
    store = _store(tmp_path)
    rows = store.nearby("杭州", 30.2400, 120.1500, limit=5, exclude=1)
    assert [row["name"] for row in rows] == ["苏堤", "灵隐寺"]
    stats = store.graph_stats()
    assert stats["nodes"] == 3
    assert store.neighbors(1, radius_m=200)[0]["name"] == "苏堤"
    assert store.same_tag(1)[0]["name"] == "苏堤"


def test_find_nearby_pois_resolves_coords_by_name(tmp_path):
    store = _store(tmp_path)
    with patch.object(tools, "poi_store", store), patch.object(poi_repository, "get_poi", return_value=None):
        rows = tools.find_nearby_pois("杭州", name="西湖", limit=5)
    # 锚点（西湖自身）被排除
    assert [row["name"] for row in rows] == ["苏堤", "灵隐寺"]


def test_find_nearby_pois_with_coords_still_excludes_anchor(tmp_path):
    """带坐标 + 名称时：坐标用于近邻查询，名称用于排除锚点自身。"""
    store = _store(tmp_path)
    monkeypatch_store = patch.object(tools, "poi_store", store)
    with monkeypatch_store, patch.object(poi_repository, "get_poi", return_value=None):
        rows = tools.find_nearby_pois("杭州", name="西湖", latitude=30.2400, longitude=120.1500, limit=5)
    assert [row["name"] for row in rows] == ["苏堤", "灵隐寺"]


def test_find_nearby_pois_without_coords_returns_empty(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(tools, "poi_store", store)

    def fake_get_poi(city, name):
        if name == "无坐标POI":
            return {"id": 5, "name": name, "city": city, "latitude": 0.0, "longitude": 0.0}
        return None

    monkeypatch.setattr(poi_repository, "get_poi", fake_get_poi)
    # 解析不到坐标（名称检索也为空）：返回空而不是伪造“附近”。
    with patch.object(store, "search", return_value=[]):
        assert tools.find_nearby_pois("杭州", name="未知地点") == []
    # 解析到的 POI 坐标是 0/0（缺失）：同样返回空。
    assert tools.find_nearby_pois("杭州", name="无坐标POI") == []


def test_find_nearby_pois_rejects_unrelated_amap_fuzzy_hits(tmp_path, monkeypatch):
    """乱名不应被高德模糊召回锚到任意酒店（市中心附近）。"""
    store = _store(tmp_path)
    monkeypatch.setattr(tools, "poi_store", store)
    monkeypatch.setattr(poi_repository, "get_poi", lambda *a, **k: None)
    monkeypatch.setattr(
        tools,
        "search_local_poi",
        lambda *a, **k: [
            {"id": 99, "name": "湖滨大酒店", "latitude": 30.25, "longitude": 120.16},
        ],
    )
    with patch.object(store, "search", return_value=[]):
        assert tools.find_nearby_pois("杭州", name="不存在的景点XYZ123") == []


def test_anchor_name_similar_gates_fuzzy_matches():
    assert tools.anchor_name_similar("西湖", "杭州西湖")
    assert tools.anchor_name_similar("良渚古城", "良渚古城遗址公园")
    assert not tools.anchor_name_similar("不存在的景点XYZ123", "湖滨大酒店")
    assert not tools.anchor_name_similar("asdfghjkl", "灵隐寺")


def test_registry_exposes_find_nearby_pois_schema():
    schemas = {spec["name"] for spec in registry.public_specs()}
    assert "find_nearby_pois" in schemas
    schema = registry.get("find_nearby_pois").function_schema()
    assert schema["function"]["parameters"]["required"] == ["city"]


# ---------- HTTP 端点与指标 ----------


def test_poi_nearby_endpoint_returns_items(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import agent
    from main import app

    monkeypatch.setattr(
        agent,
        "find_nearby_pois",
        lambda *_args, **_kwargs: [
            {"name": "苏堤", "category": "attraction", "rating": 4.7, "address": "杭州", "_distance_m": 130},
        ],
    )
    with TestClient(app) as client:
        response = client.post("/api/agent/v1/poi-nearby", json={"city": "杭州", "name": "西湖", "limit": 5})
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 200
    assert body["data"]["items"][0]["name"] == "苏堤"
    assert body["data"]["items"][0]["_distance_m"] == 130


def test_poi_nearby_endpoint_degrades_to_empty_on_error(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import agent
    from main import app

    def _fail(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(agent, "find_nearby_pois", _fail)
    with TestClient(app) as client:
        response = client.post("/api/agent/v1/poi-nearby", json={"city": "杭州"})
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_metrics_counts_cache_hits_and_routes():
    from app.agent.observability import metrics

    metrics.reset()
    trace = {
        "run_id": "run-cache",
        "events": [
            {"kind": "retrieval", "name": "cache_hit", "metadata": {}},
            {"kind": "retrieval", "name": "poi.hybrid_search", "metadata": {"route": "enumerate"}},
            {"kind": "retrieval", "name": "poi.hybrid_search", "metadata": {"route": "hybrid"}},
        ],
    }
    metrics.record(trace, success=True)
    snapshot = metrics.snapshot()
    assert snapshot["retrieval_cache_hits"] == 1
    assert snapshot["route_enumerate"] == 1
    assert snapshot["route_hybrid"] == 1
    assert snapshot["route_lexical"] == 0
