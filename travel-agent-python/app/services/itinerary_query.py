"""行程读路径（移植自 Java `ItineraryQueryService`）。

VO 字段名逐字保留（`schemaVersion`/`whyThis`/`factEvidence`/`dayOptions`/…）：
前端 `src/types/itinerary.ts` 按这些键取值，改名是**静默**的字段丢失。

三条容易丢的语义，都在这里显式实现并注释了原因：
1. 整条行程的点位**一次查出再分组**（避免按天 N+1）；预算合计用一次 `IN` 查询；
2. `stayNights` 以主表落库值为准，缺失才回落 `天数-1`——按"有酒店项的天数"反推会
   少算最后一晚（退房日没有酒店项）；
3. `qualityStatus` 的判定顺序（BLOCKED → DRAFT → 空 → STALE → READY/WARNINGS）
   依赖 days 与 items 的原始行，不能只看最终 status 字段。

时间序列化按 Jackson `ISO_LOCAL_TIME` / `ISO_LOCAL_DATE_TIME` 的"零分量省略"行为，
否则 Java 发 "09:30"、Python 发 "09:30:00"，前端切片显示会出现不一致。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.common.envelope import ApiError
from app.common.vo_json import iso_date, iso_datetime, iso_time, number
from app.db.models import BudgetDetail, ItineraryDay, ItineraryItem, ItineraryMain, PoiKnowledge
from app.db.session import session_scope
from app.services import cache_store

logger = logging.getLogger(__name__)

DETAIL_CACHE_NAMESPACE = "itinerary:detail"
DETAIL_CACHE_TTL_SECONDS = 600  # 与 Java RedisCacheConfig 的 itinerary:detail 10min 一致
QUALITY_RULE_VERSION = "travel-quality-1.0"
SCHEMA_VERSION = "1.0"

_INCOMPLETE_DAY_STATUSES = {"PENDING", "RUNNING"}
_FAILED_DAY_STATUSES = {"FAILED", "TIMED_OUT_UNKNOWN"}
# 列表视图白名单（SPEC v2.3 §6.5）：favorite/archived 之外的档位都排除归档行
_LIST_VIEWS = {"all", "active", "done", "favorite", "archived"}


_iso_time = iso_time
_iso_datetime = iso_datetime
_iso_date = iso_date
_num = number


def _loads_object(raw: str | None) -> dict[str, Any] | None:
    """损坏的可选 JSON 列不应阻塞详情读取（Java 同样降级为 null 并记日志）。"""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("json column parse failed, returned null instead")
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if item is not None]


def _as_map(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_map_list(value: Any) -> list[dict[str, Any]] | None:
    return value if isinstance(value, list) else None


def require_main(session, user_id: int, itinerary_id: int) -> ItineraryMain:
    """归属校验：不是自己的行程同样报 404，不暴露资源是否存在（同 Java）。"""
    main = session.get(ItineraryMain, itinerary_id)
    if main is None or main.user_id != user_id:
        raise ApiError(404, "行程不存在")
    return main


def next_sort(session, day_id: int | None) -> int:
    """某日末尾位次：`max(sort_no) + 1`，空日为 0。

    只留这一份实现——Java 在 `ItineraryCommandService:399` 与 `ItineraryPlanApplyService:320`
    各写了一份同名 `nextSort`，这类原语一旦分叉就会出现「同一天里两个入口算出不同顺序」。
    """
    highest = session.execute(
        select(func.max(ItineraryItem.sort_no)).where(ItineraryItem.day_id == day_id)
    ).scalar_one_or_none()
    return int(highest if highest is not None else -1) + 1


def find_owned_main(user_id: int, itinerary_id: int) -> ItineraryMain:
    """归属校验 + 取主表实体（同 Java `findOwnedMain`）。

    **不要 expunge**：写路径常在同一个事务里先取实体、再打快照（`create_snapshot` →
    `detail` → 这里），一旦 expunge，调用方手里那个实例就脱离会话，之后对它的赋值
    会被静默丢弃——不报错、不落库。MyBatis 没有这个坑（`updateById` 是显式 UPDATE）。
    离开会话后仍可安全读属性，是因为 sessionmaker 配了 `expire_on_commit=False`。
    """
    with session_scope() as session:
        return require_main(session, user_id, itinerary_id)


def find_owned_item(user_id: int, item_id: int) -> ItineraryItem:
    with session_scope() as session:
        item = session.get(ItineraryItem, item_id)
        if item is None:
            raise ApiError(404, "行程项不存在")
        itinerary_id = item.itinerary_id
    find_owned_main(user_id, itinerary_id)
    return item


def list_summaries(user_id: int, view: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    """行程列表（id 倒序、无分页）。view/q 语义见 SPEC v2.3 §6.5。

    `active` 必须含 `gen_state IS NULL` 分支：NULL 是迁移前存量（V1 DDL 注释），
    漏掉会让老行程从「计划中」里凭空消失；归档语义独立——`archived` 档只列归档，
    其余档位（含 favorite）一律排除归档行。
    """
    normalized_view = (view or "all").strip() or "all"
    if normalized_view not in _LIST_VIEWS:
        raise ApiError(400, f"无效的视图过滤：{normalized_view}")
    keyword = (q or "").strip()

    with session_scope() as session:
        stmt = select(ItineraryMain).where(ItineraryMain.user_id == user_id)
        if normalized_view == "archived":
            stmt = stmt.where(ItineraryMain.archived.is_(True))
        else:
            stmt = stmt.where(ItineraryMain.archived.is_(False))
            if normalized_view == "active":
                stmt = stmt.where(or_(ItineraryMain.gen_state.is_(None), ItineraryMain.gen_state != "COMPLETED"))
            elif normalized_view == "done":
                stmt = stmt.where(ItineraryMain.gen_state == "COMPLETED")
            elif normalized_view == "favorite":
                stmt = stmt.where(ItineraryMain.favorite.is_(True))
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(or_(ItineraryMain.title.like(pattern), ItineraryMain.city.like(pattern)))
        mains = session.execute(stmt.order_by(ItineraryMain.id.desc())).scalars().all()
        if not mains:
            return []
        totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        budgets = (
            session.execute(select(BudgetDetail).where(BudgetDetail.itinerary_id.in_([main.id for main in mains])))
            .scalars()
            .all()
        )
        for detail in budgets:
            totals[detail.itinerary_id] += detail.amount or Decimal("0")
        return [
            {
                "id": main.id,
                "title": main.title,
                "city": main.city,
                "startDate": _iso_date(main.start_date),
                "endDate": _iso_date(main.end_date),
                "days": main.days,
                "persons": main.persons,
                "budget": _num(main.budget),
                "totalAmount": float(totals.get(main.id, Decimal("0"))),
                "status": main.status,
                "tripTheme": main.trip_theme,
                # S1：封面/收藏/归档/分享态（hasShare 只回布尔，token 不下发列表）
                "coverUrl": main.cover_url,
                "coverSource": main.cover_source,
                "coverCredit": _loads_object(main.cover_credit),
                "favorite": bool(main.favorite),
                "archived": bool(main.archived),
                "hasShare": main.share_token is not None,
                "createdAt": _iso_datetime(main.created_at),
            }
            for main in mains
        ]


def detail(user_id: int, itinerary_id: int) -> dict[str, Any]:
    cache_key = f"{user_id}:{itinerary_id}"
    cached = cache_store.get_json(DETAIL_CACHE_NAMESPACE, cache_key)
    if cached is not None:
        return cached
    payload = _build_detail(user_id, itinerary_id)
    cache_store.set_json(DETAIL_CACHE_NAMESPACE, cache_key, payload, DETAIL_CACHE_TTL_SECONDS)
    return payload


def evict_detail(user_id: int, itinerary_id: int) -> None:
    """写路径的精确失效（对应 Java 侧生成链路的 evictDetailCache；不用 allEntries）。"""
    cache_store.delete(DETAIL_CACHE_NAMESPACE, f"{user_id}:{itinerary_id}")


def _build_detail(user_id: int, itinerary_id: int) -> dict[str, Any]:
    main = find_owned_main(user_id, itinerary_id)
    with session_scope() as session:
        days = (
            session.execute(
                select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id).order_by(ItineraryDay.day_no)
            )
            .scalars()
            .all()
        )
        # 一次查全部点位再按天分组：按天循环查询会产生 N+1
        items = (
            session.execute(
                select(ItineraryItem)
                .where(ItineraryItem.itinerary_id == itinerary_id)
                .order_by(ItineraryItem.day_id, ItineraryItem.sort_no)
            )
            .scalars()
            .all()
        )
        budgets = session.execute(select(BudgetDetail).where(BudgetDetail.itinerary_id == itinerary_id)).scalars().all()

        names = sorted({item.poi_name for item in items if item.poi_name and item.poi_name.strip()})
        descriptions: dict[str, str | None] = {}
        if names:
            rows = session.execute(
                select(PoiKnowledge.name, PoiKnowledge.description).where(
                    PoiKnowledge.city == main.city, PoiKnowledge.name.in_(names)
                )
            ).all()
            descriptions = {row[0]: row[1] for row in rows}

    items_by_day: dict[int, list[ItineraryItem]] = defaultdict(list)
    for item in items:
        items_by_day[item.day_id].append(item)
    intro_by_name: dict[str, ItineraryItem] = {}
    for item in items:
        if item.poi_name and item.poi_name not in intro_by_name:
            intro_by_name[item.poi_name] = item

    day_list: list[dict[str, Any]] = []
    for day in days:
        payload = {
            "dayId": day.id,
            "dayNo": day.day_no,
            "travelDate": _iso_date(day.travel_date),
            "note": day.note,
            "theme": None,
            "miniRoute": None,
            "backupPlan": None,
            "photoSpots": None,
            "practicalNotes": None,
            "dayOptions": None,
            "items": [_item_vo(item, descriptions, intro_by_name) for item in items_by_day.get(day.id, [])],
        }
        metadata = _loads_object(day.metadata_json) or {}
        payload["theme"] = metadata.get("theme")
        payload["miniRoute"] = _as_map(metadata.get("miniRoute"))
        payload["backupPlan"] = _as_map_list(metadata.get("backupPlan"))
        payload["photoSpots"] = _as_map_list(metadata.get("photoSpots"))
        payload["practicalNotes"] = _as_str_list(metadata.get("practicalNotes"))
        # dayOptions 必须透出：metadata 已落库，不透出即前端槽位空转
        payload["dayOptions"] = _as_map_list(metadata.get("dayOptions"))
        day_list.append(payload)

    total_amount = sum((b.amount or Decimal("0") for b in budgets), Decimal("0"))
    pending_facts = sum(
        1
        for item in items
        if (item.review_requirement is None or item.review_requirement != "none") or item.freshness_status == "stale"
    )
    quality_status = _quality_status(main.status, items, days, pending_facts)
    issues = _quality_issues(quality_status, days, items, pending_facts)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": main.id,
        "title": main.title,
        "city": main.city,
        "startDate": _iso_date(main.start_date),
        "endDate": _iso_date(main.end_date),
        "days": main.days,
        # 住宿晚数以主表为准；按"有酒店项的天数"反推会少算退房那一晚
        "stayNights": main.stay_nights if main.stay_nights is not None else max(len(day_list) - 1, 0),
        "persons": main.persons,
        "budget": _num(main.budget),
        "preferences": main.preferences,
        "hotelTier": main.hotel_tier,
        "status": main.status,
        "planNote": main.plan_note,
        "tripTheme": main.trip_theme,
        # S1：封面快照 / 收藏 / 归档 / 分享（详情是本人视角，shareToken 仅此处可回）
        "coverUrl": main.cover_url,
        "coverSource": main.cover_source,
        "coverCredit": _loads_object(main.cover_credit),
        "favorite": bool(main.favorite),
        "archived": bool(main.archived),
        "shareToken": main.share_token,
        "destinationStatus": _destination_status(items),
        "qualityStatus": quality_status,
        "qualityRuleVersion": QUALITY_RULE_VERSION,
        "validatedAt": None,
        "pendingFactCount": pending_facts,
        "qualityReport": _quality_report(quality_status, issues, pending_facts),
        "sources": _source_records(items),
        "suggestions": _loads_suggestions(main.suggestions_json),
        "dayList": day_list,
        "budgetList": [{"category": b.category, "amount": _num(b.amount), "itemCount": b.item_count} for b in budgets],
        "totalAmount": float(total_amount),
    }


def _item_vo(
    item: ItineraryItem, descriptions: dict[str, str | None], intro_by_name: dict[str, ItineraryItem]
) -> dict[str, Any]:
    return {
        "id": item.id,
        "itemType": item.item_type,
        "poiName": item.poi_name,
        "poiId": item.poi_id,
        "address": item.address,
        "latitude": _num(item.latitude),
        "longitude": _num(item.longitude),
        "startTime": _iso_time(item.start_time),
        "endTime": _iso_time(item.end_time),
        "durationMin": item.duration_min,
        "cost": _num(item.cost),
        "tag": item.tag,
        "remark": item.remark,
        "whyThis": item.why_note,
        "openTime": item.open_time,
        "image": item.image_url,
        "imageUrl": item.image_url,
        "source": item.source,
        "sourceUpdatedAt": _iso_datetime(item.source_updated_at),
        "verificationStatus": item.verification_status,
        "valueKind": item.value_kind,
        "freshnessStatus": item.freshness_status,
        "reviewRequirement": item.review_requirement,
        "factEvidenceJson": item.fact_evidence_json,
        "factEvidence": _loads_object(item.fact_evidence_json),
        "intro": intro_by_name[item.poi_name].intro if item.poi_name in intro_by_name else None,
        "description": descriptions.get(item.poi_name or ""),
        "sortNo": item.sort_no,
    }


def _quality_status(
    status: int | None, items: list[ItineraryItem], days: list[ItineraryDay], pending_facts: int
) -> str:
    has_failed_day = any(d.generation_status in _FAILED_DAY_STATUSES for d in days)
    has_incomplete_day = any(d.generation_status in _INCOMPLETE_DAY_STATUSES for d in days)
    has_stale = any(item.freshness_status == "stale" for item in items)
    if status == 3 or has_failed_day:
        return "BLOCKED"
    if has_incomplete_day or status == 1:
        return "DRAFT"
    if not items:
        return "BLOCKED"
    if has_stale:
        return "STALE"
    return "READY_WITH_WARNINGS" if pending_facts > 0 else "READY"


def _quality_issues(
    quality_status: str, days: list[ItineraryDay], items: list[ItineraryItem], pending_facts: int
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if quality_status == "BLOCKED":
        if not items:
            issues.append({"code": "NO_ITINERARY_ITEMS", "message": "没有可交付的行程地点"})
        if any(d.generation_status in _FAILED_DAY_STATUSES for d in days):
            issues.append({"code": "DAY_GENERATION_FAILED", "message": "至少一天的行程生成失败"})
    elif pending_facts > 0:
        issues.append({"code": "FACT_REQUIRES_REVIEW", "message": f"{pending_facts} 项事实需要出发前复核"})
    return issues


def _quality_report(quality_status: str, issues: list[dict[str, str]], pending_facts: int) -> dict[str, Any]:
    return {
        "qualityStatus": quality_status,
        "qualityRuleVersion": QUALITY_RULE_VERSION,
        "blockingIssues": issues if quality_status == "BLOCKED" else [],
        "warnings": issues if quality_status in ("READY_WITH_WARNINGS", "STALE") else [],
        "metrics": {"pendingFactCount": pending_facts},
    }


def _destination_status(items: list[ItineraryItem]) -> str:
    if not items:
        return "draft_only"
    has_open_research = any(item.source == "llm.open_day" for item in items)
    if has_open_research:
        has_authoritative = any(item.source and item.source != "llm.open_day" for item in items)
        return "researched" if has_authoritative else "draft_only"
    return "knowledge_backed"


def _source_records(items: list[ItineraryItem]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in items:
        source = item.source
        if not source:
            continue
        record = records.setdefault(source, {"sourceId": source, "storageSource": source, "provider": source})
        if item.source_updated_at is not None and "retrievedAt" not in record:
            record["retrievedAt"] = _iso_datetime(item.source_updated_at)
    return list(records.values())


def _loads_suggestions(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("suggestions_json parse failed, returned [] instead")
        return []
    return value if isinstance(value, list) else []
