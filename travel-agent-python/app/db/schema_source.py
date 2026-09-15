"""Flyway 迁移 SQL 的读取入口——**双跑期不复制文件，只引用同一份真相**。

迁移期间 Java 服务仍由 Flyway 在启动时执行 `db/migration/V*.sql`，Python 侧的
Alembic 直接读取同一目录按序执行。若在这里复制一份 SQL，就会出现两份 schema
定义互相漂移——那正是本次迁移要消灭的问题，不能反过来引入。

Java 退役（M7）时把目录整体搬进 `app/db/migrations/sql/` 即可：`resolve_migration_dir()`
先看 Java 侧、再退本仓副本，所以**搬迁不需要改任何代码**，也不会出现"改了一半"的中间态。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.common.config import BASE_DIR

# travel-backend-java 与 travel-agent-python 是仓库根下的兄弟目录
_REPO_ROOT = BASE_DIR.parent
JAVA_MIGRATION_DIR = _REPO_ROOT / "travel-backend-java" / "src" / "main" / "resources" / "db" / "migration"
# Java 退役（M7）时 SQL 整体搬到这里；搬完无需改任何代码，解析顺序会自动切过来
IN_REPO_MIGRATION_DIR = BASE_DIR / "app" / "db" / "migrations" / "sql"

_VERSION_RE = re.compile(r"^V(\d+)_")


def _has_migrations(directory: Path) -> bool:
    """目录存在还不够——归档后 Java 侧目录可能空着留在这里，空目录会让启动迁移静默不做事。"""
    return directory.is_dir() and next(directory.glob("V*.sql"), None) is not None


def resolve_migration_dir() -> Path:
    """优先用 Java 侧那份（今天 Flyway 与 Alembic 读同一份，truth 只有一份），
    Java 模块归档后再自动改用本仓副本——两种状态都能跑，归档因此是一次纯文件搬迁。
    """
    if _has_migrations(JAVA_MIGRATION_DIR):
        return JAVA_MIGRATION_DIR
    return IN_REPO_MIGRATION_DIR


# 兼容既有引用（脚本与测试）：运行时按当前仓库状态取一次
SQL_MIGRATION_DIR = resolve_migration_dir()


def migration_files() -> list[Path]:
    """按 Flyway 版本号升序返回 V*.sql。"""

    def key(path: Path) -> tuple[int, str]:
        m = _VERSION_RE.match(path.name)
        return (int(m.group(1)) if m else 0, path.name)

    directory = resolve_migration_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("V*.sql"), key=key)


def read_all() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in migration_files()]


def _statements_in_range(lo: int | None, hi: int | None) -> list[tuple[str, str]]:
    """版本号在 [lo, hi]（含端点，None 表示不限）的迁移语句，按版本序展开。"""
    out: list[tuple[str, str]] = []
    for path in migration_files():
        matched = _VERSION_RE.match(path.name)
        number = int(matched.group(1)) if matched else 0
        if lo is not None and number < lo:
            continue
        if hi is not None and number > hi:
            continue
        out.extend((path.name, statement) for statement in split_statements(path.read_text(encoding="utf-8")))
    return out


def statements_upto(max_version: int) -> list[tuple[str, str]]:
    """版本号 ≤ max_version 的迁移语句——revision 只应用自己负责的那一段。

    为什么 revision 要能按版本圈定文件：`0001` 原先把「全部 V*.sql」一把执行，
    加了 V2 之后就会与「0002 再执行一次 V2」重复（空库直接炸）。详见各 revision
    的 docstring。
    """
    return _statements_in_range(None, max_version)


def statements_between(min_version: int, max_version: int) -> list[tuple[str, str]]:
    """版本号落在 [min_version, max_version] 的迁移语句。"""
    return _statements_in_range(min_version, max_version)


def split_statements(sql: str) -> list[str]:
    """按分号切句，但**分号只在字符串字面量之外才是语句结束符**。

    两个必要性：
    1. pymysql 默认不开 CLIENT_MULTI_STATEMENTS，整文件一次 execute 会报错；
    2. DDL 的 COMMENT 文本里可能出现分号（如 '状态 1-正常; 0-禁用'），
       朴素 split(";") 会把一条 CREATE TABLE 切成两半，产生难以定位的语法错误。
    """
    statements: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if in_string:
            buf.append(ch)
            if ch == "'":
                # SQL 里单引号转义是 ''：遇到成对引号则仍在字符串内
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
        elif ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
        elif ch == "-" and "".join(buf).strip() == "" and sql[i : i + 2] == "--":
            # 行注释：跳到行尾（仅在缓冲区为空白时才当注释起始，避免误吃列内文本）
            newline = sql.find("\n", i)
            i = len(sql) if newline == -1 else newline
            buf = []
            continue
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements
