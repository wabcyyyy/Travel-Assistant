"""行程进度事件的信封与发布（AD2 SSE 链路）。

职责：
- 组装 `{type, itineraryId, seq, ts, data}` 五键信封，并同时送达两个消费者：
  进程内 SSE 总线 `app.common.event_hub`（M7-a 起 Python 自己对外提供 `/events`），
  以及 Redis 通道 ``gen:events:{itineraryId}``（双跑期 Java 网关仍在订阅）；
- 发布是尽力而为：DB 才是真相，Redis 缺席不影响本地订阅，也不影响生成主流程。

协议要点（与 Java 端约定，不得偏离）：
- 信封 JSON 键全部 camelCase：{"type", "itineraryId", "seq", "ts", "data"}；
- seq 优先取 Redis ``INCR gen:seq:{itineraryId}``（每次 INCR 后 EXPIRE 7200s），
  双跑期由 Java/Python 共用同一个计数器；Redis 不可用时退进程内自增
  （同 Java 的 fallbackSeq），保证本地事件流不断；
- ts 为东八区 ISO-8601（带时区偏移），与 Java 端口径一致。

客户端由 `app.common.redis_client` 统一惰性创建（导入期零连接开销），带 0.5s 连接超时
与 5s 熔断；reset_event_publisher 供测试隔离用例间的客户端与熔断状态。
"""

import itertools
import json
import logging
from datetime import datetime, timedelta, timezone

import redis

from app.common import event_hub, redis_client

logger = logging.getLogger(__name__)

# 东八区固定偏移：事件时间戳与 Java 网关统一用 CST，不依赖部署机本地时区
_TZ_CST = timezone(timedelta(hours=8))

# seq 计数键 TTL：与 Java 端一致，覆盖一次行程生成的最长会话窗口即可
_SEQ_TTL_SECONDS = 7200

# Redis 不可用时的进程内序号（Java 的 AtomicLong fallbackSeq 同物；CPython 下 next() 自身原子）
_fallback_seq = itertools.count(1)


def _get_client() -> redis.Redis:
    """共享快失败客户端；保留本函数作为单测注入点。

    decode_responses=True 由 `redis_client` 统一设置：发布的是 JSON 字符串，让 redis-py
    直接收发 str，避免每次发布再做 bytes 编解码。
    熔断窗口内抛 ConnectionError，由 `publish_event` 既有的静默降级分支接住——
    一条事件连不上 Redis 时不付秒级等待，也不影响生成主流程。
    """
    client = redis_client.client()
    if client is None:
        raise ConnectionError("redis circuit breaker open")
    return client


def reset_event_publisher() -> None:
    """测试钩子：丢弃共享客户端、熔断状态与进程内订阅表，保证用例之间互不串状态。"""
    redis_client.reset_for_tests()
    event_hub.reset_for_tests()


def _next_seq(itinerary_id: int) -> int:
    """事件序号：Redis INCR + 滑动 EXPIRE 7200s（与 Java 端同键同 TTL，双跑期共用计数器）。

    Redis 不可用时退进程内自增（同 Java 的 `fallbackSeq`）：M7 之后订阅方与发布方同进程，
    没有 Redis 不等于没有事件流。广播副本因此也带兜底 seq——Redis 都不通时本来就没人收。
    """
    key = f"gen:seq:{int(itinerary_id)}"
    try:
        client = _get_client()
        seq = client.incr(key)
        client.expire(key, _SEQ_TTL_SECONDS)
        return int(seq)
    except Exception as exc:
        redis_client.note_failure(exc)
        return next(_fallback_seq)


def build_envelope(
    itinerary_id: int, event_type: str, data: dict | None, *, seq: int | None = None, run_id: str | None = None
) -> str:
    """组协议信封 JSON：`{type, itineraryId, seq, ts, data}`，键序与 Java 一致。

    `runId` 属于 data 自定义区（信封五键不变），因此拷贝后再合并，不污染调用方的 dict。
    心跳与超限提示这类不承载业务语义的帧由调用方显式传 `seq=0`。
    """
    body = dict(data or {})
    if run_id:
        body["runId"] = str(run_id)
    payload = {
        "type": event_type,
        "itineraryId": int(itinerary_id),
        "seq": seq if seq is not None else _next_seq(itinerary_id),
        # 带时区 ISO-8601（+08:00）：与 Java OffsetDateTime.now() 的格式一致，不依赖部署机本地时区
        "ts": datetime.now(_TZ_CST).isoformat(),
        "data": body,
    }
    return json.dumps(payload, ensure_ascii=False)


def publish_local(itinerary_id: int, event_type: str, data: dict | None) -> str:
    """点对点直发：组信封后只投给本行程的 SSE 连接，不做 Redis 广播。

    对话流式（chat_token/chat_draft/chat_done）就是这种会话私有事件——广播给同一行程的
    其它标签页只会让它们的草稿互相覆盖。返回信封便于调用方同时落日志或再转发。
    """
    envelope = build_envelope(itinerary_id, event_type, data)
    event_hub.broadcast(int(itinerary_id), envelope)
    return envelope


