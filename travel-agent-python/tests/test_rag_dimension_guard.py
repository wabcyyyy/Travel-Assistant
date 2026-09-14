"""RAG 向量维度守护测试：换 embedding 模型（维度变化）时集合必须重置而非报错。

背景：provider/模型切换由 payload 版本签名触发全量重建（store._sync）；但
「DB 不可用 → 保留旧索引」的恢复分支不走 _sync，此时旧集合维度与新 provider
的查询向量不符会让检索层直接报错。维度守护（reset_if_dimension_mismatch）
在建立集合句柄时兜底重置，本文件覆盖集合级与 store 级两条路径。
"""

from unittest.mock import patch

from app.agent import poi_repository
from app.rag.retriever import EmbeddingProvider
from app.rag.store import PoIKnowledgeStore
from app.rag.vector_collection import QdrantVectorCollection


class _FixedDimProvider(EmbeddingProvider):
    """固定维度的假 provider：模拟 hashed(256) → 语义模型(512) 的维度切换。"""

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self.provider_name = "fake-semantic"
        self.model_name = f"fake-dim-{dim}"
        self.version = "1"

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return [[0.1] * self._dim for _ in documents]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * self._dim


def _poi() -> dict:
    return {
        "id": 1, "city": "杭州", "name": "西湖", "category": "attraction",
        "address": "西湖区", "latitude": 30.24, "longitude": 120.15,
        "ticket_price": 0.0, "duration_min": 120, "open_time": "08:00-18:00",
        "tags": "自然", "rating": 4.9, "description": "适合休闲游览",
        "source": "mysql.poi_knowledge", "source_updated_at": "2026-08-28 10:00:00",
    }


def test_collection_resets_when_dimension_mismatch(tmp_path):
    path = str(tmp_path / "qdrant")
    small = QdrantVectorCollection(collection_name="poi_knowledge", vector_size=256, path=path)
    small.upsert(ids=["1"], payloads=[{"document": "西湖"}], vectors=[[0.1] * 256])
    assert small.current_vector_size() == 256

    large = QdrantVectorCollection(collection_name="poi_knowledge", vector_size=512, path=path)
    # 构造时不校验（既有行为）：守护由调用方显式触发
    assert large.current_vector_size() == 256
    assert large.reset_if_dimension_mismatch(512) is True
    assert large.current_vector_size() == 512
    assert large.count() == 0, "重置后集合应为空（由同步逻辑重新填充）"
    # 新维度查询可用（重置前 512 维查询在 256 维集合上会直接报错）
    assert large.query(vector=[0.1] * 512, limit=1) == []
    # 维度一致时不重置
    assert large.reset_if_dimension_mismatch(512) is False


def test_store_guards_dimension_change_on_source_unavailable_path(tmp_path):
    rows = [_poi()]
    with patch.object(poi_repository, "list_all_pois_with_status",
                      side_effect=lambda: (rows, True)):
        store = PoIKnowledgeStore(tmp_path, embedding_provider=_FixedDimProvider(256))
        store.ensure_loaded()
        assert store.collection.current_vector_size() == 256
        assert isinstance(store.search("西湖", city="杭州", limit=1), list)

    # DB 不可用 + provider 维度变化（恢复分支不走版本签名重建）：
    # 守护逻辑应重置集合，检索返回空结果而不是抛错/混用错误维度
    with patch.object(poi_repository, "list_all_pois_with_status",
                      side_effect=lambda: ([], False)):
        restored = PoIKnowledgeStore(tmp_path, embedding_provider=_FixedDimProvider(512))
        assert restored.search("西湖", city="杭州", limit=1) == []
        assert restored.collection.current_vector_size() == 512
