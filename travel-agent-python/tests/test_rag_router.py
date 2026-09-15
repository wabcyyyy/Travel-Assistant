"""P2 查询路由测试：enumerate / lexical / hybrid 三级执行路径。"""

from app.common.config import settings
from app.rag.retriever import (
    HashedEmbeddingProvider,
    HybridRetriever,
    NoopReranker,
    build_poi_document,
    strip_generic_words,
)


class MemoryCollection:
    def __init__(self, provider, items):
        self._provider = provider
        self._items = items

    def query(self, *, vector, limit, where=None):
        def allowed(item):
            return all(item["metadata"].get(key) == value for key, value in (where or {}).items())

        scored = []
        for item in self._items:
            if allowed(item):
                similarity = sum(a * b for a, b in zip(vector, item["embedding"], strict=False))
                scored.append((similarity, item["metadata"]))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(meta, score) for score, meta in scored[:limit]]


def _retriever():
    provider = HashedEmbeddingProvider()
    pois = [
        {
            "id": 1,
            "city": "杭州",
            "category": "attraction",
            "name": "西湖",
            "tags": "自然 拍照",
            "description": "适合老人休闲游览",
            "rating": 4.9,
            "ticket_price": 0,
        },
        {
            "id": 2,
            "city": "杭州",
            "category": "attraction",
            "name": "灵隐寺",
            "tags": "人文 历史",
            "description": "古建筑",
            "rating": 4.8,
            "ticket_price": 45,
        },
        {
            "id": 3,
            "city": "上海",
            "category": "attraction",
            "name": "外滩",
            "tags": "地标",
            "description": "城市景观",
            "rating": 4.8,
            "ticket_price": 0,
        },
    ]
    documents = {str(poi["id"]): {"document": build_poi_document(poi), "metadata": poi} for poi in pois}
    collection = MemoryCollection(
        provider, [{**item, "embedding": provider.embed_query(item["document"])} for item in documents.values()]
    )
    retriever = HybridRetriever(collection, provider, reranker=NoopReranker())
    retriever.set_documents(documents)
    return retriever


def _counting_retriever():
    """带 embed 调用计数的检索器，用于断言轻路径不触发向量化。"""
    retriever = _retriever()
    original = retriever.embedding_provider.embed_query
    counter = {"n": 0}

    def counting(query):
        counter["n"] += 1
        return original(query)

    retriever.embedding_provider.embed_query = counting
    return retriever, counter


def test_strip_generic_words_removes_city_and_category_words():
    assert strip_generic_words("杭州美食", "杭州") == ""
    assert strip_generic_words("杭州 热门景点推荐", "杭州") == ""
    assert strip_generic_words("杭州适合老人的自然景点", "杭州") == "适合老人的自然"


def test_city_only_query_routes_to_rating_enumeration_without_embedding():
    retriever, counter = _counting_retriever()
    rows = retriever.search("杭州", city="杭州", category="attraction", top_k=2)
    assert counter["n"] == 0  # 无意图查询不触发向量化
    assert retriever.last_telemetry["route"] == "enumerate"
    assert retriever.last_telemetry["provider"] == "enumerate"
    assert [row["name"] for row in rows] == ["西湖", "灵隐寺"]  # 评分降序
    assert all(row["_route"] == "enumerate" for row in rows)


def test_enumeration_respects_preferences_before_rating():
    retriever = _retriever()
    rows = retriever.search("杭州", city="杭州", category="attraction", top_k=2, preferences=["人文"])
    assert rows[0]["name"] == "灵隐寺"  # 偏好命中优先于评分


def test_exact_name_query_routes_to_lexical_without_embedding():
    retriever, counter = _counting_retriever()
    rows = retriever.search("灵隐寺", city="杭州", category="attraction", top_k=1)
    assert counter["n"] == 0  # 精确名直查不触发向量化
    assert retriever.last_telemetry["route"] == "lexical"
    assert retriever.last_telemetry["provider"] == "bm25"
    assert rows[0]["name"] == "灵隐寺"
    assert rows[0]["_route"] == "lexical"


def test_intent_query_still_routes_to_hybrid_with_semantic_and_rerank():
    retriever, counter = _counting_retriever()
    retriever.search("杭州适合老人的自然景点", city="杭州", category="attraction", top_k=2, preferences=["自然"])
    assert counter["n"] == 1  # hybrid 保持向量召回
    assert retriever.last_telemetry["route"] == "hybrid"
    assert retriever.last_telemetry["provider"] == "semantic+bm25"


def test_router_can_be_disabled(monkeypatch):
    retriever, counter = _counting_retriever()
    monkeypatch.setattr(settings, "rag_router_enabled", False)
    retriever.search("杭州", city="杭州", category="attraction", top_k=1)
    assert counter["n"] == 1  # 关闭路由后回退完整 hybrid
    assert retriever.last_telemetry["route"] == "hybrid"