def heartbeat_envelope(itinerary_id: int) -> str:
    """心跳帧：type=heartbeat、seq=0、data={}；不占业务计数器，也不进前端生成状态机。"""
    return build_envelope(itinerary_id, "heartbeat", {}, seq=0)


def too_many_connections_envelope(itinerary_id: int) -> str:
    """连接数超限提示：与 Java 网关同文案同 code；retryable=false，前端不该重连。"""
    return build_envelope(
        itinerary_id,
        "error",
        {
            "code": "TOO_MANY_CONNECTIONS",
            "message": "该行程的实时连接数已达上限，请关闭多余页面后重试",
            "retryable": False,
        },
        seq=0,
    )


def error_envelope(itinerary_id: int, code: str, message: str, retryable: bool = True) -> str:
    """SSE 侧的错误帧（AGENT_ERROR / AGENT_BUSY）：HTTP 已经是 200，错误只能走事件。"""
    return build_envelope(itinerary_id, "error", {"code": code, "message": message, "retryable": retryable})


def publish_event(itinerary_id: int | None, event_type: str, data: dict, run_id: str | None = None) -> None:
    """按协议信封发布一条事件；任何失败都静默降级为日志。

    尽力而为语义的原因：进度事件只影响前端观感，行程真相在 DB，
    发布链路故障不允许拖垮生成主流程。

    run_id（M5 流式事件落 trace，可选）：当前 Agent run 的轨迹 ID。非空时
    - 并入 data 自定义区（key=runId），五键信封结构不变，实现
      「事件 ↔ 行程 ↔ 轨迹」三向关联；
    - 以 scene=stream 落当前 trace（record_event 在无 trace 上下文时自身
      静默跳过）。
    """
    if not itinerary_id:
        # itineraryId 缺失意味着没有可订阅的会话通道，直接跳过
        return
    # 先送进程内订阅者，再尽力广播到 Redis：Redis 缺席不再等于没有进度。
    # seq 由 _next_seq 负责（Redis 共用计数器 + 进程内兜底，同 Java 的 fallbackSeq）。
    envelope = build_envelope(itinerary_id, event_type, data, run_id=run_id)
    event_hub.broadcast(int(itinerary_id), envelope)
    try:
        _get_client().publish(f"gen:events:{int(itinerary_id)}", envelope)
    except Exception as exc:
        # 这里也要喂熔断：本模块曾是唯一不报故障的 Redis 使用方，Redis 宕时每发一条事件
        # 都要重付一次连接超时；逐日编排下成本是 `天数 × 3 × 0.5s`。
        redis_client.note_failure(exc)
        logger.warning("publish %s event for itinerary %s failed: %s", event_type, itinerary_id, exc)
    if run_id:
        # trace 落账与 Redis 发布成败解耦：即使发布失败，轨迹里也留痕。
        # 同样遵守尽力而为契约：落账自身失败只记日志，绝不向上抛。
        try:
            _record_stream_trace(event_type, itinerary_id, run_id)
        except Exception as exc:
            logger.debug("record %s stream event to trace failed: %s", event_type, exc)


def _record_stream_trace(event_type: str, itinerary_id: int, run_id: str) -> None:
    """把一次流式事件发布记入当前 trace（scene=stream）。

    延迟导入 app.agent.trace：本模块属 app.common 公共层，模块级导入会抬高
    对 Agent 层的静态依赖（防未来循环导入）；record_event 在无 trace 上下文
    时自身静默跳过，这里无需再判空。
    """
    from app.agent.trace import record_event

    record_event(
        "stream",
        str(event_type),
        metadata={
            "event": event_type,
            "itinerary_id": int(itinerary_id),
            "run_id": str(run_id),
        },
    )


def _forward_event(itinerary_id: int | None, event_type: str, data: dict, run_id: str | None) -> None:
    """便捷函数统一转发：run_id 为空时保持旧三参调用形态（兼容既有调用方/测试桩）。"""
    if run_id:
        publish_event(itinerary_id, event_type, data, run_id=run_id)
    else:
        publish_event(itinerary_id, event_type, data)


def publish_research_start(itinerary_id: int | None, domains: list[str], run_id: str | None = None) -> None:
    """研究阶段开始：告知前端本次研究覆盖的领域清单。"""
    _forward_event(itinerary_id, "research_start", {"domains": list(domains)}, run_id)


def publish_research_done(
    itinerary_id: int | None, evidence_count: int, degraded: bool, domains: list[dict], run_id: str | None = None
) -> None:
    """研究阶段完成：汇报证据总量、是否降级与各域计数（camelCase 契约）。"""
    _forward_event(
        itinerary_id,
        "research_done",
        {
            "evidenceCount": int(evidence_count),
            "degraded": bool(degraded),
            "domains": [{"domain": str(row["domain"]), "count": int(row["count"])} for row in domains],
        },
        run_id,
    )


def publish_degraded(
    itinerary_id: int | None, scope: str, reason: str, fallback: str, run_id: str | None = None
) -> None:
    """降级通知：说明哪个环节（scope）、为什么（reason）、兜底成什么样（fallback）。"""
    _forward_event(
        itinerary_id,
        "degraded",
        {
            "scope": scope,
            "reason": reason,
            "fallback": fallback,
        },
        run_id,
    )
