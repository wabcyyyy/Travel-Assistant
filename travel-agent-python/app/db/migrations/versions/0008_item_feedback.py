"""V8：条目反馈（SPEC C3.5 反馈回路·记录链路）。

SQL 真相在 `app/db/migrations/sql/V8__item_feedback.sql`，
本 revision 只按序执行 V8，不复制、不改写 SQL；0007 的库升级时只补 V8。
"""

from __future__ import annotations

from alembic import op

from app.db.schema_source import SQL_MIGRATION_DIR, statements_between

revision = "0008_item_feedback"
down_revision = "0007_template"
branch_labels = None
depends_on = None

V8_VERSION = 8


def upgrade() -> None:
    statements = statements_between(V8_VERSION, V8_VERSION)
    if not statements:
        raise RuntimeError(f"未找到 V8 迁移 SQL：{SQL_MIGRATION_DIR}（部署或目录搬迁问题）")

    applied_file = None
    for filename, statement in statements:
        if filename != applied_file:
            print(f"[alembic] applying {filename}")
            applied_file = filename
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("本仓库不提供 downgrade：业务库回退请走备份恢复，而不是 DROP 列/表。")
