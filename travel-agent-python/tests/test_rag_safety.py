from unittest.mock import patch

from app.agent import poi_repository, tools
from app.rag.retriever import HashedEmbeddingProvider
from app.rag.store import PoIKnowledgeStore


def _store(tmp_path):
    """测试固定用 hashed 向量：不依赖 .env 的语义模型配置，保持离线可跑。"""
    return PoIKnowledgeStore(tmp_path, embedding_provider=HashedEmbeddingProvider())


def _poi(price=0):
    return {
        "id": 1, "city": "杭州", "name": "西湖", "category": "attraction",
        "address": "西湖区", "latitude": 30.24, "longitude": 120.15,
        "ticket_price": price, "duration_min": 120, "open_time": "08:00-18:00",
        "tags": "自然", "rating": 4.9, "description": "适合休闲游览",
        "source": "mysql.poi_knowledge", "source_updated_at": "2026-08-28 10:00:00",
    }


def test_remote_only_poi_is_not_authoritative_candidate():
    local = [_poi()]
    remote = [
        {"name": "西湖", "city": "杭州", "category": "attraction", "ticket_price": 999},
        {"name": "远程未知景点", "city": "杭州", "category": "attraction", "ticket_price": 1},
    ]
    rows = tools._merge_pois(remote, local)
    assert [row["name"] for row in rows] == ["西湖"]
    assert rows[0]["ticket_price"] == 0
    assert rows[0]["_authoritative"] is True


def test_repository_status_distinguishes_unavailable_from_empty(monkeypatch):
    def fail_acquire():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(poi_repository.db_pool, "acquire", fail_acquire)
    assert poi_repository.list_all_pois_with_status() == ([], False)


def test_store_keeps_existing_index_when_source_is_unavailable(tmp_path):
    poi = _poi()
    with patch.object(poi_repository, "list_all_pois_with_status", return_value=([poi], True)):
        first = _store(tmp_path)
        first.ensure_loaded()
        first.ensure_loaded(force=True)
        assert first.index_info["changed_count"] == 0

    with patch.object(poi_repository, "list_all_pois_with_status", return_value=([], False)):
        second = _store(tmp_path)
        second.ensure_loaded()
        assert second.index_info["status"] == "source_unavailable"
        assert second.search("西湖", city="杭州", category="attraction", limit=1)[0]["name"] == "西湖"


def test_store_retries_source_after_recovery(tmp_path):
    poi = _poi()
    status = ([], False)
    with patch.object(poi_repository, "list_all_pois_with_status", side_effect=lambda: status):
        store = _store(tmp_path)
        store.ensure_loaded()
        assert store.index_info["status"] == "source_unavailable"
        status = ([poi], True)
        store.ensure_loaded(force=True)
        assert store.index_info.get("status") != "source_unavailable"
        assert store.index_info["poi_count"] == 1


def test_store_only_updates_changed_and_deleted_pois(tmp_path):
    poi = _poi()
    rows = [poi]
    with patch.object(poi_repository, "list_all_pois_with_status", side_effect=lambda: (rows, True)):
        store = _store(tmp_path)
        store.ensure_loaded()
        rows[0] = _poi(price=50)
        store.ensure_loaded(force=True)
        assert store.index_info["changed_count"] == 1
        rows.clear()
        store.ensure_loaded(force=True)
        assert store.index_info["deleted_count"] == 1
        assert store.search("西湖", city="杭州", category="attraction", limit=1) == []
