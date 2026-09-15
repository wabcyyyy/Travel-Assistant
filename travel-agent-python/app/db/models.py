"""业务层 ORM 模型：与 Flyway `V1__baseline_schema.sql` 逐列对齐。

迁移治理（PLAN v3.0 §1.4）：**SQL 文件仍是 schema 真相源**，本文件只是它的运行时投影。
两者由 `scripts/check_schema_contract.py` 在 CI 双向比对（实体有列而迁移没有 → 红；
迁移有而实体没有 → 仅信息，允许保留未映射的历史列）。

MySQL 专有写法统一走 variant，以便离线单测能在 SQLite 内存库上真跑 CRUD：
- BIGINT 自增主键在 SQLite 需要 INTEGER 才能真正自增；
- LONGTEXT / TINYINT(1) 在非 MySQL 上降级为 Text / SmallInteger。

非唯一索引**刻意不在模型里声明**：schema 由 SQL 迁移拥有，模型只是投影；且 MySQL
索引名是表内作用域（`idx_itinerary` 在多张表重复合法），SQLite 索引名是全局作用域，
照抄会让「从模型建表」的离线测试直接撞名。唯一约束则保留——它影响写入语义，测试需要。
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# MySQL 用 LONGTEXT，其余方言（SQLite 测试）退回 Text
LongText = Text().with_variant(LONGTEXT(), "mysql")
# MySQL 主键需 BIGINT；SQLite 只有 INTEGER 主键才自增
PkBigInt = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class SoftDelete:
    """带逻辑删除的实体共用此标记。

    过滤**不写在每个查询里**：Java 侧由 MyBatis-Plus @TableLogic 全局自动追加
    `deleted = 0`，等价的 SQLAlchemy 实现见 `app.db.session` 的 do_orm_execute 钩子。
    漏写会让已删除行程继续出现在列表 / 详情 / Atlas / 分享反查中。
    """

    deleted: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class SysUser(Base, SoftDelete):
    __tablename__ = "sys_user"
    __table_args__ = (UniqueConstraint("username", name="uk_username"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False, comment="BCrypt 加密密码")
    nickname: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[int] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserPreference(Base):
    __tablename__ = "user_preference"
    __table_args__ = (UniqueConstraint("user_id", "pref_label", name="uk_user_pref"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pref_label: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="explicit", server_default="explicit")
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("1.0000"), server_default="1.0000"
    )
    negative: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    hard_constraint: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ItineraryVersion(Base):
    __tablename__ = "itinerary_version"
    __table_args__ = (UniqueConstraint("itinerary_id", "version_no", name="uk_itinerary_version"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(BigInteger)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 实际取值 13 种（见 V2 的 MODIFY COMMENT 与 SPEC §7.4）：create/generate/add_item/
    # update_item/move_item/delete_item/reorder/nl_edit/delete/apply_plans/apply_hotel/
    # snapshot/restore；V1 的 DDL 注释 'snapshot/apply/restore' 已过时
    operation: Mapped[str] = mapped_column(String(24), nullable=False, default="snapshot", server_default="snapshot")
    summary: Mapped[str | None] = mapped_column(String(255))
    snapshot_json: Mapped[str] = mapped_column(LongText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ItineraryMain(Base, SoftDelete):
    __tablename__ = "itinerary_main"
    __table_args__ = (UniqueConstraint("share_token", name="uk_itinerary_share_token"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    persons: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    preferences: Mapped[str | None] = mapped_column(String(512))
    hotel_tier: Mapped[str | None] = mapped_column(String(16))
    stay_nights: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 面向用户的状态：1=草稿(生成中) 2=已生成 3=已取消
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    plan_note: Mapped[str | None] = mapped_column(Text)
    suggestions_json: Mapped[str | None] = mapped_column(Text)
    trip_theme: Mapped[str | None] = mapped_column(String(64))
    # 运维态生成状态机；NULL = 迁移前存量（列表筛选 active 必须含 IS NULL 分支）
    gen_state: Mapped[str | None] = mapped_column(String(16))
    gen_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    gen_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    gen_resumed: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # V2（atlas_share_covers）：封面快照三列 + 署名 + 收藏/归档 + 公开分享
    cover_url: Mapped[str | None] = mapped_column(String(512))
    cover_source: Mapped[str | None] = mapped_column(String(16))
    cover_ref: Mapped[str | None] = mapped_column(String(64))
    cover_credit: Mapped[str | None] = mapped_column(Text)
    favorite: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    archived: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    share_token: Mapped[str | None] = mapped_column(String(48))
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ItineraryChatMessage(Base):
    __tablename__ = "itinerary_chat_message"

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user/ai")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    plans_json: Mapped[str | None] = mapped_column(LongText)
    hotel_options_json: Mapped[str | None] = mapped_column(LongText)
    changed: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ItineraryDay(Base, SoftDelete):
    __tablename__ = "itinerary_day"
    __table_args__ = (
        UniqueConstraint("itinerary_id", "day_no", name="uk_itinerary_day_no"),
        UniqueConstraint("generation_action_id", name="uk_generation_action"),
    )

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    travel_date: Mapped[date | None] = mapped_column(Date)
    city: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(512))
    metadata_json: Mapped[str | None] = mapped_column(LongText)
    generation_action_id: Mapped[str | None] = mapped_column(String(96))
    generation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    generation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PENDING", server_default="PENDING"
    )
    generation_error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ItineraryItem(Base, SoftDelete):
    __tablename__ = "itinerary_item"

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    day_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    poi_name: Mapped[str] = mapped_column(String(128), nullable=False)
    poi_id: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    tag: Mapped[str | None] = mapped_column(String(32))
    remark: Mapped[str | None] = mapped_column(String(255))
    open_time: Mapped[str | None] = mapped_column(String(64))
    image_url: Mapped[str | None] = mapped_column(String(1024))
    source: Mapped[str | None] = mapped_column(String(128))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unverified", server_default="unverified"
    )
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="generated", server_default="generated")
    freshness_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    review_requirement: Mapped[str] = mapped_column(
        String(24), nullable=False, default="before_departure", server_default="before_departure"
    )
    fact_evidence_json: Mapped[str | None] = mapped_column(LongText)
    intro: Mapped[str | None] = mapped_column(String(600))
    why_note: Mapped[str | None] = mapped_column(String(255))
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BudgetDetail(Base, SoftDelete):
    __tablename__ = "budget_detail"

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    day_id: Mapped[int | None] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PoiKnowledge(Base):
    __tablename__ = "poi_knowledge"
    __table_args__ = (UniqueConstraint("city", "name", "category", name="uk_city_name_category"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="attraction", server_default="attraction")
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    ticket_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    duration_min: Mapped[int | None] = mapped_column(Integer)
    open_time: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[str | None] = mapped_column(String(128))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    description: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(
        String(128), nullable=False, default="mysql.poi_knowledge", server_default="mysql.poi_knowledge"
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class HotelRoomType(Base):
    __tablename__ = "hotel_room_type"
    __table_args__ = (UniqueConstraint("poi_id", "room_name", name="uk_hotel_room"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    poi_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    bed_type: Mapped[str | None] = mapped_column(String(64))
    breakfast: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(512))
    is_default: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class CityConsumption(Base):
    __tablename__ = "city_consumption"
    __table_args__ = (UniqueConstraint("city", name="uk_city"),)

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="standard", server_default="standard")
    meal_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    transport_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hotel_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class CityGeo(Base):
    """城市→国家字典（Atlas 归国 / 海外判定单一来源，V2）。

    刻意**不继承 SoftDelete**：字典表无 `deleted` 列（同 `poi_knowledge`）。
    未命中时调用方必须显式处置——Atlas 计入 dictMiss，禁止默认按 CN 处理。
    坐标仅兜底（行程无可用坐标时才用到）；未核实来源前保持 NULL。
    """

    __tablename__ = "city_geo"

    city_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    is_domestic: Mapped[int] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class ExportTask(Base, SoftDelete):
    __tablename__ = "export_task"

    id: Mapped[int] = mapped_column(PkBigInt, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False, default="PDF", server_default="PDF")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING", server_default="RUNNING")
    file_path: Mapped[str | None] = mapped_column(String(512))
    error_msg: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
