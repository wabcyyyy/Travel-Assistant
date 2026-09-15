"""upsert 批内去重与 norm_name 大小写折叠回归测试（#15 二次修复）。

复现并锁定实际跑批中撞唯一键的 bug：MySQL (city,name,category) 唯一键用 CI
排序规则，"Lush酒吧"/"lush酒吧" 在库里是同一行；Python 匹配键必须同样大小写
不敏感，否则被判为不同 → 双双 INSERT → 撞 1062。
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.common import db_pool

_ENRICH = Path(__file__).resolve().parents[2] / "sql" / "enrich_pois.py"


@pytest.fixture(scope="module")
def enrich():
    spec = importlib.util.spec_from_file_location("enrich_pois", _ENRICH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clear_pool():
    db_pool.close_all()
    yield
    db_pool.close_all()


def test_norm_name_is_case_insensitive(enrich):
    # 与 MySQL CI 排序规则对齐：大小写不同的同名折叠为同一匹配键
    assert enrich.norm_name("Lush酒吧") == enrich.norm_name("lush酒吧")
    assert enrich.norm_name("LUSH酒吧") == enrich.norm_name("lush酒吧")


def test_upsert_merges_case_variant_batch_duplicates(enrich):
    """批内两条仅大小写不同的同 (city,name,category) 记录：只 INSERT 一次，第二条 UPDATE。"""

    def rec(name, price):
        return {
            "city": "北京",
            "name": name,
            "category": "food",
            "address": "某街",
            "latitude": 39.9,
            "longitude": 116.4,
            "ticket_price": price,
            "avg_cost": None,
            "duration_min": None,
            "open_time": None,
            "tags": None,
            "rating": 4.5,
            "description": "x",
            "source": "amap.poi",
            "_source_parts": set(),
        }

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = []  # 库内初始为空
    cursor.lastrowid = 5001
    inserts = []
    updates = []

    def execute(sql, params=None):
        if sql.strip().upper().startswith("INSERT"):
            inserts.append(params)
        elif sql.strip().upper().startswith("UPDATE"):
            updates.append(params)

    cursor.execute.side_effect = execute

    with patch.object(enrich, "_pooled_connect", return_value=conn):
        inserted, updated, _unchanged = enrich.upsert_pois([rec("Lush酒吧", 80), rec("lush酒吧", 90)])

    assert inserted == 1, "大小写变体不应各自 INSERT（会撞唯一键）"
    assert updated == 1, "第二条应并入同一行走 UPDATE"
    assert cursor.execute.called


def test_upsert_registers_inserted_row_for_intra_batch_dedup(enrich):
    """批内完全同名同品类重复也只落一行（第二条 UPDATE 合并）。"""

    def rec(name, price=None):
        return {
            "city": "上海",
            "name": name,
            "category": "attraction",
            "address": "a",
            "latitude": 31.2,
            "longitude": 121.4,
            "ticket_price": price,
            "avg_cost": None,
            "duration_min": None,
            "open_time": None,
            "tags": None,
            "rating": 4.6,
            "description": "d",
            "source": "amap.poi",
            "_source_parts": set(),
        }

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = []
    cursor.lastrowid = 7001
    counts = {"insert": 0, "update": 0}

    def execute(sql, params=None):
        key = sql.strip().upper()
        if key.startswith("INSERT"):
            counts["insert"] += 1
        elif key.startswith("UPDATE"):
            counts["update"] += 1

    cursor.execute.side_effect = execute

    with patch.object(enrich, "_pooled_connect", return_value=conn):
        enrich.upsert_pois([rec("外滩"), rec("外滩", price=45)])

    assert counts["insert"] == 1
    assert counts["update"] == 1
