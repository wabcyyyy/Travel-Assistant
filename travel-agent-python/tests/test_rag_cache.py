"""P2 语义缓存测试：精确/近似两级命中、TTL、LRU、版本失效与安全边界。"""

from app.rag.cache import RetrievalCache, make_cache_key
from app.rag.retriever import HashedEmbeddingProvider


def _key(query, city="杭州", category="attraction", top_k=2, preferences=None, budget=None):
    return make_cache_key(query, city=city, category=category, top_k=top_k,
                          preferences=preferences, budget=budget)


def _provider():
    return HashedEmbeddingProvider()


def _rows():
    return [{"id": 1, "name": "西湖", "city": "杭州", "category": "attraction"}]


def test_exact_key_hit_and_miss():
    cache = RetrievalCache()
    key = _key("西湖")
    assert cache.lookup(key, index_version="v1") is None
    cache.store(key, _rows(), index_version="v1")
    assert cache.lookup(key, index_version="v1") == _rows()
    assert cache.stats()["hits"] == 1
    assert cache.lookup(_key("灵隐寺"), index_version="v1") is None
    assert cache.stats()["misses"] == 2  # 初始查询 + 未缓存键各记一次


def test_semantic_near_duplicate_hit_within_same_signature():
    cache = RetrievalCache(similarity=0.9)
    cache.store(_key("杭州 西湖 景点"), _rows(), embedding_provider=_provider(), index_version="v1")
    # 词序重排的同义改写：哈希 n-gram 词袋相同，cosine=1.0
    hit = cache.lookup(_key("景点 西湖 杭州"), embedding_provider=_provider(), index_version="v1")
    assert hit == _rows()
    assert cache.stats()["semantic_hits"] == 1


def test_different_signature_never_hits():
    cache = RetrievalCache()
    cache.store(_key("西湖"), _rows(), index_version="v1")
    assert cache.lookup(_key("西湖", city="上海"), index_version="v1") is None
    assert cache.lookup(_key("西湖", top_k=5), index_version="v1") is None
    assert cache.lookup(_key("西湖", preferences=["自然"]), index_version="v1") is None


def test_ttl_expiry():
    cache = RetrievalCache(ttl_seconds=0)
    key = _key("西湖")
    cache.store(key, _rows(), index_version="v1")
    assert cache.lookup(key, index_version="v1") is None  # ttl=0 立即过期


def test_index_version_change_invalidates_whole_cache():
    cache = RetrievalCache()
    cache.store(_key("西湖"), _rows(), embedding_provider=_provider(), index_version="v1")
    assert cache.lookup(_key("西湖"), embedding_provider=_provider(), index_version="v2") is None
    assert cache.size == 0  # 旧版本条目整体失效


def test_empty_rows_are_not_stored():
    cache = RetrievalCache()
    cache.store(_key("西湖"), [], index_version="v1")
    assert cache.size == 0


def test_lru_eviction_respects_max_entries():
    cache = RetrievalCache(max_entries=1)
    cache.store(_key("西湖"), _rows(), index_version="v1")
    cache.store(_key("灵隐寺"), [{"id": 2}], index_version="v1")
    assert cache.size == 1
    assert cache.lookup(_key("灵隐寺"), index_version="v1") == [{"id": 2}]
    assert cache.lookup(_key("西湖"), index_version="v1") is None


def test_cached_rows_are_copies_not_shared_references():
    cache = RetrievalCache()
    key = _key("西湖")
    cache.store(key, _rows(), index_version="v1")
    first = cache.lookup(key, index_version="v1")
    first[0]["name"] = "被调用方篡改"
    second = cache.lookup(key, index_version="v1")
    assert second[0]["name"] == "西湖"


def test_store_with_failing_embedding_is_skipped():
    cache = RetrievalCache()

    class BrokenProvider:
        def embed_query(self, _query):
            raise RuntimeError("offline")

    cache.store(_key("西湖"), _rows(), embedding_provider=BrokenProvider(), index_version="v1")
    assert cache.size == 0


# ---------- store 集成 ----------


def _poi(pid=1, name="西湖", lat=30.24, lng=120.15):
    return {
        "id": pid, "city": "杭州", "name": name, "category": "attraction",
        "address": "西湖区", "latitude": lat, "longitude": lng,
        "ticket_price": 0, "duration_min": 120, "open_time": "08:00-18:00",
        "tags": "自然", "rating": 4.9, "description": "适合休闲游览",
        "source": "mysql.poi_knowledge", "source_updated_at": "2026-09-01 10:00:00",
    }


def test_store_level_cache_hits_on_repeat_search(tmp_path, monkeypatch):
    from unittest.mock import patch

    from app.agent import poi_repository
    from app.common.config import settings
    from app.rag.store import PoIKnowledgeStore

    monkeypatch.setattr(settings, "rag_cache_enabled", True)
    # 单测不依赖 sentence-transformers：精排永久降级会把 fallback=True，
    # 导致「降级结果不缓存」把本用例的缓存写入关掉。这里显式关精排。
    monkeypatch.setattr(settings, "rag_rerank_provider", "none")
    with patch.object(poi_repository, "list_all_pois_with_status",
                      return_value=([_poi()], True)):
        store = PoIKnowledgeStore(tmp_path, embedding_provider=_provider())
        first = store.search("西湖", city="杭州", category="attraction", limit=1)
        assert first and first[0]["name"] == "西湖"
        assert store.cache_stats()["misses"] == 1
        second = store.search("西湖", city="杭州", category="attraction", limit=1)
        assert second[0]["name"] == "西湖"
        assert store.cache_stats()["hits"] == 1
