"""Java 退役就绪度：删掉 Java 模块之后，Python 侧与门禁脚本仍必须自洽。

为什么值得单独钉：退休动作最容易以两种方式静默出事——
1. **运行时找不到文件**：SQL 真相源与印刷字体今天都住在 Java 模块里，直接删目录，
   服务要到"启动迁移"或"导出 PDF"时才炸；
2. **门禁自己先红**：`check_endpoint_coverage.py` 与 `check_schema_contract.py` 都以
   "Java 目录必须存在"为前提，归档当天 CI 会因为脚本读不到目录而失败。

所以两处路径都改成"Java 侧优先 + 本仓副本兜底"的解析器，归档因此是**一次纯文件搬迁**；
两个脚本也在"Java 侧不存在"时给出明确语义（不是静默跳过）：端点对照要求残留清单已清空，
schema 契约输出里注明跳过了实体列那一半。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.common import config
from app.db import schema_source

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = BASE_DIR / "scripts"


def _load_script(name: str, file_name: str | None = None):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{file_name or name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_migration_dir_prefers_the_copy_that_actually_has_sql(monkeypatch, tmp_path) -> None:
    """两个分支都要钉：有 SQL 的 Java 侧优先；目录存在但空（归档后残留）也必须退本仓。"""
    java_dir = tmp_path / "java" / "db" / "migration"
    java_dir.mkdir(parents=True)
    monkeypatch.setattr(schema_source, "JAVA_MIGRATION_DIR", java_dir)

    # 分支一：Java 侧真的有迁移文件 → 用它的（Flyway 与 Alembic 读同一份）
    (java_dir / "V1__baseline_schema.sql").write_text("SELECT 1;", encoding="utf-8")
    assert schema_source.resolve_migration_dir() == java_dir

    # 分支二：目录还在但没 SQL（搬迁后残留空目录）→ 必须退本仓，否则启动迁移会静默不做事
    (java_dir / "V1__baseline_schema.sql").unlink()
    assert schema_source.resolve_migration_dir() == schema_source.IN_REPO_MIGRATION_DIR
    # 文档里承诺的落点：归档时把 SQL 搬到这里
    assert schema_source.IN_REPO_MIGRATION_DIR == BASE_DIR / "app" / "db" / "migrations" / "sql"


def test_font_default_resolves_to_the_in_repo_copy(monkeypatch, tmp_path) -> None:
    service_root = tmp_path / "repo" / "travel-agent-python"
    monkeypatch.setattr(config, "BASE_DIR", service_root)

    # Java 模块已删除：字体全仓只有本仓一份；历史位置即使残留也不再回读
    java_font = (tmp_path / "repo" / "travel-backend-java" / "src" / "main" / "resources"
                 / "fonts" / "simhei.ttf")
    java_font.parent.mkdir(parents=True)
    java_font.write_bytes(b"font")
    assert config._default_font_path() == str(service_root / "app" / "resources" / "fonts" / "simhei.ttf")


def test_endpoint_coverage_requires_an_empty_checklist_once_java_is_gone(monkeypatch, tmp_path, capsys) -> None:
    module = _load_script("check_endpoint_coverage")
    monkeypatch.setattr(module, "JAVA_CONTROLLERS", tmp_path / "archived")

    # 残留清单没清空就归档 = 动作跑在清单之前（或 checkout 少了 Java 目录）→ 必须红
    monkeypatch.setattr(module, "EXPECTED_REMAINING", {("GET", "/api/legacy"): "示例残留"})
    assert module.main() == 1
    assert "EXPECTED_REMAINING" in capsys.readouterr().out

    monkeypatch.setattr(module, "EXPECTED_REMAINING", {})
    assert module.main() == 0
    assert "已删除" in capsys.readouterr().out


def test_schema_contract_notes_the_skipped_java_half(monkeypatch, tmp_path, capsys) -> None:
    module = _load_script("check_schema_contract")
    monkeypatch.setattr(module, "ENTITY_DIR", tmp_path / "archived")

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "OK:" in output
    # 跳过必须写在输出里：不能让人以为"两端都对齐"
    assert "跳过" in output and "已删除" in output


def test_script_fallback_matches_the_app_resolver(monkeypatch) -> None:
    """CI 的 schema job 用裸 python3 跑这个脚本（没装依赖 → import 不到 app 包），
    脚本里那份极简兜底必须与 app 侧解析器给出同一个目录，否则归档当天两边打架。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app" or name.startswith("app."):
            raise ImportError("simulated dependency-free CI job")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = _load_script("check_schema_contract_nodeps", "check_schema_contract")
    assert module.MIGRATION_DIR == schema_source.resolve_migration_dir()
