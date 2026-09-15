"""W3 后端先行件：优化路线（`POST /{id}/optimize`）与日标题（`PATCH /{id}/days/{dayId}`）。

断言焦点：
1. 共线三点乱序（甲 0.0 / 丙 0.2 / 乙 0.1）优化后必须回到「甲 → 乙 → 丙」；
2. 优化前后各一条 `optimize` 快照（与既有写路径同纪律）；
3. 活动点位不足 2 个 → 400（含缺 dayId 的 400）；
4. 日标题写/清空都落 metadata_json.theme，未知天 404、超长 400。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.business.auth import auth_router
from app.api.business.itinerary import router as itinerary_router
from app.common.config import settings
from app.common.envelope import install_exception_handlers
from app.db import session as db_session
from app.db.models import Base, ItineraryDay, ItineraryItem, ItineraryMain, ItineraryVersion, SysUser
from app.services import cache_store, user_service

JWT_MATERIAL = "example-only-hs256-test-signing-material"


@pytest.fixture(autouse=True)
def db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'w3.db'}")
    Base.metadata.create_all(engine)
    db_session.init_engine(engine, sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "jwt_secret", JWT_MATERIAL)
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    cache_store.reset_for_tests()
    _seed()
    yield
    db_session.init_engine(None, None)
    cache_store.reset_for_tests()


def _seed() -> None:
    hashed = user_service.hash_password("x")
    with db_session.session_scope() as session:
        session.add(SysUser(username="alice", password=hashed, status=1, role="user"))
        trip = ItineraryMain(user_id=1, title="杭州2日游", city="杭州", start_date=date(2026, 4, 1),
                             end_date=date(2026, 4, 2), days=2, persons=2, budget=Decimal("2000.00"), status=2)
        session.add(trip)
        session.flush()
        first = ItineraryDay(itinerary_id=trip.id, day_no=1, generation_status="SUCCEEDED",
                             metadata_json='{"theme": "初版标题"}')
        second = ItineraryDay(itinerary_id=trip.id, day_no=2, generation_status="SUCCEEDED")
        session.add_all([first, second])
        session.flush()
        # 共线三点、故意乱序：甲(经度 0.0) 丙(0.2) 乙(0.1) —— 唯一最优路径为 甲 → 乙 → 丙
        session.add_all([
            ItineraryItem(day_id=first.id, itinerary_id=trip.id, item_type="attraction", poi_name="甲点",
                          latitude=Decimal("30.000000"), longitude=Decimal("120.000000"), sort_no=0),
            ItineraryItem(day_id=first.id, itinerary_id=trip.id, item_type="attraction", poi_name="丙点",
                          latitude=Decimal("30.000000"), longitude=Decimal("120.200000"), sort_no=1),
            ItineraryItem(day_id=first.id, itinerary_id=trip.id, item_type="attraction", poi_name="乙点",
                          latitude=Decimal("30.000000"), longitude=Decimal("120.100000"), sort_no=2),
        ])


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(itinerary_router)
    client = TestClient(app, follow_redirects=False)
    client.post("/api/auth/login", json={"username": "alice", "password": "x"})
    return client


def _trip_id(client: TestClient) -> int:
    return client.get("/api/itinerary").json()["data"][0]["id"]


def _day_ids(trip_id: int) -> list[int]:
    with db_session.session_scope() as session:
        return [row.id for row in session.execute(
            select(ItineraryDay).where(ItineraryDay.itinerary_id == trip_id).order_by(ItineraryDay.day_no)
        ).scalars().all()]


# ---------- 优化路线 ----------

def test_optimize_reorders_collinear_day_and_writes_snapshots(client: TestClient) -> None:
    trip_id = _trip_id(client)
    day1, _day2 = _day_ids(trip_id)

    before = client.get(f"/api/itinerary/{trip_id}").json()["data"]["dayList"][0]["items"]
    assert [item["poiName"] for item in before] == ["甲点", "丙点", "乙点"]

    response = client.post(f"/api/itinerary/{trip_id}/optimize", json={"dayId": day1})
    assert response.status_code == 200
    items = response.json()["data"]["dayList"][0]["items"]
    assert [item["poiName"] for item in items] == ["甲点", "乙点", "丙点"]
    assert [item["sortNo"] for item in items] == [0, 1, 2]

    with db_session.session_scope() as session:
        ops = [row.operation for row in session.execute(
            select(ItineraryVersion).where(ItineraryVersion.itinerary_id == trip_id).order_by(ItineraryVersion.id)
        ).scalars().all()]
    assert ops.count("optimize") >= 2, "优化前后各应有一条 optimize 快照"


def test_optimize_keeps_unmapped_trailing_items(client: TestClient) -> None:
    """优化器不认识的类型（酒店）不丢、留在末尾原相对顺序。"""
    trip_id = _trip_id(client)
    day1, _ = _day_ids(trip_id)
    with db_session.session_scope() as session:
        session.add(ItineraryItem(day_id=day1, itinerary_id=trip_id, item_type="hotel",
                                  poi_name="湖畔酒店", sort_no=3))

    response = client.post(f"/api/itinerary/{trip_id}/optimize", json={"dayId": day1})
    names = [item["poiName"] for item in response.json()["data"]["dayList"][0]["items"]]
    assert names == ["甲点", "乙点", "丙点", "湖畔酒店"]


def test_optimize_requires_two_active_items_and_day_id(client: TestClient) -> None:
    trip_id = _trip_id(client)
    _day1, day2 = _day_ids(trip_id)

    empty_day = client.post(f"/api/itinerary/{trip_id}/optimize", json={"dayId": day2})
    assert empty_day.status_code == 400
    assert "不足 2 个" in empty_day.json()["message"]

    missing_day = client.post(f"/api/itinerary/{trip_id}/optimize", json={})
    assert missing_day.status_code == 400
    assert "dayId" in missing_day.json()["message"]


# ---------- 日标题 ----------

def test_patch_day_theme_set_and_clear(client: TestClient) -> None:
    trip_id = _trip_id(client)
    day1, _ = _day_ids(trip_id)

    set_resp = client.patch(f"/api/itinerary/{trip_id}/days/{day1}", json={"theme": "老街与市集"})
    assert set_resp.status_code == 200
    assert set_resp.json()["data"]["dayList"][0]["theme"] == "老街与市集"

    clear_resp = client.patch(f"/api/itinerary/{trip_id}/days/{day1}", json={"theme": "  "})
    assert clear_resp.json()["data"]["dayList"][0]["theme"] in (None, "")

    with db_session.session_scope() as session:
        ops = [row.operation for row in session.execute(
            select(ItineraryVersion).where(ItineraryVersion.itinerary_id == trip_id).order_by(ItineraryVersion.id)
        ).scalars().all()]
    assert ops.count("update_day") >= 4, "两次编辑各前后一条 update_day 快照"


def test_patch_day_validations(client: TestClient) -> None:
    trip_id = _trip_id(client)
    day1, _ = _day_ids(trip_id)

    unknown = client.patch(f"/api/itinerary/{trip_id}/days/99999", json={"theme": "x"})
    assert unknown.status_code == 404

    too_long = client.patch(f"/api/itinerary/{trip_id}/days/{day1}", json={"theme": "字" * 61})
    assert too_long.status_code == 400
    assert "过长" in too_long.json()["message"]
