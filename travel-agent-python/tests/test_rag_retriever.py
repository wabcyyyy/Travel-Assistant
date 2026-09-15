import sys
import types

from app.common.config import settings
from app.rag.retriever import (
    HashedEmbeddingProvider,
    HybridRetriever,
    NoopReranker,
    build_poi_document,
    create_embedding_provider,
)


class MemoryCollection:
    """中性向量集合协议的内存实现（payload + cosine 相似度语义）。"""

    def __init__(self, provider, items):
        self._provider = provider
        self._items = items

    def query(self, *, vector, limit, where=None):
        def allowed(item):
            return all(item["metadata"].get(key) == value for key, value in (where or {}).items())

        query = vector
        scored = []
        for item in self._items:
            if allowed(item):
                similarity = sum(a * b for a, b in zip(query, item["embedding"], strict=False))
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
    # 显式注入 NoopReranker：测试不依赖 .env 的精排配置，避免加载真实模型。
    retriever = HybridRetriever(collection, provider, reranker=NoopReranker())
    retriever.set_documents(documents)
    return retriever


def test_hybrid_retriever_fuses_exact_name_and_semantic_results_with_hard_filters():
    retriever = _retriever()
    rows = retriever.search(
        "杭州西湖适合老人自然景点", city="杭州", category="attraction", top_k=2, preferences=["自然"]
    )
    assert [row["name"] for row in rows] == ["西湖", "灵隐寺"]
    assert all(row["city"] == "杭州" and row["category"] == "attraction" for row in rows)
    assert rows[0]["_authoritative"] is True
    assert retriever.last_telemetry["provider"] == "semantic+bm25"
    assert retriever.last_telemetry["candidate_count"] == 2


def test_hybrid_retriever_keeps_lexical_results_when_semantic_provider_fails():
    retriever = _retriever()
    retriever.embedding_provider.embed_query = lambda _query: (_ for _ in ()).throw(RuntimeError("offline"))
    # P2 查询路由后，"西湖" 这类精确名会走 lexical 直查而不触发语义召回；
    # 这里用有具体意图的查询保持在 hybrid 路径上，验证语义失败时词法兜底。
    rows = retriever.search("古建筑寺庙", city="杭州", category="attraction", top_k=1)
    assert rows[0]["name"] == "灵隐寺"
    assert retriever.last_telemetry["fallback"] is True


# ---- 语义模型供给：cache_dir 透传与响亮降级 ----


def test_semantic_provider_receives_configured_cache_dir(monkeypatch):
    """模型缓存目录必须传给 sentence-transformers，且保持 local_files_only 离线约定。"""
    captured: dict = {}

    class _FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            captured["model_name"] = model_name
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer)
    )
    provider = create_embedding_provider("semantic", "BAAI/bge-small-zh-v1.5")
    assert captured["model_name"] == "BAAI/bge-small-zh-v1.5"
    assert captured["cache_folder"] == settings.rag_model_cache_dir
    assert captured["model_kwargs"] == {"local_files_only": True}
    assert provider.provider_name == "sentence-transformers"
    assert provider.model_name == "BAAI/bge-small-zh-v1.5"


def test_semantic_provider_falls_back_loudly_when_model_unavailable(monkeypatch):
    """模型缺失时必须降级为 hashed 且标 fallback=True（供启动告警/遥测识别），不抛错。"""

    class _BoomSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            raise OSError("model not found in local cache")

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_BoomSentenceTransformer)
    )
    provider = create_embedding_provider("semantic", "BAAI/bge-small-zh-v1.5")
    assert provider.provider_name == "hashed"
    assert getattr(provider, "fallback", False) is True
