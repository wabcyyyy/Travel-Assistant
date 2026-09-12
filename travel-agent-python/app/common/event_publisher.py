"""Redis Pub/Sub 进度事件发布器（AD2 SSE 链路的 Python 侧）。

职责：
- 把 Python 节点（研究阶段）的进度事件发布到通道 ``gen:events:{itineraryId}``，
  由 Java SSE 网关订阅后转发前端；与 Java 端共用同一事件信封协议，不得偏离。

协议要点（与 Java 端约定）：
- 信封 JSON 键全部 camelCase：{"type", "itineraryId", "seq", "ts", "data"}；
- seq 用 Redis ``INCR gen:seq:{itineraryId}``（每次 INCR 后 EXPIRE 7200s）保证
  跨发布方（Java/Python）单调，不能在进程内自增；
- ts 为东八区 ISO-8601（带时区偏移），与 Java 端口径一致；
- Python 只发布 research_start / research_done / degraded，其余事件归 Java。

实现要点：
- 事件是尽力而为通知（DB 才是真相）：Redis 任何异常只记日志并静默跳过，
  绝不向上抛异常影响生成主流程；itineraryId 缺失（None）时不发布；
- 客户端惰性创建 + 模块级单例：未配置 Redis 的部署在导入期零连接开销，
  reset_event_publisher 供测试隔离用例间的单例状态。
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import redis

from app.common.config import settings

logger = logging.getLogger(__name__)

# 东八区固定偏移：事件时间戳与 Java 网关统一用 CST，不依赖部署机本地时区
_TZ_CST = timezone(timedelta(hours=8))

# seq 计数键 TTL：与 Java 端一致，覆盖一次行程生成的最长会话窗口即可
_SEQ_TTL_SECONDS = 7200

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    """惰性创建并缓存 Redis 客户端（模块级单例）。

    decode_responses=True：发布的是 JSON 字符串，让 redis-py 直接收发 str，
    避免每次发布再做 bytes 编解码。
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def reset_event_publisher() -> None:
    """测试钩子：丢弃单例客户端，保证用例之间互不串状态。"""
    global _client
    _client = None


def publish_event(itinerary_id: int | None, event_type: str, data: dict,
                  run_id: str | None = None) -> None:
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
    try:
        client = _get_client()
        seq_key = f"gen:seq:{int(itinerary_id)}"
        # 先 INCR 后 EXPIRE：EXPIRE 需每次续期，计数键不能因忘记 TTL 而永久残留
        seq = client.incr(seq_key)
        client.expire(seq_key, _SEQ_TTL_SECONDS)
        # runId 属于 data 自定义区：拷贝后再合并，不污染调用方的 dict
        body = dict(data)
        if run_id:
            body["runId"] = str(run_id)
        envelope = {
            "type": event_type,
            "itineraryId": int(itinerary_id),
            "seq": int(seq),
            "ts": datetime.now(_TZ_CST).isoformat(),
            "data": body,
        }
        client.publish(f"gen:events:{int(itinerary_id)}", json.dumps(envelope, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - 通知失败不影响主流程
        logger.warning("publish %s event for itinerary %s failed: %s",
                       event_type, itinerary_id, exc)
    if run_id:
        # trace 落账与 Redis 发布成败解耦：即使发布失败，轨迹里也留痕。
        # 同样遵守尽力而为契约：落账自身失败只记日志，绝不向上抛。
        try:
            _record_stream_trace(event_type, itinerary_id, run_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("record %s stream event to trace failed: %s", event_type, exc)


def _record_stream_trace(event_type: str, itinerary_id: int, run_id: str) -> None:
    """把一次流式事件发布记入当前 trace（scene=stream）。

    延迟导入 app.agent.trace：本模块属 app.common 公共层，模块级导入会抬高
    对 Agent 层的静态依赖（防未来循环导入）；record_event 在无 trace 上下文
    时自身静默跳过，这里无需再判空。
    """
    from app.agent.trace import record_event

    record_event("stream", str(event_type), metadata={
        "event": event_type,
        "itinerary_id": int(itinerary_id),
        "run_id": str(run_id),
    })


def _forward_event(itinerary_id: int | None, event_type: str, data: dict,
                   run_id: str | None) -> None:
    """便捷函数统一转发：run_id 为空时保持旧三参调用形态（兼容既有调用方/测试桩）。"""
    if run_id:
        publish_event(itinerary_id, event_type, data, run_id=run_id)
    else:
        publish_event(itinerary_id, event_type, data)


def publish_research_start(itinerary_id: int | None, domains: list[str],
                           run_id: str | None = None) -> None:
    """研究阶段开始：告知前端本次研究覆盖的领域清单。"""
    _forward_event(itinerary_id, "research_start", {"domains": list(domains)}, run_id)


def publish_research_done(itinerary_id: int | None, evidence_count: int,
                          degraded: bool, domains: list[dict],
                          run_id: str | None = None) -> None:
    """研究阶段完成：汇报证据总量、是否降级与各域计数（camelCase 契约）。"""
    _forward_event(itinerary_id, "research_done", {
        "evidenceCount": int(evidence_count),
        "degraded": bool(degraded),
        "domains": [{"domain": str(row["domain"]), "count": int(row["count"])}
                    for row in domains],
    }, run_id)


def publish_degraded(itinerary_id: int | None, scope: str, reason: str, fallback: str,
                     run_id: str | None = None) -> None:
    """降级通知：说明哪个环节（scope）、为什么（reason）、兜底成什么样（fallback）。"""
    _forward_event(itinerary_id, "degraded", {
        "scope": scope,
        "reason": reason,
        "fallback": fallback,
    }, run_id)
