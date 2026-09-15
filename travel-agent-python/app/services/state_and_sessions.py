"""滑动窗口限速与会话登记（与 Java `DistributedStateService`/`UserSessionService` 共享键）。

为什么这两类必须共享而缓存必须隔离（见 cache_store 的 `py:` 前缀）：
- 限速用 Redis ZSET，**member 内容任意、score 是 epoch 毫秒**，Java 写的成员 Python
  读得到、反之亦然 → 双跑期不会因为换了服务就"清零额度"，那会让暴力破解重试预算翻倍；
- 会话是 SET(jti) + 字符串(jti→token)，都是纯文本，无序列化格式问题；
- 缓存 value 是 Jackson 多态 JSON（带 `com.travel.backend.` 包名），跨语言读不了，只能各自命名空间。

Redis 不可用时降级为进程内实现（单机演示有效），与 Java 同语义。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque

from app.common import redis_client

logger = logging.getLogger(__name__)

LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES = 5
MAX_REGISTER_ATTEMPTS = 5
SESSION_KEY_PREFIX = "auth:sess:"

_lock = threading.Lock()
_windows: dict[str, deque[float]] = {}
_marks: dict[str, float] = {}
_session_sets: dict[str, set[str]] = {}
_jti_to_token: dict[str, str] = {}


def _redis():
    """共享快失败客户端；熔断窗口内抛 ConnectionError，由调用方兜底分支接住。"""
    client = redis_client.client()
    if client is None:
        raise ConnectionError("redis circuit breaker open")
    return client


def _note_redis_failure(exc: BaseException, message: str) -> None:
    """登记故障开熔断，并按「每个窗口只告警一次」记录。

    熔断窗口内的失败是我们主动不再探测的结果，每请求刷一条 WARNING 会把真正的
    Redis 故障埋在噪音里。
    """
    already_down = redis_client.is_down()
    redis_client.note_failure(exc)
    logger.log(logging.DEBUG if already_down else logging.WARNING, message, exc)


def login_fail_key(ip: str, username: str) -> str:
    """键格式与 Java `UserServiceImpl` 完全一致：`auth:login:fail:{ip}|{username}`。"""
    return f"auth:login:fail:{ip}|{username}"


def register_key(ip: str) -> str:
    return f"auth:register:{ip}"


# ---------- 滑动窗口 ----------


def sliding_hit(key: str, window_seconds: int) -> int:
    """记一次事件，返回窗口内事件数（含本次）。"""
    now = time.time()
    try:
        zset = _redis().zset
        member = f"{int(now * 1000)}:{uuid.uuid4().hex[:8]}"
        zset.add(key, {member: now * 1000})
        zset.remrangebyscore(key, 0, (now - window_seconds) * 1000)
        _redis().expire(key, window_seconds + 1)
        return int(zset.card(key) or 0)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("sliding_hit redis fallback (%s): %s", key, exc)
    with _lock:
        queue = _windows.setdefault(key, deque())
        queue.append(now)
        cutoff = now - window_seconds
        while queue and queue[0] <= cutoff:
            queue.popleft()
        return len(queue)


def sliding_count(key: str, window_seconds: int) -> int:
    try:
        now = time.time()
        return int(_redis().zcount(key, (now - window_seconds) * 1000, "+inf") or 0)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("sliding_count redis fallback (%s): %s", key, exc)
    with _lock:
        queue = _windows.get(key)
        if not queue:
            return 0
        cutoff = time.time() - window_seconds
        return sum(1 for ts in queue if ts > cutoff)


def reset_counter(key: str) -> None:
    try:
        _redis().delete(key)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("reset_counter redis fallback (%s): %s", key, exc)
    with _lock:
        _windows.pop(key, None)


# ---------- 一次性标记（SETNX + TTL） ----------
# 移植自 Java `DistributedStateService.tryMark/isMarked/unmark`：生成日锁与恢复去重锁都靠它。
# Redis 可用时跨实例互斥；不可用时退回进程内 map（仅单机有效），与 Java 同语义。


def try_mark(key: str, ttl_seconds: int) -> bool:
    """占位成功返回 True；已被占用返回 False（**不**续期别人的占用）。

    Redis 的答复就是权威结论（与 Java `setIfAbsent` 后「非 null 即返回」一致），
    只有拿不到答复（异常或 null）才退回进程内 map。
    """
    try:
        acquired = _redis().set(key, "1", nx=True, ex=int(ttl_seconds))
        if acquired is not None:
            return bool(acquired)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("try_mark redis fallback (%s): %s", key, exc)
    return _try_mark_local(key, ttl_seconds)


def _try_mark_local(key: str, ttl_seconds: int) -> bool:
    now = time.time()
    with _lock:
        expires_at = _marks.get(key)
        if expires_at is None or expires_at < now:
            _marks[key] = now + ttl_seconds
            return True
    return False


def is_marked(key: str) -> bool:
    try:
        return bool(_redis().exists(key))
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("is_marked redis fallback (%s): %s", key, exc)
    with _lock:
        expires_at = _marks.get(key)
        if expires_at is None:
            return False
        if expires_at < time.time():
            _marks.pop(key, None)
            return False
        return True


def unmark(key: str) -> None:
    try:
        _redis().delete(key)
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("unmark redis fallback (%s): %s", key, exc)
    # 无论 Redis 是否删成功，本地占用都要撤掉：否则 Redis 故障期间占的锁永远放不下
    with _lock:
        _marks.pop(key, None)


# ---------- 多端会话 ----------


def register_session(username: str, jti: str, token: str, ttl_seconds: int) -> None:
    if not username or not jti or not token or ttl_seconds <= 0:
        return
    try:
        redis = _redis()
        key = SESSION_KEY_PREFIX + username
        redis.sadd(key, jti)
        redis.expire(key, ttl_seconds)
        redis.set(f"{SESSION_KEY_PREFIX}tok:{jti}", token, ex=ttl_seconds)
        return
    except Exception as exc:
        _note_redis_failure(exc, "session register redis failed, local fallback: %s")
    with _lock:
        _session_sets.setdefault(username, set()).add(jti)
        _jti_to_token[jti] = token


def revoke_current(username: str, jti: str, token: str, ttl_seconds: int) -> None:
    from app.common import token_revocation

    token_revocation.revoke(token, ttl_seconds)
    try:
        redis = _redis()
        redis.srem(SESSION_KEY_PREFIX + username, jti)
        redis.delete(f"{SESSION_KEY_PREFIX}tok:{jti}")
        return
    except Exception as exc:
        redis_client.note_failure(exc)
        logger.debug("revoke_current redis fallback: %s", exc)
    with _lock:
        _session_sets.get(username, set()).discard(jti)
        _jti_to_token.pop(jti, None)


def revoke_all(username: str) -> int:
    """吊销该用户全部已登记会话，返回吊销数。"""
    from app.common import token_revocation

    revoked = 0
    try:
        redis = _redis()
        key = SESSION_KEY_PREFIX + username
        for jti in list(redis.smembers(key) or set()):
            token = redis.get(f"{SESSION_KEY_PREFIX}tok:{jti}")
            if token:
                token_revocation.revoke(token, 86_400)  # 拿不到剩余寿命，按 1 天兜底（同 Java）
                revoked += 1
            redis.delete(f"{SESSION_KEY_PREFIX}tok:{jti}")
        redis.delete(key)
        return revoked
    except Exception as exc:
        _note_redis_failure(exc, "logout-all redis failed, local fallback: %s")
    with _lock:
        for jti in _session_sets.pop(username, set()) or set():
            token = _jti_to_token.pop(jti, None)
            if token:
                token_revocation.revoke(token, 86_400)
                revoked += 1
    return revoked


def list_jtis(username: str) -> list[str]:
    try:
        return sorted(_redis().smembers(SESSION_KEY_PREFIX + username) or set())
    except Exception as exc:
        redis_client.note_failure(exc)
        with _lock:
            return sorted(_session_sets.get(username, set()))


def reset_for_tests() -> None:
    with _lock:
        _windows.clear()
        _marks.clear()
        _session_sets.clear()
        _jti_to_token.clear()
    redis_client.reset_for_tests()
