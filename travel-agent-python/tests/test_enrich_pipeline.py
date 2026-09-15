"""数据管线（sql/enrich_pois.py）纯函数回归测试：#14/#15/#14c 修复。

覆盖：高德 cost 按品类落位（景点→avg_cost、餐饮/酒店→ticket_price）、
Wikivoyage 合并名称门槛、source 并集不降级、重复行按完整度收敛。
管线脚本以文件路径动态加载，不触发其网络/写库副作用。
"""

import importlib.util
from pathlib import Path

import pytest

_ENRICH = Path(__file__).resolve().parents[2] / "sql" / "enrich_pois.py"


@pytest.fixture(scope="module")
def enrich():
    spec = importlib.util.spec_from_file_location("enrich_pois", _ENRICH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- #14：parse_amap_poi 价格落位 ----------


def _amap_raw(category_type, cost):
    return {
        "name": "测试点",
        "type": category_type,
        "location": "120.15,30.24",
        "address": "某路1号",
        "id": "B0TEST",
        "biz_ext": {"rating": "4.6", "cost": str(cost), "opentime2": "09:00-17:00"},
    }


def test_attraction_cost_lands_in_avg_cost_not_ticket_price(enrich):
    bbox = (118.3, 29.2, 120.9, 30.6)
    rec = enrich.parse_amap_poi(_amap_raw("风景名胜", "80"), "杭州", "attraction", bbox)
    assert rec is not None
    assert rec["avg_cost"] == 80.0
    assert rec["ticket_price"] is None  # 人均不再冒充门票价


def test_food_cost_keeps_ticket_price_contract(enrich):
    bbox = (118.3, 29.2, 120.9, 30.6)
    rec = enrich.parse_amap_poi(_amap_raw("中餐厅", "120"), "杭州", "food", bbox)
    assert rec is not None
    assert rec["ticket_price"] == 120.0  # 餐饮人均沿用 ticket_price（下游取价契约）
    assert rec["avg_cost"] is None


def test_hotel_cost_keeps_ticket_price_contract(enrich):
    bbox = (118.3, 29.2, 120.9, 30.6)
    rec = enrich.parse_amap_poi(_amap_raw("宾馆酒店", "450"), "杭州", "hotel", bbox)
    assert rec is not None
    assert rec["ticket_price"] == 450.0
    assert rec["avg_cost"] is None


# ---------- #14c：Wikivoyage 合并名称门槛 ----------


def test_name_compatible(enrich):
    assert enrich._name_compatible("西湖", "西湖")
    assert enrich._name_compatible("西湖风景名胜区", "西湖")  # 前缀包含
    assert enrich._name_compatible("楼外楼(西湖店)", "楼外楼")  # 去分店后缀
    assert not enrich._name_compatible("西湖", "苏堤")  # 邻近但不同实体
    assert not enrich._name_compatible("知味观", "绿茶餐厅")  # 互不为前缀不合并
    assert not enrich._name_compatible("", "西湖")  # 空名不合并


def test_merge_requires_name_match(enrich):
    """核心区 200m 内同类但名称无关的记录不得合并（误并污染权威字段）。"""
    amap = {
        "attraction": [
            {
                "name": "灵隐寺",
                "category": "attraction",
                "latitude": 30.2430,
                "longitude": 120.1000,
                "description": None,
                "open_time": None,
                "ticket_price": None,
                "avg_cost": None,
                "tags": "",
                "_source_parts": {"amap.poi"},
            }
        ]
    }
    wv = [
        {
            "name": "法喜寺",
            "category": "attraction",
            "latitude": 30.2432,
            "longitude": 120.1002,  # 距灵隐寺 ~30m
            "description": "误并风险条目",
            "open_time": None,
            "ticket_price": None,
            "avg_cost": None,
            "tags": "",
            "_source_parts": {"wikivoyage"},
        }
    ]
    standalone = enrich.merge_wv_into_amap(wv, amap)
    assert len(standalone) == 1  # 未合并，作为独立记录
    assert amap["attraction"][0]["description"] is None


def test_merge_allows_same_name(enrich):
    amap = {
        "attraction": [
            {
                "name": "灵隐寺",
                "category": "attraction",
                "latitude": 30.2430,
                "longitude": 120.1000,
                "description": None,
                "open_time": None,
                "ticket_price": None,
                "avg_cost": None,
                "tags": "",
                "_source_parts": {"amap.poi"},
            }
        ]
    }
    wv = [
        {
            "name": "灵隐寺",
            "category": "attraction",
            "latitude": 30.2432,
            "longitude": 120.1002,
            "description": "禅宗名刹",
            "open_time": "07:00-18:00",
            "ticket_price": 45,
            "avg_cost": None,
            "tags": "",
            "_source_parts": {"wikivoyage"},
        }
    ]
    standalone = enrich.merge_wv_into_amap(wv, amap)
    assert standalone == []
    target = amap["attraction"][0]
    assert target["description"] == "禅宗名刹"
    assert target["ticket_price"] == 45
    assert "wikivoyage" in target["_source_parts"]


# ---------- #15：source 并集与重复行收敛 ----------


def test_source_union_does_not_downgrade(enrich):
    assert enrich._source_union("amap.poi+wikivoyage", "amap.poi") == "amap.poi+wikivoyage"
    assert enrich._source_union("mysql.poi_knowledge", "amap.poi") == "amap.poi"
    assert enrich._source_union(None, "llm") == "llm"


def test_row_completeness_prefers_richer_row(enrich):
    sparse = {
        "address": None,
        "latitude": None,
        "longitude": None,
        "ticket_price": None,
        "avg_cost": None,
        "open_time": None,
        "description": None,
        "rating": None,
        "tags": None,
    }
    rich = dict(sparse, address="a", latitude=1.0, longitude=2.0, rating=4.5)
    assert enrich._row_completeness(rich) > enrich._row_completeness(sparse)


# ---------- 国外模式：Nominatim 免 key 采集 ----------


def test_parse_nominatim_poi_contract(enrich):
    """Nominatim 记录 → 内部契约（source=nominatim，坐标必须落城市范围）。"""
    bbox = (2.22, 48.79, 2.47, 48.93)  # 巴黎
    rec = enrich.parse_nominatim_poi(
        {
            "lat": "48.8584",
            "lon": "2.2945",
            "name": "Eiffel Tower",
            "display_name": "Eiffel Tower, Champ de Mars, 75007 Paris, France",
            "extratags": {"rating": "4.6"},
        },
        "巴黎",
        "attraction",
        bbox,
    )
    assert rec is not None
    assert rec["name"] == "Eiffel Tower"
    assert rec["latitude"] == 48.8584 and rec["longitude"] == 2.2945
    assert rec["_source_parts"] == {"nominatim"}
    assert enrich.compose_source(rec["_source_parts"]) == "nominatim"
    assert rec["category"] == "attraction"


def test_parse_nominatim_poi_rejects_outside_bbox(enrich):
    """城市范围外的坐标必须丢弃（不造假坐标）。"""
    bbox = (2.22, 48.79, 2.47, 48.93)
    rec = enrich.parse_nominatim_poi(
        {"lat": "34.0522", "lon": "-118.2437", "name": "LA Downtown", "display_name": "Los Angeles, CA, USA"},
        "巴黎",
        "attraction",
        bbox,
    )
    assert rec is None


def test_foreign_cities_have_no_adcode_and_are_configured(enrich):
    """国外城市配置齐全（wv_title + bbox，无 adcode），自动走 Nominatim 管线。"""
    for city in ("巴黎", "东京", "纽约", "伦敦"):
        cfg = enrich.CITY_CONFIG[city]
        assert "adcode" not in cfg
        assert cfg["wv_title"] and len(cfg["bbox"]) == 4
    # 国内城市仍带 adcode（走高德管线）
    assert "adcode" in enrich.CITY_CONFIG["杭州"]
    assert enrich.NOMINATIM_KEYWORDS.keys() >= {"attraction", "food", "hotel"}
