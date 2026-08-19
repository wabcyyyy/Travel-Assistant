import logging
from pathlib import Path

import chromadb
from chromadb.config import Settings

from app.agent import poi_repository
from app.common.config import BASE_DIR
from app.rag.embeddings import embed

logger = logging.getLogger(__name__)

_DATA_DIR = BASE_DIR / "data"
_COLLECTION_NAME = "poi_knowledge"


class PoIKnowledgeStore:
    def __init__(self, persist_dir: Path | None = None) -> None:
        self._persist_dir = persist_dir or _DATA_DIR
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        self._loaded = False

    def ensure_loaded(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        pois = poi_repository.list_all_pois()
        if not pois:
            logger.warning("poi_knowledge 为空，跳过 RAG 索引构建")
            self._loaded = True
            return
        if not force and self._collection.count() == len(pois):
            logger.info("RAG 索引已存在（%s 条），跳过构建", self._collection.count())
            self._loaded = True
            return
        self._rebuild(pois)
        self._loaded = True

    def _rebuild(self, pois: list[dict]) -> None:
        logger.info("构建 RAG 索引：%s 条", len(pois))
        try:
            self._client.delete_collection(_COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        for poi in pois:
            pid = poi.get("id")
            if pid is None:
                continue
            ids.append(str(pid))
            documents.append(
                " ".join(
                    filter(
                        None,
                        [
                            poi.get("name"),
                            poi.get("tags"),
                            poi.get("description"),
                            poi.get("address"),
                        ],
                    )
                )
            )
            metadatas.append(
                {
                    "id": int(pid),
                    "city": poi.get("city") or "",
                    "category": poi.get("category") or "",
                    "name": poi.get("name") or "",
                    "address": poi.get("address") or "",
                    "latitude": float(poi.get("latitude") or 0.0),
                    "longitude": float(poi.get("longitude") or 0.0),
                    "ticket_price": float(poi.get("ticket_price") or 0.0),
                    "duration_min": int(poi.get("duration_min") or 0),
                    "open_time": poi.get("open_time") or "",
                    "tags": poi.get("tags") or "",
                    "rating": float(poi.get("rating") or 0.0),
                    "description": poi.get("description") or "",
                }
            )
        if not ids:
            return
        embeddings = [embed(doc) for doc in documents]
        self._collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        logger.info("RAG 索引构建完成：%s 条", len(ids))

    def search(self, query: str, city: str | None = None, category: str | None = None,
               limit: int = 10) -> list[dict]:
        where: dict = {}
        if city:
            where["city"] = city
        if category:
            where["category"] = category
        try:
            result = self._collection.query(
                query_embeddings=[embed(query)],
                n_results=max(limit, 1),
                where=where if where else None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error("RAG 检索失败: %s", e)
            return []
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        rows: list[dict] = []
        for meta, dist in zip(metas, distances):
            if meta is None:
                continue
            rows.append(
                {
                    "id": meta.get("id"),
                    "city": meta.get("city"),
                    "name": meta.get("name"),
                    "category": meta.get("category"),
                    "address": meta.get("address") or None,
                    "latitude": meta.get("latitude") or None,
                    "longitude": meta.get("longitude") or None,
                    "ticket_price": meta.get("ticket_price") or None,
                    "duration_min": meta.get("duration_min") or None,
                    "open_time": meta.get("open_time") or None,
                    "tags": meta.get("tags") or None,
                    "rating": meta.get("rating") or None,
                    "description": meta.get("description") or None,
                    "_distance": dist,
                }
            )
        return rows


poi_store = PoIKnowledgeStore()


def warmup_rag() -> None:
    poi_store.ensure_loaded()