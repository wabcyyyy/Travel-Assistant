"""行程版本：快照、列表、结构化 Diff、恢复（移植自 Java `ItineraryVersionService`）。

MyBatis-Plus 语义对齐：配了 `@TableLogic` 之后，`delete()`/`deleteById()` 实际发出的是
`UPDATE ... SET deleted = 1`，**不是物理删除**——用户侧删除路径保持这一形态，否则迁移后
的数据形态与 Java 存量不一致（历史行消失、回收/审计无从谈起）。

唯一的例外是 `restore()` 的"清旧明细"：`itinerary_day` 上有唯一键
`uk_itinerary_day_no(itinerary_id, day_no)`，软删的旧日行仍然占着键位，按快照重建同日
必然冲突。Java 侧正是踩在这条约束上——该端点前端未接线、也没有任何测试，从未成功跑通过。
这里按物理删除修复：历史真相由版本快照本身承载，重建出来的行不需要留在明细表里。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import delete, select

from app.common.envelope import ApiError
from app.db.models import ItineraryDay, ItineraryItem, ItineraryMain, ItineraryVersion
from app.db.session import session_scope
from app.services import budget_engine, itinerary_query

logger = logging.getLogger(__name__)

MAX_SUMMARY = 255


def create_snapshot(user_id: int, itinerary_id: int, operation: str | None, summary: str | None) -> dict[str, Any]:
    with session_scope() as session:
        main = itinerary_query.require_writable_main(session, user_id, itinerary_id)
        latest = _latest(session, itinerary_id)
        itinerary_query.evict_detail(user_id, itinerary_id)
        detail = itinerary_query.detail(user_id, itinerary_id)
        version = ItineraryVersion(
            itinerary_id=itinerary_id,
            user_id=user_id,
            parent_version_id=None if latest is None else latest.id,
            version_no=1 if latest is None else latest.version_no + 1,
            operation=operation or "snapshot",
            summary=(summary or "行程快照")[:MAX_SUMMARY],
            snapshot_json=json.dumps(detail, ensure_ascii=False),
        )
        session.add(version)
        session.flush()
        return {
            "id": version.id,
            "itineraryId": main.id,
            "versionNo": version.version_no,
            "parentVersionId": version.parent_version_id,
            "operation": version.operation,
            "summary": version.summary,
            "createdAt": version.created_at.isoformat() if version.created_at else None,
        }


def list_versions(user_id: int, itinerary_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        rows = (
            session.execute(
                select(ItineraryVersion)
                .where(ItineraryVersion.itinerary_id == itinerary_id)
                .order_by(ItineraryVersion.version_no.desc())
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": row.id,
            "versionNo": row.version_no,
            "parentVersionId": row.parent_version_id,
            "operation": row.operation,
            "summary": row.summary,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def diff(user_id: int, itinerary_id: int, from_id: int, to_id: int) -> dict[str, Any]:
    with session_scope() as session:
        _require_main(session, user_id, itinerary_id)
        before_row, after_row = _require(session, itinerary_id, from_id), _require(session, itinerary_id, to_id)
    try:
        before = json.loads(before_row.snapshot_json)
        after = json.loads(after_row.snapshot_json)
    except (ValueError, TypeError) as exc:
        raise ApiError(500, "行程版本 Diff 失败") from exc

    changes: list[dict[str, Any]] = []
    for field in ("city", "days", "budget"):
        if before.get(field) != after.get(field):
            changes.append({"type": "updated", "key": field, "before": before.get(field), "after": after.get(field)})
    before_items = _item_index(before.get("dayList") or [])
    after_items = _item_index(after.get("dayList") or [])
    for key, value in before_items.items():
        if key not in after_items:
            changes.append({"type": "removed", "key": key, "before": value, "after": None})
    for key, value in after_items.items():
        if key not in before_items:
            changes.append({"type": "added", "key": key, "before": None, "after": value})
        elif before_items[key] != value:
            changes.append({"type": "updated", "key": key, "before": before_items[key], "after": value})
    return {"fromVersionId": from_id, "toVersionId": to_id, "changes": changes}


def restore(user_id: int, itinerary_id: int, version_id: int) -> dict[str, Any]:
    version_no: int
    with session_scope() as session:
        main = itinerary_query.require_writable_main(session, user_id, itinerary_id)
        version = _require(session, itinerary_id, version_id)
        try:
            snapshot = json.loads(version.snapshot_json)
        except (ValueError, TypeError) as exc:
            raise ApiError(500, "行程版本内容损坏") from exc
        version_no = version.version_no

        # 物理删除（见模块 docstring 的例外说明）：软删会让 uk_itinerary_day_no 被旧行占住
        session.execute(delete(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary_id))
        session.execute(delete(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id))

        main.title = snapshot.get("title")
        main.city = snapshot.get("city")
        main.start_date = _as_date(snapshot.get("startDate"))
        main.end_date = _as_date(snapshot.get("endDate"))
        main.days = snapshot.get("days")
        main.persons = snapshot.get("persons")
        main.budget = snapshot.get("budget")
        main.preferences = snapshot.get("preferences")
        main.hotel_tier = snapshot.get("hotelTier")
        main.stay_nights = snapshot.get("stayNights")

        for day_snapshot in snapshot.get("dayList") or []:
            day = ItineraryDay(
                itinerary_id=itinerary_id,
                day_no=day_snapshot.get("dayNo"),
                travel_date=_as_date(day_snapshot.get("travelDate")),
                city=snapshot.get("city"),
                note=day_snapshot.get("note"),
                metadata_json=_metadata_json(day_snapshot),
                generation_status="SUCCEEDED",
            )
            session.add(day)
            session.flush()
            for sort, item_snapshot in enumerate(day_snapshot.get("items") or []):
                session.add(
                    ItineraryItem(
                        itinerary_id=itinerary_id,
                        day_id=day.id,
                        item_type=item_snapshot.get("itemType"),
                        poi_name=item_snapshot.get("poiName"),
                        poi_id=item_snapshot.get("poiId"),
                        address=item_snapshot.get("address"),
                        latitude=item_snapshot.get("latitude"),
                        longitude=item_snapshot.get("longitude"),
                        start_time=_as_time(item_snapshot.get("startTime")),
                        end_time=_as_time(item_snapshot.get("endTime")),
                        duration_min=item_snapshot.get("durationMin"),
                        cost=item_snapshot.get("cost"),
                        tag=item_snapshot.get("tag"),
                        remark=item_snapshot.get("remark"),
                        open_time=item_snapshot.get("openTime"),
                        image_url=item_snapshot.get("imageUrl"),
                        source=item_snapshot.get("source"),
                        source_updated_at=_as_datetime(item_snapshot.get("sourceUpdatedAt")),
                        verification_status=item_snapshot.get("verificationStatus"),
                        value_kind=item_snapshot.get("valueKind"),
                        freshness_status=item_snapshot.get("freshnessStatus"),
                        review_requirement=item_snapshot.get("reviewRequirement"),
                        fact_evidence_json=item_snapshot.get("factEvidenceJson"),
                        intro=item_snapshot.get("intro"),
                        sort_no=sort,
                    )
                )
        session.flush()
        budget_engine.recalculate(itinerary_id)

    itinerary_query.evict_detail(user_id, itinerary_id)
    create_snapshot(user_id, itinerary_id, "restore", f"恢复到版本 {version_no}")
    return itinerary_query.detail(user_id, itinerary_id)


def _metadata_json(day_snapshot: dict[str, Any]) -> str | None:
    metadata: dict[str, Any] = {}
    if day_snapshot.get("theme") is not None:
        metadata["theme"] = day_snapshot["theme"]
    for key in ("miniRoute", "backupPlan", "photoSpots", "practicalNotes"):
        value = day_snapshot.get(key)
        if value:
            metadata[key] = value
    # 与 Java 同：dayOptions 不在恢复白名单里，恢复后该槽位会丢失（已知行为，非缺陷）
    return json.dumps(metadata, ensure_ascii=False) if metadata else None


def _require_main(session, user_id: int, itinerary_id: int) -> ItineraryMain:
    """版本读路径（list/diff）：owner 或协作成员可读（SPEC C2.3）。"""
    return itinerary_query.require_main(session, user_id, itinerary_id)


def _latest(session, itinerary_id: int) -> ItineraryVersion | None:
    return session.execute(
        select(ItineraryVersion)
        .where(ItineraryVersion.itinerary_id == itinerary_id)
        .order_by(ItineraryVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()


def _require(session, itinerary_id: int, version_id: int) -> ItineraryVersion:
    version = session.get(ItineraryVersion, version_id)
    if version is None or version.itinerary_id != itinerary_id:
        raise ApiError(404, "行程版本不存在")
    return version


def _item_index(days: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for day in days:
        day_no = day.get("dayNo")
        for item in day.get("items") or []:
            key = f"{day_no}:{item.get('id') if item.get('id') is not None else item.get('poiName')}"
            index[key] = item
    return index


def _as_date(value: Any) -> date | None:
    return None if value is None else date.fromisoformat(str(value)[:10])


def _as_time(value: Any) -> time | None:
    if value is None:
        return None
    parts = [int(p) for p in str(value).split(":")]
    return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def _as_datetime(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))
