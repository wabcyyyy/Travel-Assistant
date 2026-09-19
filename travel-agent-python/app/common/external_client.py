"""外部调用基类（G-3.2）：超时 / 响应上限 / TTL 缓存 / 自节流 / key 解析链。

适用面：三处对外取数——图片查找（Unsplash / Wikipedia）、实时价格（酒店/餐饮
的联网核价）、联网搜索补池。它们此前各写各的：有的裸 `httpx.get`（超时是有，
但没有缓存、没有节流、没有响应字节上限），有的经 llm_client（有超时，同样
无缓存无节流）。本基类把这五件事收成一处，调用方只提供"怎么取数"。

五项能力（INV-9 的落地形态）：
1. **超时**：每个调用都有明确上限（`timeout_seconds`），由 loader 使用；
2. **响应字节上限**：`clamp_bytes` 用于 httpx 通道（超限即拒，不截断后当成功）；
   LLM 通道由 `max_tokens` 承担，调用方在 loader 里设；
3. **TTL 缓存**：命中即返回，不打网络；**负结果用更短 TTL**（查不到要能较快重试，
   查得到的结果可以缓存久些）；
4. **自节流（双车道）**：interactive（用户在等，间隔短）与 background（后台补池，
   间隔长）；等待超过 `max_wait_seconds` 就**放弃本次调用**（返回 None），
   绝不把后台补池拖成前台阻塞；
5. **key 解析链**：env → 实例配置 → 调用方自带，逐级回落；**绝不复用他人的 key**
   （`resolve_key` 只在自己这一串里选，不跨实例借用）。

线程安全：缓存与车道时间戳都加锁（生成跑在 worker 线程，管理面在主线程）。

依赖：标准库（threading/time/logging/json）+ httpx（只为 `fetch_bytes`/`fetch_json`
两个外呼助手签名与超时服务）；具体的 loader 仍由调用方注入。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

INTERACTIVE = "interactive"
BACKGROUND = "background"

#: 车道最小调用间隔（秒）：前台已可容忍短等待，后台补池应明显更克制。
_LANE_MIN_INTERVAL: dict[str, float] = {INTERACTIVE: 0.2, BACKGROUND: 1.0}


@dataclass
class ExternalClient(Generic[T]):
    """一个外部数据源的取数门面（泛型参数 = 成功返回的类型）。"""

    name: str
    #: 成功结果 TTL（秒）
    ttl_seconds: float = 900.0
    #: 负结果（None / 空列表）TTL（秒）：更短，保证"供应商暂时挂了"能较快重试
    negative_ttl_seconds: float = 60.0
    #: 响应字节上限（httpx 通道用 clamp_bytes；LLM 通道由 max_tokens 承担）
    max_response_bytes: int = 256 * 1024
    #: 进程内缓存条目上限：高基数键（点位名、坐标串）在长跑进程里必须有界（R2-10）
    max_entries: int = 2048
    #: 单次调用超时（秒）：由 `fetch_json`/`fetch_bytes` 真正传给 httpx（per-request
    #: 覆盖共享客户端的默认超时）。以前它只是声明，调用点各写各的。
    timeout_seconds: float = 8.0
    #: 节流等待上限（秒）：超过即放弃本次调用（不自旋、不阻塞车道）
    max_wait_seconds: float = 1.5
    #: 本实例的车道最小间隔覆盖（秒）：个别供应商有硬性限流（如 Nominatim 1 rps），
    #: 需要比车道默认值更保守的间隔；None = 沿用车道默认。
    min_interval_seconds: float | None = None

    _cache: dict[str, tuple[Any, float]] = field(default_factory=dict, init=False, repr=False)
    _lane_last: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ---- key 解析链 -------------------------------------------------------

    @staticmethod
    def resolve_key(*candidates: str | None) -> str | None:
        """按 env → 实例配置 → 调用方自带 的顺序取第一个非空 key。

        只在本链内回落：任何一级都不去"借用"别处的凭据（G-3.2 硬约束）。
        """
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None

    # ---- 缓存 -------------------------------------------------------------

    def _is_negative(self, value: Any) -> bool:
        return value is None or (isinstance(value, list) and not value)

    def _cached(self, cache_key: str) -> tuple[bool, Any]:
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return False, None
            value, expires_at = entry
            if expires_at <= time.monotonic():
                self._cache.pop(cache_key, None)
                return False, None
            return True, value

    def _store(self, cache_key: str, value: Any) -> None:
        ttl = self.negative_ttl_seconds if self._is_negative(value) else self.ttl_seconds
        if ttl <= 0:
            return
        with self._lock:
            self._cache[cache_key] = (value, time.monotonic() + ttl)
            if len(self._cache) <= self.max_entries:
                return
            # 与 cache_store 的兜底表同理：高基数键（POI 名、坐标串）+ 长跑进程 = 无界增长。
            # 先清过期，仍超限按最早到期逐出（不含刚写入的这条）。
            now = time.monotonic()
            for key in [k for k, (_v, exp) in self._cache.items() if exp <= now]:
                self._cache.pop(key, None)
            overflow = len(self._cache) - self.max_entries
            if overflow > 0:
                candidates = sorted((k for k in self._cache if k != cache_key), key=lambda k: self._cache[k][1])
                for key in candidates[:overflow]:
                    self._cache.pop(key, None)

    def clear_cache(self) -> None:
        """测试/管理用：清空缓存（便于断言"真的又打了一次"）。"""
        with self._lock:
            self._cache.clear()

    # ---- 节流 -------------------------------------------------------------

    def _acquire_slot(self, lane: str) -> bool:
        """按车道最小间隔等待；超过 max_wait_seconds 放弃（返回 False）。

        选择"放弃"而不是"无限等待"：后台补池撞上节流时应当快速跳过，
        否则一次生成会被外部依赖的节奏拖住。
        """
        interval = self.min_interval_seconds or _LANE_MIN_INTERVAL.get(lane, _LANE_MIN_INTERVAL[BACKGROUND])
        with self._lock:
            now = time.monotonic()
            last = self._lane_last.get(lane, 0.0)
            wait = interval - (now - last)
            if wait > self.max_wait_seconds:
                logger.info("external[%s] throttled on %s lane (wait %.2fs)", self.name, lane, wait)
                return False
            if wait > 0:
                time.sleep(wait)
            self._lane_last[lane] = time.monotonic()
            return True

    # ---- 取数 -------------------------------------------------------------

    def call(
        self,
        cache_key: str,
        loader: Callable[[], T | None],
        *,
        lane: str = INTERACTIVE,
    ) -> T | None:
        """缓存 → 节流 → loader 的取数流程；任何异常都降级为 None（不打断生成）。"""
        hit, value = self._cached(cache_key)
        if hit:
            return value
        if not self._acquire_slot(lane):
            return None
        try:
            result = loader()
        except Exception as exc:
            logger.warning("external[%s] call failed (%s): %s", self.name, cache_key, exc)
            result = None
        self._store(cache_key, result)
        return result

    def clamp_bytes(self, payload: bytes | str | None) -> bytes | None:
        """响应字节上限：超限返回 None（拒收），不做"截断后当成功"。

        截断的 JSON/HTML 交给上层解析只会产出脏数据，不如让调用方走降级。
        """
        if payload is None:
            return None
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(data) > self.max_response_bytes:
            logger.warning("external[%s] response too large: %d > %d", self.name, len(data), self.max_response_bytes)
            return None
        return data


def fetch_bytes(
    client: ExternalClient[Any],
    http: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> bytes | None:
    """INV-9 的真实执行点：GET/POST → 本 client 的 per-request 超时 → 状态检查 → 字节上限。

    为什么要有这个函数：`timeout_seconds`/`max_response_bytes` 过去只是**声明**，调用点
    各写各的 `api_client().get(...).json()`——于是"每个外呼都有超时与响应上限"这条
    纪律只在图片通道成立，结构化 JSON 通道（OTM/Nominatim/Open-Meteo）三条都没上限。
    `json_body` 走 POST：给需要请求体的现代 API（Places 一类）留的口，纪律不变。
    """
    if json_body is not None:
        response = http.post(url, json=json_body, params=params, headers=headers, timeout=client.timeout_seconds)
    else:
        response = http.get(url, params=params, headers=headers, timeout=client.timeout_seconds)
    response.raise_for_status()
    return client.clamp_bytes(response.content)


def fetch_json(
    client: ExternalClient[Any],
    http: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """`fetch_bytes` + JSON 解析；形状是否可用由调用方判（None = 降级，不冒充数据）。"""
    raw = fetch_bytes(client, http, url, params=params, headers=headers, json_body=json_body)
    if raw is None:
        return None
    return json.loads(raw)
