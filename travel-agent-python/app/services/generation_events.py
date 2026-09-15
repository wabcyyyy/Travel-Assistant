"""行程生成进度事件（事件类型表移植自 Java `ItineraryEventPublisher`）。

信封 `{type, itineraryId, seq, ts, data}` 与通道 `gen:events:{itineraryId}` 由
`app/common/event_publisher.py` 负责；本模块只钉 `data` 的**键名与取值口径**，因为
双跑期订阅方仍是 Java 的 SSE 网关（M7 才进程内化）——它按这些键渲染前端事件，
改一个键名就是前端少一格进度。

事件是尽力而为：DB 才是真相，发布失败只记日志（见 `publish_event`）。
"""

from __future__ import annotations

from typing import Any

from app.common.event_publisher import publish_event


def day_start(itinerary_id: int, day_no: int) -> None:
    publish_event(itinerary_id, "day_start", {"dayNo": int(day_no)})


def day_done(itinerary_id: int, day_no: int, theme: str | None, item_count: int, note: str | None) -> None:
    publish_event(
        itinerary_id,
        "day_done",
        {
            "dayNo": int(day_no),
            "theme": theme,
            "itemCount": int(item_count),
            "note": note,
        },
    )


def degraded(itinerary_id: int, scope: str, reason: str | None, fallback: str) -> None:
    """降级通知。`scope` 形状固定：`day_{n}` / `research` / `butler` / `poi_intros`。"""
    publish_event(
        itinerary_id,
        "degraded",
        {
            "scope": scope,
            "reason": reason,
            "fallback": fallback,
        },
    )


def error(itinerary_id: int, code: str, message: str | None, retryable: bool) -> None:
    publish_event(
        itinerary_id,
        "error",
        {
            "code": code,
            "message": message,
            "retryable": bool(retryable),
        },
    )


def complete(
    itinerary_id: int, status: str, day_count: int | None, degraded_days: list[int], version_id: int | None
) -> None:
    """终态事件：前端据此停止监听。`status` 只有 COMPLETED / PARTIAL 两值。"""
    publish_event(
        itinerary_id,
        "complete",
        {
            "status": status,
            "dayCount": day_count,
            "degradedDays": [int(day_no) for day_no in (degraded_days or [])],
            "versionId": version_id,
        },
    )


def butler_note(itinerary_id: int, length: int, preview: str) -> None:
    """管家讲解写回成功。事件体只带长度与 ≤60 字预览，不携带长文本。"""
    payload: dict[str, Any] = {"length": int(length), "preview": preview}
    publish_event(itinerary_id, "butler_note", payload)


def export_done(itinerary_id: int, task_id: int, status: str, download_url: str) -> None:
    """PDF 导出完成：前端可据此停止轮询 `GET /api/export/tasks/{id}`。"""
    publish_event(
        itinerary_id,
        "export_done",
        {
            "taskId": int(task_id),
            "status": status,
            "downloadUrl": download_url,
        },
    )
