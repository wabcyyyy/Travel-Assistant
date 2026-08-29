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
from app.rag.retriever import (
    EmbeddingProvider,
    HybridRetriever,
    build_poi_document,
    create_embedding_provider,
)

logger = logging.getLogger(__name__)
_DATA_DIR = BASE_DIR / "data"
_COLLECTION_NAME = "poi_knowledge"


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
        self._loaded = False
        self._source_unavailable = False
        self._last_source_retry_at = 0.0
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
            if self._loaded and not self._source_unavailable and not force:
                return
            # 数据库恢复期间避免每个请求都重复连接；force 仍可立即触发检查。
            now = time.monotonic()
            if self._source_unavailable and not force and now - self._last_source_retry_at < 30:
                return
            self._last_source_retry_at = now
            pois, available = poi_repository.list_all_pois_with_status()
            if not available:
                # 数据库短暂不可用不能等同于空表，否则会把可恢复的索引删掉。
                self._restore_from_collection()
                self._loaded = True
                self._source_unavailable = True
                self._last_sync = {
                    "status": "source_unavailable",
                    "poi_count": len(self._documents),
                    "fallback": True,
                }
                logger.warning("POI 数据源不可用，保留已有 Chroma 索引并降级检索")
                return
            self._sync(pois)
            self._loaded = True
            self._source_unavailable = False

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

    def _row_payload(self, poi: dict[str, Any]) -> tuple[str, str, dict[str, Any], str]:
        pid = str(poi["id"])
        document = build_poi_document(poi)
        source = poi.get("source") or "mysql.poi_knowledge"
        source_updated_at = str(poi.get("source_updated_at") or "")
        fingerprint_payload = {
            "id": pid, "document": document, "city": poi.get("city") or "",
            "category": poi.get("category") or "", "address": poi.get("address") or "",
            "latitude": poi.get("latitude"), "longitude": poi.get("longitude"),
            "ticket_price": poi.get("ticket_price"), "duration_min": poi.get("duration_min"),
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
            "ticket_price": float(poi.get("ticket_price") or 0.0),
            "duration_min": int(poi.get("duration_min") or 0),
            "open_time": poi.get("open_time") or "", "tags": poi.get("tags") or "",
            "rating": float(poi.get("rating") or 0.0), "description": poi.get("description") or "",
            "source": source, "source_updated_at": source_updated_at,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_version": self.embedding_provider.version,
            "document_version": settings.rag_document_version,
            "content_fingerprint": fingerprint,
        }
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
        return self._retriever.search(
            query, city=city, category=category,
            top_k=limit or settings.rag_top_k, preferences=preferences, budget=budget,
        )


poi_store = PoIKnowledgeStore()


def warmup_rag() -> None:
    poi_store.ensure_loaded()
