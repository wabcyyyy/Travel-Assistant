"""检索结果语义缓存（P2）。

两级命中：
- 精确键：(query, city, category, top_k, preferences, budget) 完全一致；
- 语义近似：同一过滤签名下，查询向量 cosine 相似度 ≥ 阈值时复用，
  避免同义改写（"适合老人的景点" vs "适合老年人的景区"）重复触发
  embedding 与 cross-encoder 精排（CPU 上 2-4s）。

失效策略：
- 每条缓存记录写入时的 index_version；读取时版本不一致即整体清空，
  保证索引重建/增量同步后不会返回旧数据；
- TTL 过期逐条失效；容量上限 LRU 淘汰。

安全边界：
- 降级结果（semantic/reranker fallback）与空结果不缓存，避免把瞬时
  故障或空索引固化 5 分钟；
- 缓存返回深拷贝，调用方对行的原地修改不会污染缓存。
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.common.config import settings

logger = logging.getLogger(__name__)

# 缓存键：过滤签名 + 原始查询。签名不同（城市/类别/偏好/预算/top_k 不同）
# 的条目永远不互相命中，语义近似也只在同签名桶内比较。
CacheKey = tuple[tuple, str]


def make_cache_key(query: str, *, city: str | None, category: str | None,
                   top_k: int, preferences: list[str] | None,
                   budget: float | None) -> CacheKey:
    signature = (
        city or "", category or "", int(top_k),
        tuple(sorted(str(p) for p in (preferences or []))),
        None if budget is None else round(float(budget), 2),
    )
    return signature, str(query or "")


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
    return dot / norm if norm else 0.0


@dataclass
class _Entry:
    rows: list[dict[str, Any]]
    query_embedding: list[float]
    index_version: str
    expires_at: float
    kind: str = "exact"  # exact | semantic
    stored_at: float = field(default_factory=time.monotonic)


class RetrievalCache:
    """线程安全的进程内检索缓存；零外部依赖，索引版本变化即整体失效。"""

    def __init__(self, *, ttl_seconds: int | None = None, max_entries: int | None = None,
                 similarity: float | None = None) -> None:
        # 显式 None 判断：0 是合法值（ttl=0 立即过期、similarity=0 关闭近似命中），
        # 不能走 falsy 回退。
        self.ttl_seconds = int(ttl_seconds if ttl_seconds is not None
                               else settings.rag_cache_ttl_seconds)
        self.max_entries = max(int(max_entries if max_entries is not None
                                   else settings.rag_cache_max_entries), 1)
        self.similarity = float(similarity if similarity is not None
                                else settings.rag_cache_similarity)
        self._buckets: dict[tuple, OrderedDict[str, _Entry]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.semantic_hits = 0

    @property
    def size(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._buckets.values())

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": sum(len(bucket) for bucket in self._buckets.values()),
                "hits": self.hits, "semantic_hits": self.semantic_hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / max(self.hits + self.misses, 1), 4),
            }

    def lookup(self, key: CacheKey, *, embedding_provider: Any = None,
               index_version: str = "") -> list[dict[str, Any]] | None:
        signature, query = key
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(signature)
            if bucket:
                self._drop_expired(bucket, now)
            entry = bucket.get(query) if bucket else None
            if entry is not None and entry.index_version != index_version:
                # 索引已变化：全部旧版本条目一律失效。
                self._buckets.clear()
                entry = None
            if entry is None and embedding_provider is not None and bucket:
                entry = self._semantic_lookup(bucket, query, embedding_provider, index_version)
            if entry is None:
                self.misses += 1
                return None
            self.hits += 1
            if entry.kind == "semantic":
                self.semantic_hits += 1
            # 深拷贝出缓存：调用方对行的原地修改不会污染缓存条目。
            return copy.deepcopy(entry.rows)

    def store(self, key: CacheKey, rows: list[dict[str, Any]], *,
              embedding_provider: Any = None, index_version: str = "") -> None:
        if not rows:
            return  # 空结果不缓存：往往意味着瞬时故障或空索引。
        signature, query = key
        now = time.monotonic()
        try:
            embedding = (embedding_provider.embed_query(query)
                         if embedding_provider is not None else [])
        except Exception as exc:  # noqa: BLE001 - 向量化失败只影响缓存，不影响检索
            logger.debug("缓存条目向量化失败，跳过写入: %s", exc)
            return
        with self._lock:
            bucket = self._buckets.setdefault(signature, OrderedDict())
            bucket[query] = _Entry(rows=rows, query_embedding=embedding,
                                   index_version=index_version,
                                   expires_at=now + self.ttl_seconds)
            bucket.move_to_end(query)
            self._evict()

    def _drop_expired(self, bucket: OrderedDict[str, _Entry], now: float) -> None:
        expired = [query for query, entry in bucket.items() if entry.expires_at <= now]
        for query in expired:
            bucket.pop(query, None)

    def _semantic_lookup(self, bucket: OrderedDict[str, _Entry], query: str,
                         embedding_provider: Any, index_version: str) -> _Entry | None:
        """同签名桶内的近似命中：cosine ≥ 阈值即复用（取最高分）。"""
        if self.similarity <= 0:
            return None
        try:
            query_embedding = embedding_provider.embed_query(query)
        except Exception:
            return None
        best: tuple[float, str, _Entry] | None = None
        for candidate_query, entry in bucket.items():
            if entry.index_version != index_version:
                continue
            score = _cosine(query_embedding, entry.query_embedding)
            if score >= self.similarity and (best is None or score > best[0]):
                best = (score, candidate_query, entry)
        if best is None:
            return None
        _, entry_key, entry = best
        entry.kind = "semantic"  # 近似命中标记，供命中统计区分
        bucket.move_to_end(entry_key)  # LRU 触碰原条目
        return entry

    def _evict(self) -> None:
        while sum(len(bucket) for bucket in self._buckets.values()) > self.max_entries:
            oldest_signature = next(iter(self._buckets))
            bucket = self._buckets[oldest_signature]
            bucket.popitem(last=False)
            if not bucket:
                self._buckets.pop(oldest_signature, None)
