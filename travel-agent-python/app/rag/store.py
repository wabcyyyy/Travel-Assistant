"""POI 权威知识库到 Chroma 的同步与统一混合检索适配层。"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from app.agent import poi_repository
from app.common.config import BASE_DIR, settings
from app.rag.cache import RetrievalCache, make_cache_key
from app.rag.graph import PoiGraph
from app.rag.retriever import (
    EmbeddingProvider,
    HybridRetriever,
    build_poi_document,
    create_embedding_provider,
)

logger = logging.getLogger(__name__)
_DATA_DIR = BASE_DIR / "data"
_COLLECTION_NAME = "poi_knowledge"


def record_cache_event(cache_key: tuple, *, kind: str) -> None:
    """缓存命中遥测：只记命中（miss 会走常规检索遥测，无需重复）。"""
    try:
        from app.agent.trace import record_event

        signature, query = cache_key
        record_event("retrieval", "cache_hit", metadata={
            "kind": kind, "query": query[:120],
            "city": signature[0], "category": signature[1], "top_k": signature[2],
        })
    except Exception:  # noqa: BLE001 - 遥测失败不影响检索主链路
        pass


class PoIKnowledgeStore:
    """保持 Chroma 索引与 MySQL 权威 POI 数据一致。

    同一 embedding/document 版本下只 upsert 指纹变化的记录；版本变化时
    全量重建，避免使用不同模型的向量混在同一个集合中。
    """

    def __init__(
        self,
        persist_dir: Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._persist_dir = persist_dir or _DATA_DIR
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_provider = embedding_provider or create_embedding_provider()
        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME, metadata=self._collection_metadata()
        )
        self._documents: dict[str, dict[str, Any]] = {}
        self._retriever = HybridRetriever(
            self._collection, self.embedding_provider, rrf_k=settings.rag_rrf_k
        )
        # P2：语义缓存与轻量近邻图（都在索引同步点重建/失效）。
        self._cache = RetrievalCache()
        self._graph = PoiGraph()
        self._loaded = False
        self._source_unavailable = False
        self._last_source_retry_at = 0.0
        # 上次成功加载/同步的时刻，用于 rag_refresh_seconds 惰性刷新判定。
        self._last_load_at = 0.0
        self._sync_lock = threading.RLock()
        self._last_sync: dict[str, Any] = {}

    def _collection_metadata(self, *, index_version: str | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "hnsw:space": "cosine",
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_version": self.embedding_provider.version,
            "document_version": settings.rag_document_version,
        }
        if index_version:
            metadata["index_version"] = index_version
        return metadata

    @property
    def collection(self):
        return self._collection

    @property
    def index_info(self) -> dict[str, Any]:
        return dict(self._last_sync)

    def ensure_loaded(self, force: bool = False) -> None:
        with self._sync_lock:
            now = time.monotonic()
            stale = (settings.rag_refresh_seconds > 0
                     and now - self._last_load_at > settings.rag_refresh_seconds)
            if self._loaded and not self._source_unavailable and not force and not stale:
                return
            # 数据库恢复期间避免每个请求都重复连接；force 仍可立即触发检查。
            if self._source_unavailable and not force and now - self._last_source_retry_at < 30:
                return
            self._last_source_retry_at = now
            pois, available = poi_repository.list_all_pois_with_status()
            if not available:
                # 数据库短暂不可用不能等同于空表，否则会把可恢复的索引删掉。
                self._restore_from_collection()
                self._loaded = True
                self._source_unavailable = True
                self._last_load_at = now
                self._last_sync = {
                    "status": "source_unavailable",
                    "poi_count": len(self._documents),
                    "fallback": True,
                }
                logger.warning("POI 数据源不可用，保留已有 Chroma 索引并降级检索")
                return
            try:
                self._sync(pois)
            except Exception as exc:  # noqa: BLE001 - 索引同步失败不能拖垮检索
                # 保留旧内存目录继续服务，并把本次纳入与"数据源不可用"同样的
                # 30s 退避窗口；否则每个请求都会重复"查全表→失败"。
                logger.warning("RAG 索引同步失败，沿用现有索引: %s", exc)
                self._source_unavailable = True
                self._last_load_at = now
                return
            self._loaded = True
            self._source_unavailable = False
            self._last_load_at = time.monotonic()

    def _restore_from_collection(self) -> None:
        """数据库不可用时从已有 Chroma 元数据恢复词法检索所需的内存目录。"""
        try:
            result = self._collection.get(include=["documents", "metadatas"])
        except Exception as exc:
            logger.warning("恢复已有 Chroma 索引失败: %s", exc)
            self._documents = {}
            self._retriever.set_documents(self._documents)
            return
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        restored: dict[str, dict[str, Any]] = {}
        for document, metadata in zip(documents, metadatas):
            if not metadata or metadata.get("id") is None:
                continue
            pid = str(metadata["id"])
            restored[pid] = {"document": document or "", "metadata": metadata,
                             "fingerprint": metadata.get("content_fingerprint", "")}
        self._documents = restored
        self._retriever.set_documents(self._documents)
        self._graph.rebuild(self._documents)

    def _row_payload(self, poi: dict[str, Any]) -> tuple[str, str, dict[str, Any], str]:
        pid = str(poi["id"])
        document = build_poi_document(poi)
        source = poi.get("source") or "mysql.poi_knowledge"
        source_updated_at = str(poi.get("source_updated_at") or "")
        fingerprint_payload = {
            "id": pid, "document": document, "city": poi.get("city") or "",
            "category": poi.get("category") or "", "address": poi.get("address") or "",
            "latitude": poi.get("latitude"), "longitude": poi.get("longitude"),
            "ticket_price": poi.get("ticket_price"), "avg_cost": poi.get("avg_cost"),
            "duration_min": poi.get("duration_min"),
            "open_time": poi.get("open_time") or "", "tags": poi.get("tags") or "",
            "rating": poi.get("rating"), "description": poi.get("description") or "",
            "source": source, "source_updated_at": source_updated_at,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        metadata: dict[str, Any] = {
            "id": int(poi["id"]), "city": poi.get("city") or "",
            "category": poi.get("category") or "", "name": poi.get("name") or "",
            "address": poi.get("address") or "", "latitude": float(poi.get("latitude") or 0.0),
            "longitude": float(poi.get("longitude") or 0.0),
            "duration_min": int(poi.get("duration_min") or 0),
            "open_time": poi.get("open_time") or "", "tags": poi.get("tags") or "",
            "rating": float(poi.get("rating") or 0.0), "description": poi.get("description") or "",
            "source": source, "source_updated_at": source_updated_at,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_version": self.embedding_provider.version,
            "document_version": settings.rag_document_version,
            "content_fingerprint": fingerprint,
        }
        # Chroma 不接受 None：缺价字段直接省略，禁止把 NULL 写成 0.0 哨兵
        # （否则下游把 0 当成真实免费价，0 价覆盖与 Reflect 会失效）。
        ticket_price = poi.get("ticket_price")
        avg_cost = poi.get("avg_cost")
        if ticket_price is not None:
            try:
                metadata["ticket_price"] = float(ticket_price)
            except (TypeError, ValueError):
                pass
        if avg_cost is not None:
            try:
                metadata["avg_cost"] = float(avg_cost)
            except (TypeError, ValueError):
                pass
        return pid, document, metadata, fingerprint

    def _sync(self, pois: list[dict]) -> None:
        desired: dict[str, dict[str, Any]] = {}
        for poi in pois:
            if poi.get("id") is None:
                continue
            pid, document, metadata, fingerprint = self._row_payload(poi)
            desired[pid] = {"document": document, "metadata": metadata, "fingerprint": fingerprint}

        existing_meta = self._collection.metadata or {}
        signature = self._collection_metadata()
        # hnsw:space 是建集合时的静态配置，modify(index_version) 后可能不再出现在
        # 返回的 metadata 中；模型/文档版本才决定是否必须全量重建。
        version_keys = ("embedding_provider", "embedding_model", "embedding_version", "document_version")
        version_mismatch = any(existing_meta.get(key) != signature[key] for key in version_keys)
        existing = self._collection.get(include=["metadatas"])
        existing_ids = {str(pid) for pid in existing.get("ids", [])}
        existing_by_id = {
            str(meta.get("id")): meta
            for meta in (existing.get("metadatas") or [])
            if meta and meta.get("id") is not None
        }
        legacy = any("content_fingerprint" not in meta for meta in existing_by_id.values())
        full_rebuild = version_mismatch or legacy
        if full_rebuild:
            self._rebuild(desired)
            changed_count = len(desired)
            deleted_count = len(existing_ids)
        else:
            changed_ids = [pid for pid, item in desired.items()
                           if existing_by_id.get(pid, {}).get("content_fingerprint") != item["fingerprint"]]
            deleted = existing_ids - set(desired)
            if deleted:
                self._collection.delete(ids=sorted(deleted))
            if changed_ids:
                changed = [desired[pid] for pid in changed_ids]
                self._collection.upsert(
                    ids=changed_ids,
                    documents=[item["document"] for item in changed],
                    metadatas=[item["metadata"] for item in changed],
                    embeddings=self.embedding_provider.embed_documents([item["document"] for item in changed]),
                )
            changed_count = len(changed_ids)
            deleted_count = len(deleted)
            self._update_collection_metadata(self._index_version(desired))

        self._documents = desired
        self._retriever.collection = self._collection
        self._retriever.set_documents(self._documents)
        self._graph.rebuild(self._documents)
        self._cache.clear()  # 索引内容已变化，旧缓存整体失效。
        self._last_sync = {
            "index_version": self._index_version(desired),
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_version": self.embedding_provider.version,
            "document_version": settings.rag_document_version,
            "poi_count": len(desired), "changed_count": changed_count,
            "deleted_count": deleted_count, "full_rebuild": full_rebuild,
            "fallback": bool(self.embedding_provider.fallback),
        }
        logger.info(
            "RAG 索引同步完成：总数=%s，更新=%s，删除=%s，全量重建=%s",
            len(desired), changed_count, deleted_count, full_rebuild,
        )

    def _index_version(self, desired: dict[str, dict[str, Any]]) -> str:
        values = [f"{pid}:{item['fingerprint']}" for pid, item in sorted(desired.items())]
        payload = "|".join([self.embedding_provider.identity, settings.rag_document_version, *values])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _update_collection_metadata(self, index_version: str) -> None:
        try:
            # Chroma 不允许通过 modify 改变 hnsw:space；该静态配置只在建集合时写入。
            metadata = self._collection_metadata(index_version=index_version)
            metadata.pop("hnsw:space", None)
            self._collection.modify(metadata=metadata)
        except Exception as exc:
            logger.warning("更新 Chroma 索引元数据失败: %s", exc)

    def _rebuild(self, desired: dict[str, dict[str, Any]]) -> None:
        logger.info("构建 RAG 索引：%s 条", len(desired))
        try:
            self._client.delete_collection(_COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata=self._collection_metadata(index_version=self._index_version(desired)),
        )
        if not desired:
            return
        ids = list(desired)
        self._collection.add(
            ids=ids,
            documents=[desired[pid]["document"] for pid in ids],
            metadatas=[desired[pid]["metadata"] for pid in ids],
            embeddings=self.embedding_provider.embed_documents([desired[pid]["document"] for pid in ids]),
        )

    def search(
        self, query: str, city: str | None = None, category: str | None = None,
        limit: int | None = None, *, preferences: list[str] | None = None,
        budget: float | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_loaded()
        top_k = limit or settings.rag_top_k
        cache_key = make_cache_key(query, city=city, category=category, top_k=top_k,
                                   preferences=preferences, budget=budget)
        if settings.rag_cache_enabled:
            # 必须传 embedding_provider，否则近似命中分支在生产链路永远不生效
            # （单测传入 provider 掩盖了这一集成缺口）。
            cached = self._cache.lookup(
                cache_key, embedding_provider=self.embedding_provider,
                index_version=str(self._last_sync.get("index_version", "")))
            if cached is not None:
                record_cache_event(cache_key, kind="hit")
                return cached
        rows = self._retriever.search(
            query, city=city, category=category,
            top_k=top_k, preferences=preferences, budget=budget,
        )
        # 降级结果（向量/精排 fallback）与空结果不缓存，避免固化瞬时故障。
        if settings.rag_cache_enabled and rows and not self._retriever.last_telemetry.get("fallback"):
            self._cache.store(cache_key, rows, embedding_provider=self.embedding_provider,
                              index_version=str(self._last_sync.get("index_version", "")))
        return rows

    def cache_stats(self) -> dict[str, Any]:
        """语义缓存命中统计（观测/评测用）。"""
        return self._cache.stats()

    def nearby(self, city: str, latitude: float, longitude: float, *,
               limit: int | None = None, radius_m: int | None = None,
               category: str | None = None,
               exclude: str | int | None = None) -> list[dict[str, Any]]:
        """给定坐标的同城权威 POI 近邻（轻量 GraphRAG 空间层）。"""
        self.ensure_loaded()
        return self._graph.nearby(city, latitude, longitude, limit=limit,
                                  radius_m=radius_m, category=category, exclude=exclude)

    def neighbors(self, poi_id: str | int, *, limit: int | None = None,
                  radius_m: int | None = None,
                  category: str | None = None) -> list[dict[str, Any]]:
        """给定 POI 的同城近邻（轻量 GraphRAG 空间层）。"""
        self.ensure_loaded()
        return self._graph.neighbors(poi_id, limit=limit, radius_m=radius_m,
                                     category=category)

    def same_tag(self, poi_id: str | int, *,
                 limit: int | None = None) -> list[dict[str, Any]]:
        """给定 POI 的同标签同类推荐（轻量 GraphRAG 标签层）。"""
        self.ensure_loaded()
        return self._graph.same_tag(poi_id, limit=limit)

    def graph_stats(self) -> dict[str, int]:
        self.ensure_loaded()
        return self._graph.stats()


poi_store = PoIKnowledgeStore()


def warmup_rag() -> None:
    poi_store.ensure_loaded()
