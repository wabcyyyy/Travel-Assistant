"""向量集合的最小中性契约与 Qdrant 实现。

历史上检索层直接依赖 Chroma 的 collection 对象；切换到 Qdrant 时把边界
收敛为本模块的中性协议，检索层（HybridRetriever）与索引同步层只依赖该协议：

* ``query(vector, limit, where) -> [(payload, similarity)]`` —— 相似度语义
  （Chroma 的 ``distance = 1 - cosine`` 语义不再外泄到检索层）；
* ``where`` 为扁平等值过滤（城市/类别），由实现层映射到各自的过滤器；
* ``upsert`` / ``delete`` / ``all_payloads`` 仅服务索引同步与故障恢复；
  payload 中额外携带 ``document`` 字段，供词法召回在恢复场景重建语料。

三种运行模式（按优先级）：
- ``url``：独立 Qdrant 服务（生产共享/持久化，多实例可读）；
- ``path``：Qdrant 本地嵌入式持久化（默认；对应旧 Chroma PersistentClient）；
- ``memory``：纯内存（一次性重建场景）。

注意：向量数据是从 MySQL 权威库可全量重建的派生数据，本地模式的持久化
只是加速启动，不是数据主权所在。
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)


def _point_id(pid: str) -> int | str:
    """Qdrant 点 ID 只接受无符号整数或 UUID；数字直转，其余用 uuid5 确定性映射。"""
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"poi:{pid}"))
    return value if value > 0 else str(uuid.uuid5(uuid.NAMESPACE_URL, f"poi:{pid}"))


# 本地/服务客户端注册表：同一路径或 URL 进程内共享一个 QdrantClient。
# 本地模式对存储目录加文件锁（单客户端），与旧 Chroma PersistentClient 的
# 进程内去重行为对齐，避免第二个实例拿到 "already accessed" 错误。
_CLIENT_LOCK = threading.Lock()
_CLIENTS: dict[str, QdrantClient] = {}


def _get_client(*, path: str | None = None, url: str | None = None, timeout: float | None = None) -> QdrantClient:
    if url:
        key = f"url:{url}"
    elif path:
        key = f"path:{Path(path).resolve()}"
    else:
        # 纯内存模式不共享：每次调用得到独立实例，保证调用方之间数据隔离。
        return QdrantClient(":memory:")
    with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = QdrantClient(url=url, timeout=timeout) if url else QdrantClient(path=str(path))
            _CLIENTS[key] = client
        return client


def _build_filter(where: dict[str, Any] | None) -> Filter | None:
    """扁平等值过滤 → Qdrant Filter（本项目仅 city/category 两类键）。"""
    if not where:
        return None
    return Filter(
        must=[
            FieldCondition(key=str(key), match=MatchValue(value=value))
            for key, value in where.items()
            if value is not None
        ]
        or None
    )


class QdrantVectorCollection:
    """Qdrant 版向量集合：单集合、单向量、余弦相似度。"""

    def __init__(
        self,
        *,
        collection_name: str,
        vector_size: int,
        path: str | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._name = collection_name
        self._vector_size = int(vector_size)
        self._client = _get_client(path=path, url=url, timeout=timeout)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self._client.collection_exists(self._name):
            self._client.create_collection(
                self._name,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )
            logger.info("已创建 Qdrant 集合 %s（dim=%s）", self._name, self._vector_size)

    def current_vector_size(self) -> int | None:
        """集合当前向量维度；集合不存在或形状异常时返回 None。"""
        try:
            info = self._client.get_collection(self._name)
        except Exception:
            return None
        vectors = getattr(getattr(info, "config", None), "params", None)
        size = getattr(getattr(vectors, "vectors", None), "size", None)
        try:
            return int(size) if size else None
        except (TypeError, ValueError):
            return None

    def reset_if_dimension_mismatch(self, vector_size: int) -> bool:
        """维度守护：既有集合维度与当前 embedding 不一致时重置为空集合并重建。

        常规切换由 payload 版本签名触发全量重建；本方法是兜底——例如 DB 不可用
        走「保留旧索引」恢复分支时，旧集合维度与新 provider 的查询向量不符，
        检索层会直接报错；这里提前清空，待数据源恢复后由同步逻辑重新填充。
        """
        current = self.current_vector_size()
        if current is None or current == int(vector_size):
            return False
        logger.warning(
            "Qdrant 集合 %s 维度与当前 embedding 不一致（%s vs %s），重置集合", self._name, current, vector_size
        )
        self._vector_size = int(vector_size)
        self.reset()
        return True

    def reset(self) -> None:
        """删除并按当前向量配置重建集合（embedding/文档版本变化时全量重建）。

        顺序是先清点位、再删集合重建：嵌入式（本地）模式在 Windows 上目录清理
        可能因文件占用静默失败（qdrant-client 用 ignore_errors=True），重建会
        挂回残留数据；而残留的旧维度向量会让新维度的查询直接抛形状不匹配错误
        （本地实现的距离计算对全体向量矩阵生效，已删除点也参与）。清点后再从
        存储重建会跳过已删除点，保证「reset 后集合为空且维度正确」。
        """
        self._client.delete(self._name, points_selector=Filter())
        self._client.delete_collection(self._name)
        self._ensure_collection()

    def query(
        self,
        *,
        vector: list[float],
        limit: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """ANN 检索：返回 (payload, cosine 相似度) 列表，按相似度降序。"""
        result = self._client.query_points(
            self._name,
            query=vector,
            limit=max(int(limit), 1),
            query_filter=_build_filter(where),
            with_payload=True,
        )
        return [(point.payload or {}, float(point.score)) for point in result.points]

    def upsert(
        self,
        ids: list[str],
        payloads: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        points = [
            PointStruct(id=_point_id(pid), vector=vector, payload=payload)
            for pid, payload, vector in zip(ids, payloads, vectors, strict=False)
        ]
        self._client.upsert(self._name, points=points)

    def delete(self, ids: list[str]) -> None:
        from qdrant_client.models import PointIdsList

        self._client.delete(
            self._name,
            points_selector=PointIdsList(points=[_point_id(pid) for pid in ids]),
        )

    def all_payloads(self) -> list[dict[str, Any]]:
        """全量扫描 payload（索引同步比对与故障恢复用；分页拉取）。"""
        payloads: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._name,
                with_payload=True,
                limit=256,
                offset=offset,
            )
            payloads.extend(point.payload or {} for point in points)
            if offset is None:
                break
        return payloads

    def count(self) -> int:
        return int(self._client.count(self._name, exact=True).count)
