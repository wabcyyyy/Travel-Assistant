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


def _extract_config_defaults(source: str) -> dict[str, tuple[str, Any, Any]]:
    """返回 {环境变量名: (类型, 默认值, 原始字面量)}；非字面量默认记为 None。

    G-1.5 起config.py 为 pydantic-settings 字段定义式：字段名小写即环境
    变量名（大小写不敏感对应，agent_host <-> AGENT_HOST）；这里按注解取
    类型（bool/int/float/str），按字面量取默认值；default_factory 等复杂
    默认只做存在性校验（expected=None）。validation_alias（如
    jwt_revocation_prefer_redis <- APP_JWT_REVOKE_PREFER_REDIS）优先于
    字段名派生。
    """
    tree = ast.parse(source)
    defaults: dict[str, tuple[str, Any, Any]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Settings"):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            field_name = stmt.target.id
            annotation = getattr(stmt.annotation, "id", "")
            if annotation not in ("str", "bool", "int", "float"):
                continue
            env_name = field_name.upper()
            value = stmt.value
            raw: Any = None
            # Field(default=..., validation_alias="...")：别名即环境变量名
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
                for keyword in value.keywords:
                    if keyword.arg == "validation_alias" and isinstance(keyword.value, ast.Constant):
                        env_name = str(keyword.value.value)
                    if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                        raw = keyword.value.value
            elif isinstance(value, ast.Constant):
                raw = value.value
            elif isinstance(value, ast.BinOp):
                raw = None  # 5 * 1024 * 1024 之类的表达式默认不做值比对
            defaults[env_name] = (annotation, raw, raw if isinstance(raw, (bool, int, float, str)) else None)
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
