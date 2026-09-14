"""双端 schema 漂移检查：Flyway V1 基线必须覆盖 Python 查询列与 Java 实体列。

用法（仓库任意位置）：
    uv run python scripts/check_schema_contract.py

校验口径（纯静态，不需要数据库）：
- Python：app/agent/poi_repository.py 的 _POI_COLUMNS（只读查询列）必须在 V1 的
  poi_knowledge 表定义中存在；
- Java：各 @TableName 实体的字段（camelCase→snake_case）必须在对应建表语句中；
- 任何缺失即 exit 1 —— 新环境「启动即建表」后两端查询不会因缺列直接失败。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "travel-backend-java/src/main/resources/db/migration/V1__baseline_schema.sql"
POI_REPOSITORY = ROOT / "travel-agent-python/app/agent/poi_repository.py"
ENTITY_DIR = ROOT / "travel-backend-java/src/main/java/com/travel/backend/entity"

_COLUMN_RE = re.compile(
    r"^\s*`?(\w+)`?\s+(?:BIGINT|VARCHAR|DECIMAL|INT|TINYINT|DATETIME|DATE|TIME|TEXT|LONGTEXT|CHAR|DOUBLE|FLOAT)",
    re.I | re.M,
)


def parse_v1() -> dict[str, set[str]]:
    text = V1.read_text(encoding="utf-8")
    tables: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\)\s*ENGINE", text, re.S):
        tables[m.group(1)] = {c.lower() for c in _COLUMN_RE.findall(m.group(2))}
    return tables


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def check_python(tables: dict[str, set[str]]) -> list[str]:
    text = POI_REPOSITORY.read_text(encoding="utf-8")
    block = re.search(r"_POI_COLUMNS\s*=\s*\((.*?)\)", text, re.S)
    if not block:
        return ["poi_repository._POI_COLUMNS 解析失败（检查脚本或重构了常量）"]
    columns = re.findall(r'"([\w, ]+)"', block.group(1))
    names = [c.strip() for part in columns for c in part.split(",") if c.strip()]
    known = tables.get("poi_knowledge", set())
    return [f"poi_knowledge 缺列（Python 只读查询需要）: {c}" for c in names if c.lower() not in known]


def check_java(tables: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    for f in sorted(ENTITY_DIR.glob("*.java")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r'@TableName\("(\w+)"\)', text)
        if not m:
            continue
        table = m.group(1)
        known = tables.get(table)
        if known is None:
            problems.append(f"{f.name}: V1 缺少实体对应表 {table}")
            continue
        for fm in re.finditer(r"^\s*private\s+[\w<>,\s\.]+\s+(\w+)\s*;", text, re.M):
            col = snake(fm.group(1))
            if col not in known:
                problems.append(f"{f.name}: {table} 缺列 {col}")
    return problems


def main() -> int:
    tables = parse_v1()
    problems = check_python(tables) + check_java(tables)
    if problems:
        print("schema 漂移（V1 与两端代码不一致）：")
        for p in problems:
            print("  -", p)
        return 1
    print(f"OK: V1 覆盖 {len(tables)} 张表；Python 只读列与 Java 实体列全部存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
