"""僵尸生成任务的自动续跑（移植自 Java `ItineraryStatusRecovery`）。

Java 用 `@Scheduled(fixedDelay=60s, initialDelay=60s)` + `ApplicationReadyEvent` 各跑一次；
这里是**一个 daemon 线程 + 同样的节奏**，启动时在 lifespan 里先跑一次。判定口径保持逐字：

- 活跃阈值 `updated_at < now - 5min`。这条完全依赖 MySQL 的
  `ON UPDATE CURRENT_TIMESTAMP`——任何一次状态写（markRunning/markFailed/persist）都会刷新
  `itinerary_day.updated_at`，这就是"活跃天心跳"。Python 侧同样靠列默认值，不在代码里手写时间。
- 老数据没有 `gen_state`，所以两个分支都要带 `gen_state IS NULL AND status IN (1,3)` 的回落。
- `gen_resumed=1` 表示"已经自动续跑过一次"，再失败不再重拉（防失败→重生成死循环）。
- 续跑去重锁 `gen:resume:{id}` TTL 10 分钟（大于一次生成的读超时 + 落库时间）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update

from app.db.models import ItineraryDay, ItineraryItem, ItineraryMain
from app.db.session import session_scope
from app.services import generation_gate, itinerary_generation, itinerary_query

logger = logging.getLogger(__name__)

IDLE_SECONDS = 5 * 60
SCAN_INTERVAL_SECONDS = 60
# Java 在 ApplicationReadyEvent 上立刻扫一次；这里把这趟扫描挪进线程并延后几秒，
# 免得"启动应用"这件事依赖数据库可用（测试里 `with TestClient(app)` 会走 lifespan）。
STARTUP_DELAY_SECONDS = 5


def rebuild_request(main: ItineraryMain) -> itinerary_generation.GenerateCommand:
    """从行程主表反推生成参数（与 Java `rebuildRequest` 同口径）。"""
    preferences = (
        []
        if not main.preferences or not main.preferences.strip()
        else [part for part in main.preferences.split(",") if part.strip()]
    )
    return itinerary_generation.GenerateCommand(
        city=main.city,
        days=main.days,
        persons=main.persons if main.persons is not None else 1,
        stay_nights=main.stay_nights if main.stay_nights is not None else max(main.days - 1, 0),
        start_date=main.start_date,
        end_date=main.end_date,
        budget=main.budget,
        preferences=preferences,
        hotel_tier=main.hotel_tier,
    )


def recover() -> int:
    """扫描一轮，返回发生状态变更的行程数（便于测试与运维断言）。

    注意阈值口径：`updated_at` 由 MySQL 的 `ON UPDATE CURRENT_TIMESTAMP` 填，而这里用的是
    应用侧 `datetime.now()`。两者必须同一时区，否则这个 5 分钟窗口会整体平移（实例在 UTC、
    库在 +08:00 时，僵尸判定会提前 8 小时命中）。部署保持两侧同时区。
    """
    active_after = datetime.now() - timedelta(seconds=IDLE_SECONDS)
    stale = ItineraryMain.updated_at < active_after
    idle_generating = and_(
        stale,
        or_(
            ItineraryMain.gen_state == "GENERATING", and_(ItineraryMain.gen_state.is_(None), ItineraryMain.status == 1)
        ),
    )
    failed_resumable = and_(
        stale,
        or_(ItineraryMain.gen_state == "FAILED", and_(ItineraryMain.gen_state.is_(None), ItineraryMain.status == 3)),
    )
    changed = 0
    with session_scope() as session:
        generating = session.execute(select(ItineraryMain).where(idle_generating)).scalars().all()
        failed = session.execute(select(ItineraryMain).where(failed_resumable)).scalars().all()
        targets = [(main.id, main.user_id, False) for main in generating] + [
            (main.id, main.user_id, True) for main in failed
        ]
    for itinerary_id, user_id, failed_resume in targets:
        try:
            if recover_one(itinerary_id, failed_resume, active_after):
                changed += 1
                itinerary_query.evict_detail(user_id, itinerary_id)
        except Exception as exc:
            logger.warning("could not resume itinerary %s: %s", itinerary_id, exc)
    return changed


def recover_one(itinerary_id: int, failed_resume: bool, active_after: datetime | None = None) -> bool:
    """返回是否真的动了状态。"""
    cutoff = active_after or (datetime.now() - timedelta(seconds=IDLE_SECONDS))
    with session_scope() as session:
        main = session.get(ItineraryMain, itinerary_id)
        if main is None:
            return False
        days = (
            session.execute(
                select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id).order_by(ItineraryDay.day_no)
            )
            .scalars()
            .all()
        )
        day_ids_with_items = {
            row
            for row in session.execute(
                select(ItineraryItem.day_id).where(ItineraryItem.itinerary_id == itinerary_id).distinct()
            )
            .scalars()
            .all()
        }
        completed_days = sum(
            1
            for day in days
            if day.generation_status == "SUCCEEDED" or (day.generation_status is None and day.id in day_ids_with_items)
        )
        if days and completed_days == len(days) and len(days) == main.days:
            # 数据其实齐了，只是终态没写上：补终态，不重跑
            session.execute(
                update(ItineraryMain)
                .where(ItineraryMain.id == itinerary_id)
                .values(
                    status=2, gen_state="COMPLETED", gen_finished_at=datetime.now(), title=f"{main.city}{main.days}日游"
                )
            )
            logger.info("recovered completed itinerary %s", itinerary_id)
            return True

        if any(day.generation_status == "RUNNING" and day.updated_at and day.updated_at > cutoff for day in days):
            return False
        if failed_resume and not _resumable_failed_trip(days):
            return False
        if not generation_gate.try_resume_lock(itinerary_id):
            return False
        if failed_resume:
            session.execute(
                update(ItineraryMain)
                .where(ItineraryMain.id == itinerary_id)
                .values(gen_resumed=True, gen_state="GENERATING", status=1)
            )
        command = rebuild_request(main)
        user_id = main.user_id

    try:
        itinerary_generation.submit_planning(user_id, itinerary_id, command)
    except itinerary_generation.TaskRejected as rejected:
        generation_gate.release_resume_lock(itinerary_id)
        logger.warning("could not resume itinerary %s: %s", itinerary_id, rejected)
        return False
    # failedResume 分支返回 True（这条行程确实被重拉了）；僵尸分支保持 Java 的返回值
    return failed_resume


def _resumable_failed_trip(days: list[ItineraryDay]) -> bool:
    """可续跑的失败行程：每一天都已终态且失败原因非空（否则交给生成中分支处理）。"""
    return bool(days) and all(
        day.generation_status == "FAILED" and day.generation_error and day.generation_error.strip() for day in days
    )


_stop = threading.Event()


def _loop() -> None:
    """启动后先扫一次（对应 Java 的 ApplicationReadyEvent 那趟），之后 fixedDelay=60s。

    单次扫描失败不能退出循环：一次数据库抖动会让僵尸行程永远没人续跑。
    """
    logger.info(
        "generation recovery loop starting (startup sweep in %ss, then every %ss)",
        STARTUP_DELAY_SECONDS,
        SCAN_INTERVAL_SECONDS,
    )
    deadline = STARTUP_DELAY_SECONDS
    while not _stop.wait(deadline):
        deadline = SCAN_INTERVAL_SECONDS
        try:
            recover()
        except Exception as exc:
            logger.warning("generation recovery scan failed: %s", exc)


def start_loop() -> threading.Thread:
    thread = threading.Thread(target=_loop, name="generation-recovery", daemon=True)
    thread.start()
    return thread


def stop_loop() -> None:
    _stop.set()
