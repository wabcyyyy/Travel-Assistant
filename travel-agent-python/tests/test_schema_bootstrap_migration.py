"""M7-b 迁移验证：启动即迁移（等价 Java 侧 Flyway 在 boot 跑 V*.sql）。

revision 自 S0-13 起按文件拆分（0001 管 V1、0002 管 V2，见 E23）。这里钉住三条：

1. **既有库（有表、无 alembic_version）打点到基线、且继续 upgrade**：stamp 目标必须是
   `0001` 而不是 head——打到 head 会把基线之后的迁移整体跳过；打点后必须再 upgrade，
   才能把老库缺的 V2+ 补上。本用例把 `upgrade` 换成记录器：既断言它被调用，也证明
   除打点外没有任何 DDL 执行（真跑 V1 的 MySQL 语法在 SQLite 上会当场报错，
   测试通过本身就是"没跑 DDL"的证据）。
2. **重复启动幂等**：已有 alembic_version 的库不再打点，只走 upgrade。
3. **迁移 revision 自身拒绝重建**：若分支写错直接 upgrade，`0001_wrap_flyway_baseline`
   会用一句可执行的报错拦住（宁可启动失败，也不要"以为建了表其实没有"）。
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db import migrate as db_migrate
from app.db import session as db_session
from app.db.models import Base


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'bootstrap.db'}")
    db_session.init_engine(engine, sessionmaker(bind=engine, expire_on_commit=False))
    yield engine
    db_session.init_engine(None, None)


def _head_revision() -> str:
    return ScriptDirectory.from_config(db_migrate.alembic_config()).get_current_head()


def _record_upgrade(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(db_migrate.command, "upgrade", lambda config, revision: calls.append(revision))
    return calls


def test_existing_database_stamps_baseline_then_upgrades(sqlite_db, monkeypatch) -> None:
    # 模拟"Flyway 已经建过表的既有库"：只有业务表，没有 alembic_version
    Base.metadata.create_all(sqlite_db)
    assert inspect(sqlite_db).has_table("sys_user")
    assert not inspect(sqlite_db).has_table("alembic_version")

    upgrade_calls = _record_upgrade(monkeypatch)
    assert db_migrate.ensure_schema() == "stamped"

    with sqlite_db.connect() as connection:
        recorded = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    assert recorded == "0001_wrap_flyway_baseline", "打点必须落在基线：打到 head 会跳过 V2+ 的 DDL，库看着最新实际缺列"
    assert upgrade_calls == ["head"], "打点后必须继续 upgrade，把基线之后的迁移补齐"
    assert _head_revision() != "0001_wrap_flyway_baseline", (
        "head 尚等于基线说明 V2 revision 不存在——本断言的防跳过后半段失去意义"
    )


def test_second_boot_skips_stamp_and_only_upgrades(sqlite_db, monkeypatch) -> None:
    Base.metadata.create_all(sqlite_db)
    with sqlite_db.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('0001_wrap_flyway_baseline')")

    stamp_calls: list[str] = []
    monkeypatch.setattr(db_migrate.command, "stamp", lambda config, revision: stamp_calls.append(revision))
    upgrade_calls = _record_upgrade(monkeypatch)

    assert db_migrate.ensure_schema() == "upgraded"
    assert stamp_calls == [], "已有版本登记的库不应重复打点"
    assert upgrade_calls == ["head"]
    with sqlite_db.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM alembic_version").scalar() == 1


def test_revision_refuses_to_rebuild_an_existing_schema(sqlite_db) -> None:
    """分支写错的兜底：既有的表 + 直接 upgrade 必须炸出可执行的指引，不能静默跳过。"""
    Base.metadata.create_all(sqlite_db)
    with pytest.raises(RuntimeError) as exc:
        command.upgrade(db_migrate.alembic_config(), "head")
    assert "stamp" in str(exc.value)
    assert "V1__baseline_schema.sql" in str(exc.value)
