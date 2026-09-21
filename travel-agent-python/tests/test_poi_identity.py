"""PoiSeenRegistry 坐标通道的判定口径。

这条近距离判重通道是 2026-09-20 第 1 轮评审里的 P0：实现把 `item_type` 绑成 `_t`
却从不按它过滤，于是"景点"只要挨着一家"餐厅"（商场/寺庙咖啡座是常态）就被当成
重复项从行程里删掉，只留一条 `stream_duplicate_dropped` 遥测。类 docstring 与
`trip_stream._prepare_day` 的顺序注释写的都是**同类型** <80m，代码与文档相反。

`test_stream_snapshot.py` 的黄金件当时把这个行为固化了下来（被删的点位出现在
suggestions 里而不是日计划里），所以只有这里能挡住回归。
"""

from __future__ import annotations

from app.agent.poi_identity import PoiSeenRegistry

# 相距约 22m（纬度差 0.0002）——同一栋建筑里的两个不同业态
ATTRACTION = ("圣家堂", "attraction", 41.4030, 2.1740)
NEARBY_SHOP = ("圣家堂商店咖啡", "food", 41.4032, 2.1740)
NEARBY_ATTRACTION = ("圣家堂大教堂", "attraction", 41.4032, 2.1740)


def test_proximity_channel_is_same_type_only() -> None:
    registry = PoiSeenRegistry()
    registry.register(*ATTRACTION)
    assert not registry.is_duplicate(*NEARBY_SHOP), "跨类型近距离不是重复：这是真实点位被误删的那条路径"
    assert registry.is_duplicate(*NEARBY_ATTRACTION), "同类型 <80m 是名称变体指向同一地点，必须判重"


def test_name_channel_still_catches_exact_repeats() -> None:
    registry = PoiSeenRegistry()
    registry.register(*ATTRACTION)
    assert registry.is_duplicate("圣家堂", "attraction"), "同名重复与坐标无关"
    assert registry.is_duplicate("圣家堂", "attraction", None, None), "缺坐标时退化为纯名称判定，不得抛错"


def test_hotel_never_participates() -> None:
    registry = PoiSeenRegistry()
    registry.register("巴塞罗那舒适酒店", "hotel", 41.40, 2.17)
    registry.register("巴塞罗那是那酒店", "attraction", 41.40, 2.17)
    assert not registry.is_duplicate("另一天同一家酒店", "hotel", 41.40, 2.17), "N-1 晚摊铺语义：跨天同酒店合法"
    assert registry.is_duplicate("又一家景点", "attraction", 41.40, 2.17)


def test_far_apart_same_type_is_kept() -> None:
    registry = PoiSeenRegistry()
    registry.register("甲景点", "attraction", 41.40, 2.17)
    assert not registry.is_duplicate("乙景点", "attraction", 41.50, 2.27)
