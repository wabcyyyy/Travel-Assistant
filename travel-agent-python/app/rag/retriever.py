"""可插拔 Embedding 与 POI 混合检索实现。

这里不把业务代码绑定到 Chroma 的具体 embedding function：

* ``EmbeddingProvider`` 是统一的向量化接口；
* 哈希 n-gram 是默认离线实现；
* ``sentence-transformers`` 只作为可选依赖，模型不可用时启动仍可工作；
* 词法召回使用无额外依赖的 BM25 风格打分，与 Chroma 语义召回通过 RRF 融合；
* 业务重排只改变排序，不改变城市、类别和权威数据边界。
"""

from __future__ import annotations

import logging
import math
import re
import time
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

from app.agent.trace import record_event
from app.common.config import settings
from app.rag.embeddings import HashedNGramEmbedding

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """向量化提供方的最小稳定接口。"""

    provider_name: str
    model_name: str
    version: str
    fallback: bool = False

    @abstractmethod
    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        raise NotImplementedError

    @property
    def identity(self) -> str:
        return f"{self.provider_name}:{self.model_name}:{self.version}"


class HashedEmbeddingProvider(EmbeddingProvider):
    provider_name = "hashed"
    version = "1"

    def __init__(self, dim: int = 256) -> None:
        self._embedding = HashedNGramEmbedding(dim)
        self.model_name = self._embedding.name()

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return self._embedding(documents)

    def embed_query(self, query: str) -> list[float]:
        return self._embedding([query])[0]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    provider_name = "sentence-transformers"
    version = "1"

    def __init__(self, model_name: str) -> None:
        # Optional import is intentional: CI/offline deployments do not need to
        # download or install a model merely to import the application.
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "RAG semantic provider requires the optional 'sentence-transformers' dependency"
            ) from exc
        self.model_name = model_name
        # 只使用本地缓存，避免把“离线可运行”变成启动时隐式联网下载。
        self._model = SentenceTransformer(model_name, model_kwargs={"local_files_only": True})

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        vectors = self._model.encode(documents, normalize_embeddings=True)
        return vectors.tolist() if hasattr(vectors, "tolist") else list(vectors)

    def embed_query(self, query: str) -> list[float]:
        return self.embed_documents([query])[0]


def create_embedding_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
) -> EmbeddingProvider:
    """创建配置的 embedding provider，模型不可用时安全降级到哈希向量。"""
    configured = (provider_name or settings.rag_embedding_provider).strip().lower()
    model = model_name or settings.rag_embedding_model
    if configured in {"hashed", "hash", "offline"}:
        return HashedEmbeddingProvider()
    if configured in {"semantic", "sentence-transformers", "sentence_transformers", "st"}:
        try:
            return SentenceTransformerEmbeddingProvider(model)
        except Exception as exc:
            logger.warning("语义 Embedding 不可用，降级到哈希 Embedding: %s", exc)
            fallback = HashedEmbeddingProvider()
            fallback.fallback = True
            return fallback
    raise ValueError(f"不支持的 RAG_EMBEDDING_PROVIDER: {configured}")


class RerankerProvider(ABC):
    """精排提供方的最小稳定接口：对 (query, document) 打 0~1 相关性分。"""

    provider_name: str
    model_name: str
    fallback: bool = False

    @abstractmethod
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        raise NotImplementedError


class NoopReranker(RerankerProvider):
    """无精排：保持融合排序结果不变。"""

    provider_name = "none"
    model_name = "none"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0] * len(documents)


class CrossEncoderReranker(RerankerProvider):
    provider_name = "cross-encoder"

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "RAG reranker requires the optional 'sentence-transformers' dependency"
            ) from exc
        self.model_name = model_name
        # 只使用本地缓存，与 embedding provider 保持一致的离线约定。
        self._model = CrossEncoder(model_name, max_length=512, local_files_only=True)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        logits = self._model.predict([(query, doc) for doc in documents])
        # bge-reranker 输出 logit；sigmoid 映射到 0~1 相关性分。
        return [1.0 / (1.0 + math.exp(-float(score))) for score in logits]


