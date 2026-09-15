"""CI 校验：.env.example 与 app/common/config.py 默认值对齐（M0 契约先行）。

做法：
- 用 ast 解析 config.py 的 Settings 类体，提取每个 ``_get(...)`` / ``_get_bool(...)``
  调用的环境变量名与默认值字面量（兼容 ``int(_get(...))`` / ``float(_get(...))`` 包裹；
  非字面量默认（如 ``str(BASE_DIR / ...)``）只做存在性校验）；
- 解析 .env.example 的活动 ``KEY=VALUE`` 行与 ``# KEY=`` 注释行；
- 断言：①每个非密钥 config 键在 example 中存在（活动行或注释行均可；
  名字含 KEY/SECRET/TOKEN/PASSWORD 的密钥类排除，保持占位符不校验）；
  ②活动行的值与 config 默认一致（布尔归一化 true/false/1/0 大小写不敏感；
  int 按字符串去空格比较；float 用 str(float(a)) == str(float(b))）。

失败信息直接指出漂移的键，便于 CI 排障。
"""

import ast
import re
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "common" / "config.py"
EXAMPLE_PATH = Path(__file__).resolve().parent.parent / ".env.example"

_SECRET_MARKS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def _extract_config_defaults(source: str) -> dict[str, tuple[str, Any, str | None]]:
    """返回 {环境变量名: (包装类型, 默认值, 原始字面量)}；非字面量默认记为 None。"""
    tree = ast.parse(source)
    defaults: dict[str, tuple[str, Any, str | None]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Settings"):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            call = stmt.value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            wrapper: str | None = None
            if call.func.id in ("int", "float"):
                wrapper = call.func.id
                inner = call.args[0]
                if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)):
                    continue
                call = inner
            if call.func.id not in ("_get", "_get_bool"):
                continue
            env_name = call.args[0].value
            second = call.args[1] if len(call.args) > 1 else None
            if isinstance(second, ast.Constant):  # noqa: SIM108 -- 嵌套三元比 if/else 链更不可读，保持分支写法
                raw = second.value
            else:
                raw = False if call.func.id == "_get_bool" else None
            kind = "bool" if call.func.id == "_get_bool" else (wrapper or "str")
            defaults[env_name] = (kind, raw, second.value if isinstance(second, ast.Constant) else None)
    return defaults


def _parse_example(text: str) -> tuple[dict[str, str], set[str]]:
    """返回 (活动 KEY=VALUE 行, 注释里的 KEY= 键名集合)。"""
    active: dict[str, str] = {}
    commented: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
            if m:
                commented.add(m.group(1))
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            active[key.strip()] = value.strip()
    return active, commented


def test_env_example_covers_all_non_secret_config_keys():
    defaults = _extract_config_defaults(CONFIG_PATH.read_text(encoding="utf-8"))
    assert defaults, "未能从 config.py 解析出任何配置键（解析逻辑可能失效）"
    active, commented = _parse_example(EXAMPLE_PATH.read_text(encoding="utf-8"))
    missing = sorted(
        key
        for key in defaults
        if not any(mark in key.upper() for mark in _SECRET_MARKS) and key not in active and key not in commented
    )
    assert not missing, f".env.example 缺少以下 config 键（活动行或 # KEY= 注释行均可）: {missing}"


def test_env_example_active_values_match_config_defaults():
    defaults = _extract_config_defaults(CONFIG_PATH.read_text(encoding="utf-8"))
    active, _commented = _parse_example(EXAMPLE_PATH.read_text(encoding="utf-8"))
    drifted: list[str] = []
    for key, (kind, expected, _raw) in defaults.items():
        if key not in active or expected is None:
            continue  # 注释行/非字面量默认只做存在性校验
        if any(mark in key.upper() for mark in _SECRET_MARKS):
            continue  # 密钥类只保留占位符，不做值校验
        actual = active[key]
        if kind == "bool":
            if (actual.lower() in ("1", "true", "yes")) is not expected:
                drifted.append(f"{key}: example={actual!r} vs config 默认={expected}")
        elif kind == "float":
            if str(float(actual)) != str(float(expected)):
                drifted.append(f"{key}: example={actual!r} vs config 默认={expected!r}")
        elif str(actual) != str(expected).strip():
            drifted.append(f"{key}: example={actual!r} vs config 默认={expected!r}")
    assert not drifted, ".env.example 以下键的值与 config.py 默认值不一致: " + "; ".join(drifted)
