"""带命名空间的键值缓存（Redis 优先，故障降级进程内）。

双跑期隔离原因（PLAN v3.0 §1.3）：Java 侧 `RedisCacheConfig` 用 Jackson 多态序列化并
白名单 `com.travel.backend.` 包名，Python **无法反序列化** Java 写的 value。因此
本模块统一给 key 加 `py:` 前缀，两侧各用各的命名空间、各自独占失效权，
避免"看起来共享、实际互相看不见"的诡异缓存行为。

语义对齐 Java：`amap:poi` TTL 1 小时；空结果也缓存（防穿透），用哨兵值表示。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

from app.common import redis_client

logger = logging.getLogger(__name__)

KEY_PREFIX = "py:"
_EMPTY_SENTINEL = "\x00empty"

_local: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _get_client():
    """共享快失败客户端；保留本函数作为单测注入点。

    熔断窗口内抛 ConnectionError，让下面三个命令既有的 `except Exception` 分支
    走进程内兜底——降级路径与 Redis 真故障时完全一致。
    """
    client = redis_client.client()
    if client is None:
        raise ConnectionError("redis circuit breaker open")
    return client


def full_key(namespace: str, key: str) -> str:
    return f"{KEY_PREFIX}{namespace}:{key}"


def get_json(namespace: str, key: str) -> Optional[Any]:
    """返回缓存值；未命中返回 None。空结果哨兵转成 None（调用方按未命中处理但不再打外网）。"""
    full = full_key(namespace, key)
    try:
        raw = _get_client().get(full)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("cache redis miss/unavailable (%s): %s", namespace, exc)
        raw = _local_get(full)
    if raw is None:
        return None
    if raw == _EMPTY_SENTINEL:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def set_json(namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
    full = full_key(namespace, key)
    raw = _EMPTY_SENTINEL if value is None else json.dumps(value, ensure_ascii=False, default=str)
    try:
        _get_client().set(full, raw, ex=int(ttl_seconds))
        return
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("cache redis write failed, fallback local (%s): %s", namespace, exc)
    with _lock:
        _local[full] = (time.time() + ttl_seconds, raw)


def delete(namespace: str, key: str) -> None:
    """精确失效一个键（写路径用；不做整片清空）。"""
    full = full_key(namespace, key)
    try:
        _get_client().delete(full)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("cache delete redis fallback (%s): %s", namespace, exc)
    with _lock:
        _local.pop(full, None)


def reset_for_tests() -> None:
    with _lock:
        _local.clear()
    redis_client.reset_for_tests()


def _local_get(full: str) -> Optional[str]:
    with _lock:
        entry = _local.get(full)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at < time.time():
            _local.pop(full, None)
            return None
        return raw