def create_reranker(
    provider_name: str | None = None,
    model_name: str | None = None,
) -> RerankerProvider:
    """创建配置的精排 provider，模型不可用时安全降级为无精排。"""
    configured = (provider_name or settings.rag_rerank_provider).strip().lower()
    if configured in {"", "none", "off", "disabled"}:
        return NoopReranker()
    model = model_name or settings.rag_rerank_model
    if configured in {"cross-encoder", "cross_encoder", "sentence-transformers", "st"}:
        try:
            return CrossEncoderReranker(model)
        except Exception as exc:
            logger.warning("精排模型不可用，降级为融合排序: %s", exc)
            fallback = NoopReranker()
            fallback.fallback = True
            return fallback
    raise ValueError(f"不支持的 RAG_RERANK_PROVIDER: {configured}")


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def tokenize(text: str | None) -> list[str]:
    """中文按字/二元组切分，英文数字按词和二元组切分。"""
    tokens = _TOKEN_RE.findall(str(text or "").lower())
    result: list[str] = []
    for token in tokens:
        if len(token) <= 2:
            result.append(token)
        result.extend(token[i : i + 2] for i in range(len(token) - 1))
    return result


def build_poi_document(poi: dict[str, Any]) -> str:
    """使用字段标签构造文档，避免名称与描述在向量中权重完全相同。"""
    fields = (
        ("名称", poi.get("name")),
        ("城市", poi.get("city")),
        ("类别", poi.get("category")),
        ("标签", poi.get("tags")),
        ("描述", poi.get("description")),
        ("地址", poi.get("address")),
    )
    return "\n".join(f"{label}：{value}" for label, value in fields if value not in (None, ""))


# 查询路由（P2）：把无意图查询从“向量+精排”重路径上移走。
# 泛词集合覆盖品类与旅游意图词；不含任何具体意图的查询走评分枚举。
_GENERIC_QUERY_WORDS = (
    "景点", "美食", "餐饮", "餐厅", "酒店", "住宿", "好玩", "旅游", "旅行",
    "热门", "推荐", "必去", "必吃", "必玩", "打卡", "小吃", "特产", "商圈",
    "附近", "周边", "攻略", "名胜", "景区", "游玩",
)

_NAME_STRIP_RE = re.compile(r"[\s（）()【】\[\]·]")


def normalize_query_name(text: str | None) -> str:
    """归一化查询/名称：去空白与括号等修饰符，供精确名路由匹配。"""
    return _NAME_STRIP_RE.sub("", str(text or ""))


def strip_generic_words(query: str, city: str | None) -> str:
    """去掉城市名与品类泛词后的剩余意图文本；为空说明查询没有具体意图。"""
    text = str(query or "")
    if city:
        text = text.replace(str(city), " ")
    for word in _GENERIC_QUERY_WORDS:
        text = text.replace(word, " ")
    return "".join(text.split())


def _field_value(poi: dict[str, Any], key: str) -> str:
    return str(poi.get(key) or "")


