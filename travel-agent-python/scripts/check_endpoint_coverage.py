"""迁移完成度的机器证据：Java 业务端点集合 vs Python 已挂载集合。

为什么要有这个脚本：「Java 已经迁完了」这句话以前只能靠文档里的手抄计数维持，
而文档是时间快照——评审报告里就出现过「仍是 serviceImpl」这类早已失效的结论。
端点数是最容易被说错、又最容易被机器算对的数字，所以把它变成门禁：

- 少迁（Python 缺端点）→ 红：说明有域没搬完；
- 多迁出预期差集（Python 出现 Java 没有的 /api 业务端点）→ 不报错，只列出来；
- **预期残留集发生变化**（既不在 Python、也不在下面的白名单里）→ 红。

`EXPECTED_REMAINING` 就是"还剩什么、为什么故意不搬"的唯一清单；M7 收尾时应逐条清空。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
JAVA_CONTROLLERS = REPO_ROOT / "travel-backend-java/src/main/java/com/travel/backend/controller"

_MAPPING_RE = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping(?:\(([^)]*)\))?")
_CLASS_PREFIX_RE = re.compile(r'@RequestMapping\(\s*"([^"]+)"')
_PATH_RE = re.compile(r'"([^"]+)"')
_PARAM_RE = re.compile(r"\{[^}]+\}")

# 迁移期的残留清单：Java 模块已删除（2026-09-14），端点对照随之收尾，此表保持为空。
# 若将来恢复 Java 代码作对照，把对照出的残留逐条登记在这里再跑本脚本。
EXPECTED_REMAINING: dict[tuple[str, str], str] = {}


def _normalize(prefix: str, path: str) -> str:
    """`{id}`/`{itemId}` 等占位符统一成 `{}`：两端参数命名不同，但路径形状必须可比。"""
    joined = prefix + (path or "")
    joined = re.sub(r"/{2,}", "/", joined)
    return _PARAM_RE.sub("{}", joined)


def java_endpoints() -> set[tuple[str, str]]:
    endpoints: set[tuple[str, str]] = set()
    for file in sorted(JAVA_CONTROLLERS.glob("*.java")):
        text = file.read_text(encoding="utf-8")
        prefix_match = _CLASS_PREFIX_RE.search(text)
        prefix = prefix_match.group(1) if prefix_match else ""
        for verb, args in _MAPPING_RE.findall(text):
            path_match = _PATH_RE.search(args or "")
            endpoints.add((verb.upper(), _normalize(prefix, path_match.group(1) if path_match else "")))
    return endpoints


def python_endpoints() -> set[tuple[str, str]]:
    sys.path.insert(0, str(BASE_DIR))
    import main

    endpoints: set[tuple[str, str]] = set()
    for route in main.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path.startswith(("/api/agent", "/docs", "/redoc", "/openapi.json")):
            continue
        for method in methods:
            if method not in ("HEAD", "OPTIONS"):
                endpoints.add((method, _normalize("", path)))
    return endpoints


def main() -> int:
    if not JAVA_CONTROLLERS.is_dir():
        # Java 模块已归档 = 迁移收尾。此时唯一正确的状态是"残留清单已清空"：
        # 否则说明归档动作跑在清单清空之前（或 checkouts 里少了 Java 目录），必须报出来。
        if EXPECTED_REMAINING:
            print(
                "FAIL: Java 控制器目录不存在，但 EXPECTED_REMAINING 仍有登记："
                + ", ".join(f"{verb} {path}" for verb, path in sorted(EXPECTED_REMAINING))
            )
            return 1
        print(f"OK: Java 模块已删除（{JAVA_CONTROLLERS} 不存在），端点对照不再适用且无残留登记")
        return 0
    java_set = java_endpoints()
    python_set = python_endpoints()
    missing = sorted(java_set - python_set)
    unexpected = [(verb, path) for verb, path in missing if (verb, path) not in EXPECTED_REMAINING]
    retired = sorted(set(EXPECTED_REMAINING) - set(missing))

    print(
        f"Java 业务端点 {len(java_set)} · Python 已挂载 {len(python_set)} · "
        f"残留 {len(missing)}（预期 {len(EXPECTED_REMAINING)}）"
    )
    for verb, path in missing:
        reason = EXPECTED_REMAINING.get((verb, path))
        print(f"  残留  {verb:6} {path}" + (f"  ← {reason}" if reason else "  ← 未登记！"))
    for verb, path in retired:
        print(f"  已迁  {verb:6} {path}  ← 请同步删除 EXPECTED_REMAINING 里的这一条")
    if unexpected:
        print(f"FAIL: {len(unexpected)} 个未登记的残留端点")
        return 1
    if retired:
        print("FAIL: 预期残留清单已过期（有端点其实已经迁完）")
        return 1
    print("OK: 残留端点与登记的清单逐条一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
