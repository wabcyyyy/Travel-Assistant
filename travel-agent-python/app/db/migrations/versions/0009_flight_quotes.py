"""V9：往返航班报价（L14 航班链路）。

SQL 真相在 `app/db/migrations/sql/V9__flight_quotes.sql`，
本 revision 只按序执行 V9，不复制、不改写 SQL；0008 的库升级时只补 V9。
"""

from __future__ import annotations

from alembic import op

from app.db.schema_source import SQL_MIGRATION_DIR, statements_between

revision = "0009_flight_quotes"
down_revision = "0008_item_feedback"
branch_labels = None
depends_on = None

V9_VERSION = 9


def upgrade() -> None:
    statements = statements_between(V9_VERSION, V9_VERSION)
    if not statements:
        raise RuntimeError(f"未找到 V9 迁移 SQL：{SQL_MIGRATION_DIR}（部署或目录搬迁问题）")

    applied_file = None
    for filename, statement in statements:
        if filename != applied_file:
            print(f"[alembic] applying {filename}")
            applied_file = filename
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("本仓库不提供 downgrade：业务库回退请走备份恢复，而不是 DROP 列/表。")