class HybridRetriever:
    """Chroma 语义召回 + 本地 BM25 风格词法召回 + RRF/业务重排。"""

    def __init__(
        self,
        collection: Any,
        embedding_provider: EmbeddingProvider,
        *,
        rrf_k: int | None = None,
        reranker: RerankerProvider | None = None,
    ) -> None:
        self.collection = collection
        self.embedding_provider = embedding_provider
        self.rrf_k = max(int(rrf_k or settings.rag_rrf_k), 1)
        self.documents: dict[str, dict[str, Any]] = {}
        self._lexical_cache: dict[tuple[str | None, str | None], tuple[dict[str, list[str]], Counter[str], float]] = {}
        self.last_telemetry: dict[str, Any] = {}
        # 精排 provider 惰性创建：构造检索器不应触发 2GB 级模型加载（如测试场景）。
        self._reranker = reranker

    @property
    def reranker(self) -> RerankerProvider:
        if self._reranker is None:
            self._reranker = create_reranker()
        return self._reranker

    def set_documents(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents
        self._lexical_cache.clear()

    def _allowed(self, row: dict[str, Any], city: str | None, category: str | None) -> bool:
        return (not city or row.get("city") == city) and (not category or row.get("category") == category)

    def _route(self, query: str, city: str | None, category: str | None) -> str:
        """查询路由：enumerate（无意图枚举）/ lexical（精确名直查）/ hybrid（默认）。

        路由只决定执行路径，不改变城市、类别与权威数据边界；匹配不到具体
        意图时保守回退 hybrid，保证语义与精排收益不丢失。
        """
        if not settings.rag_router_enabled or not self.documents:
            return "hybrid"
        if not strip_generic_words(query, city):
            return "enumerate"
        query_name = normalize_query_name(query)
        if len(query_name) >= 2:
            for item in self.documents.values():
                if not self._allowed(item["metadata"], city, category):
                    continue
                if normalize_query_name(item["metadata"].get("name")) == query_name:
                    return "lexical"
        return "hybrid"

    def _enumerate(
        self, *, city: str | None, category: str | None,
        preferences: list[str] | None, top_k: int,
    ) -> list[dict[str, Any]]:
        """无意图查询的确定性枚举：偏好命中优先，其次评分，最后稳定按 id。"""
        rows = [
            dict(item["metadata"]) for item in self.documents.values()
            if self._allowed(item["metadata"], city, category)
        ]
        for row in rows:
            preference_score = self._preference_score(row, preferences or [])
            rating_score = min(max(float(row.get("rating") or 0.0) / 5.0, 0.0), 1.0)
            row.update({
                "_route": "enumerate",
                "_preference_score": round(preference_score, 6),
                "_business_score": round(0.16 * preference_score + 0.06 * rating_score, 6),
                "_retrieval_score": round(preference_score + rating_score, 6),
                "_authoritative": True,
            })
        rows.sort(key=lambda row: (-row["_retrieval_score"], int(row.get("id") or 0)))
        return rows[:top_k]

    def _lexical_search(
        self, query: str, *, city: str | None, category: str | None, candidate_limit: int
    ) -> list[tuple[str, float]]:
        query_tokens = Counter(tokenize(query))
        if not query_tokens:
            return []
        cache_key = (city, category)
        cached = self._lexical_cache.get(cache_key)
        if cached is None:
            allowed = {
                doc_id: item for doc_id, item in self.documents.items()
                if self._allowed(item["metadata"], city, category)
            }
            document_tokens = {
                doc_id: tokenize(item["document"]) for doc_id, item in allowed.items()
            }
            document_frequency: Counter[str] = Counter()
            for tokens in document_tokens.values():
                document_frequency.update(set(tokens))
            avgdl = sum(len(tokens) for tokens in document_tokens.values()) / max(len(document_tokens), 1)
            cached = (document_tokens, document_frequency, avgdl)
            self._lexical_cache[cache_key] = cached
        document_tokens, document_frequency, avgdl = cached
        if not document_tokens:
            return []
        scored: list[tuple[str, float]] = []
        for doc_id, tokens in document_tokens.items():
            counts = Counter(tokens)
            dl = len(tokens)
            score = 0.0
            for token, query_tf in query_tokens.items():
                tf = counts.get(token, 0)
                if not tf:
                    continue
                df = document_frequency[token]
                idf = math.log(1 + (len(document_tokens) - df + 0.5) / (df + 0.5))
                denominator = tf + 1.5 * (0.75 + 0.25 * dl / max(avgdl, 1))
                score += idf * tf * 2.5 / denominator * min(query_tf, 2)
            row = self.documents[doc_id]["metadata"]
            name = _field_value(row, "name").lower()
            tags = _field_value(row, "tags").lower()
            query_lower = query.lower()
            if name and (query_lower in name or name in query_lower):
                score += 12.0
            score += sum(2.0 for token in query_tokens if token in name)
            score += sum(0.8 for token in query_tokens if token in tags)
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:candidate_limit]

    def _semantic_search(
        self, query: str, *, city: str | None, category: str | None, candidate_limit: int
    ) -> tuple[list[tuple[str, float]], bool]:
        where: dict[str, Any] | None = None
        conditions: list[dict[str, Any]] = []
        if city:
            conditions.append({"city": city})
        if category:
            conditions.append({"category": category})
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            where = {"$and": conditions}
        try:
            result = self.collection.query(
                query_embeddings=[self.embedding_provider.embed_query(query)],
                n_results=max(candidate_limit, 1),
                where=where,
                include=["metadatas", "distances"],
            )
            metas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            rows: list[tuple[str, float]] = []
            for meta, distance in zip(metas, distances):
                if not meta:
                    continue
                doc_id = str(meta.get("id"))
                if doc_id in self.documents and self._allowed(meta, city, category):
                    # Chroma cosine distance is 1 - cosine similarity.
                    rows.append((doc_id, max(0.0, min(1.0, 1.0 - float(distance)))))
            return rows, False
        except Exception as exc:
            logger.warning("语义召回失败，保留词法召回: %s", exc)
            return [], True

    def _preference_score(self, row: dict[str, Any], preferences: list[str]) -> float:
        if not preferences:
            return 0.0
        haystack = " ".join(_field_value(row, key) for key in ("tags", "description", "category")).lower()
        hits = sum(1 for preference in preferences if str(preference).lower() in haystack)
        return hits / len(preferences)

    def search(
        self,
        query: str,
        *,
        city: str | None = None,
        category: str | None = None,
        top_k: int | None = None,
        preferences: list[str] | None = None,
        budget: float | None = None,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        final_k = max(int(top_k or settings.rag_top_k), 1)
        candidate_limit = max(final_k * 2, settings.rag_top_k)
        route = self._route(query, city, category)
        semantic_fallback = False
        lexical: list[tuple[str, float]] = []
        semantic: list[tuple[str, float]] = []
        if route == "enumerate":
            rows = self._enumerate(city=city, category=category,
                                   preferences=preferences, top_k=final_k)
            self.last_telemetry = {
                "provider": "enumerate", "route": route,
                "embedding_provider": self.embedding_provider.provider_name,
                "embedding_model": self.embedding_provider.model_name,
                "semantic_count": 0, "lexical_count": 0,
                "fused_count": 0, "candidate_count": len(rows),
                "top_k": final_k,
                "fallback": bool(self.embedding_provider.fallback),
                "selected_poi_ids": [row.get("id") for row in rows],
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            record_event("retrieval", "poi.hybrid_search",
                         metadata={"query": query[:120], **self.last_telemetry})
            return rows
        if route == "lexical":
            # 精确名直查：BM25 的名称加权保证目标 rank-1，无需向量与精排。
            lexical = self._lexical_search(query, city=city, category=category,
                                           candidate_limit=candidate_limit)
        else:
            lexical = self._lexical_search(query, city=city, category=category,
                                           candidate_limit=candidate_limit)
            semantic, semantic_fallback = self._semantic_search(
                query, city=city, category=category, candidate_limit=candidate_limit
            )
        lexical_rank = {doc_id: rank for rank, (doc_id, _) in enumerate(lexical, start=1)}
        semantic_rank = {doc_id: rank for rank, (doc_id, _) in enumerate(semantic, start=1)}
        semantic_score = dict(semantic)
        lexical_score = dict(lexical)
        ids = set(lexical_rank) | set(semantic_rank)
        max_lexical = max(lexical_score.values(), default=1.0)
        reranked: list[tuple[float, str, dict[str, Any]]] = []
        for doc_id in ids:
            item = self.documents[doc_id]
            row = dict(item["metadata"])
            rrf = 0.0
            if doc_id in lexical_rank:
                rrf += 1 / (self.rrf_k + lexical_rank[doc_id])
            if doc_id in semantic_rank:
                rrf += 1 / (self.rrf_k + semantic_rank[doc_id])
            lexical_normalized = lexical_score.get(doc_id, 0.0) / max_lexical
            semantic_normalized = semantic_score.get(doc_id, 0.0)
            preference_score = self._preference_score(row, preferences or [])
            rating_score = min(max(float(row.get("rating") or 0.0) / 5.0, 0.0), 1.0)
            budget_penalty = 0.0
            price = row.get("ticket_price")
            if budget is not None and price is not None and float(price) > float(budget):
                budget_penalty = min((float(price) - float(budget)) / max(float(budget), 1.0), 1.0)
            business = (
                0.18 * lexical_normalized
                + 0.18 * semantic_normalized
                + 0.16 * preference_score
                + 0.06 * rating_score
                - 0.12 * budget_penalty
            )
            row.update({
                "_semantic_score": round(semantic_score.get(doc_id, 0.0), 6),
                "_lexical_score": round(lexical_score.get(doc_id, 0.0), 6),
                "_distance": round(1.0 - semantic_score[doc_id], 6) if doc_id in semantic_score else None,
                "_rrf_score": round(rrf, 8),
                "_business_score": round(business, 6),
                "_retrieval_score": round(rrf + business, 8),
                "_authoritative": True,
            })
            reranked.append((rrf + business, doc_id, row))
        reranked.sort(key=lambda value: (-value[0], value[1]))
        # 精排（P0②）：对融合排序头部窗口做 cross-encoder 重打分。
        # 精排分为主、业务分为辅（0.7/0.3），窗口外的尾部保持融合排序不变；
        # 精排失败时整段退回融合排序结果。lexical 直查路由无需语义精排。
        rerank_telemetry: dict[str, Any] = {}
        window_n = min(len(reranked), max(final_k, settings.rag_rerank_candidates))
        if route == "hybrid" and window_n > 0 and self.reranker.provider_name != "none":
            window = reranked[:window_n]
            rest = reranked[window_n:]
            started_rerank = time.perf_counter()
            scores: list[float] | None = None
            try:
                scores = self.reranker.rerank(
                    query, [self.documents[doc_id]["document"] for _, doc_id, _ in window]
                )
            except Exception as exc:  # noqa: BLE001 - 精排失败不阻断检索
                logger.warning("精排失败，退回融合排序: %s", exc)
            if scores is not None:
                rescored: list[tuple[float, str, dict[str, Any]]] = []
                for (_, doc_id, row), score in zip(window, scores):
                    rerank_score = max(0.0, min(1.0, float(score)))
                    # business 分值域约 [-0.12, 0.58]，归一到 0~1 后与精排分加权。
                    business = float(row["_business_score"])
                    business_norm = max(0.0, min(1.0, (business + 0.12) / 0.70))
                    row["_rerank_score"] = round(rerank_score, 6)
                    row["_retrieval_score"] = round(0.7 * rerank_score + 0.3 * business_norm, 8)
                    rescored.append((row["_retrieval_score"], doc_id, row))
                rescored.sort(key=lambda value: (-value[0], value[1]))
                reranked = rescored + rest
            rerank_telemetry = {
                "reranker": self.reranker.provider_name,
                "rerank_model": self.reranker.model_name,
                "rerank_candidates": window_n,
                "rerank_duration_ms": round((time.perf_counter() - started_rerank) * 1000, 2),
            }
        rows = [row for _, _, row in reranked[:final_k]]
        for row in rows:
            row["_route"] = route
        self.last_telemetry = {
            "provider": "semantic+bm25" if route == "hybrid" else "bm25",
            "route": route,
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "semantic_count": len(semantic),
            "lexical_count": len(lexical),
            "fused_count": len(ids),
            "candidate_count": len(ids),
            "top_k": final_k,
            "fallback": bool(self.embedding_provider.fallback or semantic_fallback
                             or self.reranker.fallback),
            **rerank_telemetry,
            "selected_poi_ids": [row.get("id") for row in rows],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        record_event(
            "retrieval",
            "poi.hybrid_search",
            metadata={"query": query[:120], **self.last_telemetry},
        )
        return rows
