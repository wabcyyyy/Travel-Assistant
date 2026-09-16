"""两条生成链路共用的落地步骤（G-2.5 ① 治因）。

为什么单独成模块：图节点链路（open_plans）与整段流式链路（trip_stream）此前
各自实现「过滤脏项 + 参考资料落地 + 本地补点」——同一业务两份逻辑，改一处忘
另一处就会出现**流式与图产出不一致**（同一行程走两条路径结果不同）。这里收敛
为唯一实现，两处调用同一函数。

边界（有意不抽的部分）：逐日去重仍留在各链路——图路径用一次性
`drop_cross_day_duplicates` 后处理（事件名 duplicate_cross_day_dropped），
流式路径必须**边流边判**（事件名 stream_duplicate_dropped，且要阻止重复项
触发网络落地），两者的可观测行为不同，强行合并会改变事件序列（INV-2）。

依赖：generation_core（脏项过滤）、reference_pool（参考资料池）、grounding
（本地补点）；无上层依赖。
"""

from typing import Any

from app.agent.generation_core import filter_dirty_items
from app.agent.grounding import local_ground
from app.agent.reference_pool import ReferencePool


def filter_plan_items(items: list[Any] | None) -> list[dict]:
    """落地前的脏项过滤（两条链路共用的一份实现）。"""
    return filter_dirty_items(items)


def ground_item(item: dict, *, city: str, ref_pool: ReferencePool, ground_cache: dict) -> bool:
    """单个点位的事实落地：参考资料命中即回填权威字段，否则本地知识库补点。

    返回是否命中参考资料（供调用方决定是否累计 used_names）。
    """
    if ref_pool.ground(item):
        return True
    local_ground(item, city, ground_cache)
    return False
