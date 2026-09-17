"""参考资料池：权威候选 → 带编号参考资料 → 模型引用落地（G-2.2 自 generators 拆出）。

职责：
- normalize_poi_name / has_valid_coords / is_authoritative_source：名称归一、
  坐标有效性、来源值域校验（后两者是权威背书的判定基础）；
- ReferencePool：把本次候选编成可被模型引用的 [Rn] 资料块，并把模型输出的
  refs 引用落地回权威字段。

实现要点：
- 来源值域校验不可省：/v1/generate-day 的 context 由调用方传入属不可信输入，
  不做值域校验则调用方可伪造 "mysql.poi_knowledge" 让幻觉事实获得权威背书；
- 值域保留历史来源（amap/nominatim）——库里存量行仍带这些 source。

依赖：generation_core；无上层依赖。
"""

import decimal
import re
from collections.abc import Mapping
from typing import Any

from app.agent.generation_core import norm_poi_key  # noqa: F401  (供上层沿用同一归一)

# 开放模式参考资料注入规模：把权威知识库（poi_knowledge）检索结果按编号
# 提供给模型，选点优先从资料中挑并输出 refs 引用编号；规模过大不再加。
REFERENCE_ATTRACTION_LIMIT = 16
REFERENCE_FOOD_LIMIT = 6
REFERENCE_HOTEL_LIMIT = 4

_NAME_NORMALIZE_RE = re.compile(r"[\s（）()【】\[\]·]")

# 权威来源值域：只有这些前缀的 source 才允许为行程项背书
# （verification_status=partially_verified / value_kind=observed）。
# /v1/generate-day 的 context 由 HTTP 调用方传入，属于不可信输入；若不做
# 值域校验，调用方可伪造 "opentripmap" 让幻觉事实获得外部背书。
# POI 库退役后，外部来源即 OpenTripMap / Nominatim（真实坐标与分类）与
# 联网搜索（真实店名）；llm 保留——模型自选点位落 ref 时按 llm 记账。
AUTHORITATIVE_SOURCE_PREFIXES = (
    "opentripmap",
    "nominatim",
    "web.search",
    "llm",
)
# 非权威来源统一改写为该标记，并降级为 unverified/estimated。
UNTRUSTED_SOURCE = "client-context"


def normalize_poi_name(name: str | None) -> str:
    """归一化地点名：去空白/括号/间隔号，供引用匹配使用。"""
    return _NAME_NORMALIZE_RE.sub("", str(name or "")).strip()


def is_authoritative_source(source: object) -> bool:
    text = str(source or "").strip()
    return bool(text) and text.startswith(AUTHORITATIVE_SOURCE_PREFIXES)


def has_valid_coords(poi: Mapping[str, Any]) -> bool:
    """坐标存在且非 0/0（0/0 是缺失坐标的哨兵值，不是有效位置）。

    参数用 Mapping 而非 dict：调用方既有开放 dict（落地草稿），也有
    TypedDict（PoiFactRow 权威行）——TypedDict 可赋给 Mapping，不可赋给 dict。
    """
    lat, lng = poi.get("latitude"), poi.get("longitude")
    if lat is None or lng is None:
        return False
    try:
        return abs(float(lat)) > 1e-6 and abs(float(lng)) > 1e-6
    except (TypeError, ValueError):
        return False


def _json_default(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    return str(o)


class ReferencePool:
    """开放模式的权威参考资料池：编号、注入 Prompt、行程项匹配与使用统计。

    P1 引用式生成的核心：候选池不再只是保底链路的白名单，还被格式化为
    带编号参考资料 [R1]…[Rn] 注入开放模式 Prompt；模型选点时输出 refs
    编号，生成后由 ground_reference_item 落地为权威字段并回填真实来源。
    """

    def __init__(self, context: dict | None, exclude_names: set[str] | None = None) -> None:
        self.references: list[dict] = self._collect(context, exclude_names)
        self.by_name: dict[str, dict] = {}
        self.by_normalized: dict[str, dict] = {}
        for poi in self.references:
            name = str(poi.get("name") or "").strip()
            if name:
                self.by_name.setdefault(name, poi)
                self.by_normalized.setdefault(normalize_poi_name(name), poi)
        self.cited_names: set[str] = set()
        self.stats: dict[str, int] = {
            "references": len(self.references),
            "items": 0,
            "grounded": 0,
            "refs_cited": 0,
            "refs_valid": 0,
            "cited_references": 0,
        }

    @staticmethod
    def _collect(context: dict | None, exclude_names: set[str] | None = None) -> list[dict]:
        """收集参考资料；exclude_names 过滤"已排入/已去过"的 POI。

        注意：过滤会改变 refs 编号，Prompt 渲染（block）与落地（ground）
        必须使用同一 exclude_names 构造的同一个池，编号才对齐。
        """
        ctx = context or {}
        excluded = exclude_names or set()
        collected: list[dict] = []
        seen: set[str] = set()
        for key, limit in (
            ("candidates", REFERENCE_ATTRACTION_LIMIT),
            ("foods", REFERENCE_FOOD_LIMIT),
            ("hotels", REFERENCE_HOTEL_LIMIT),
        ):
            rows = ctx.get(key)
            if not isinstance(rows, list):
                continue
            kept = 0
            for poi in rows:
                if kept >= limit:
                    break
                if not isinstance(poi, dict):
                    continue
                name = str(poi.get("name") or "").strip()
                if not name or name in seen or name in excluded:
                    continue
                seen.add(name)
                collected.append(poi)
                kept += 1
        return collected

    def __len__(self) -> int:
        return len(self.references)

    def block(self) -> str:
        """渲染为注入 Prompt 的参考资料块；空池返回空串。"""
        lines: list[str] = []
        for no, poi in enumerate(self.references, start=1):
            segments = [str(poi.get("category") or "attraction")]
            if poi.get("ticket_price") is not None:
                segments.append(f"票价{float(poi['ticket_price']):g}")
            for key in ("open_time", "address"):
                value = str(poi.get(key) or "").strip()
                if value:
                    segments.append(value)
            lines.append(f"[R{no}] {poi.get('name')}｜" + "｜".join(segments))
        if not lines:
            return ""
        return (
            "权威参考资料（本地知识库，事实可信；行程与备选点优先从这里选，"
            "选中时必须在 item 中输出 refs:[对应编号，如 3]；"
            "资料中没有合适点位时才可用你的知识补充真实存在的地点，无需 refs，禁止编造）：\n" + "\n".join(lines)
        )

    def match(self, item: dict) -> dict | None:
        """行程项 → 参考资料匹配：名称精确/归一化优先，其次 refs 编号。"""
        name = str(item.get("poi_name") or "").strip()
        poi = self.by_name.get(name) or self.by_normalized.get(normalize_poi_name(name))
        if poi is not None:
            return poi
        for ref in item.get("refs") or []:
            if isinstance(ref, bool) or not isinstance(ref, int):
                continue
            if 1 <= ref <= len(self.references):
                return self.references[ref - 1]
        return None

    def _count_refs(self, item: dict) -> None:
        refs = item.get("refs") or []
        valid_ints = [
            r for r in refs if isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= len(self.references)
        ]
        if refs:
            self.stats["refs_cited"] += 1
            if valid_ints:
                self.stats["refs_valid"] += 1

    def ground(self, item: dict) -> bool:
        """把命中参考资料的行程项落地为权威字段；返回是否命中。

        名称命中时保留模型名称；refs 命中时名称归一为权威名，保证后续
        按名查找（format_output / 单日 lookup）一致。transport 为合成项，
        不参与匹配。refs 是生成中间产物，计数与匹配完成后移除。
        """
        if item.get("item_type") == "transport" or not str(item.get("poi_name") or "").strip():
            item.pop("refs", None)
            return False
        self.stats["items"] += 1
        self._count_refs(item)
        name = str(item.get("poi_name") or "").strip()
        poi = self.match(item)
        item.pop("refs", None)  # 匹配完成后移除中间产物，避免进入 TripItem
        if poi is None:
            return False
        # match() 仅在名称查找（原名/归一化名）都未命中时才落到 refs 编号，
        # 因此这里直接按名称查找即可区分两种引用方式。
        matched_by_name = name in self.by_name or normalize_poi_name(name) in self.by_normalized
        self.stats["grounded"] += 1
        poi_name = str(poi.get("name") or "")
        self.cited_names.add(poi_name)
        self.stats["cited_references"] = len(self.cited_names)
        if not matched_by_name:
            item["poi_name"] = poi_name
        item["item_type"] = poi.get("category") or item.get("item_type") or "attraction"
        item["poi_id"] = str(poi.get("id") or "") or item.get("poi_id")
        item["address"] = poi.get("address")
        if has_valid_coords(poi):
            item["latitude"] = float(poi["latitude"])
            item["longitude"] = float(poi["longitude"])
        if poi.get("duration_min"):
            item["duration_min"] = int(poi["duration_min"])
        if poi.get("open_time"):
            item["open_time"] = poi.get("open_time")
        if poi.get("ticket_price") is not None:
            item["cost"] = float(poi["ticket_price"])
        source_name = str(poi.get("source") or "mysql.poi_knowledge")
        updated_at = str(poi.get("source_updated_at") or "") or None
        if not is_authoritative_source(source_name):
            # 参考资料来源不在权威值域内（例如客户端伪造的 context）：
            # 不背书，改写来源并降级为待复核的估算事实。
            item["source"] = UNTRUSTED_SOURCE
            item["source_updated_at"] = None
            item["verification_status"] = "unverified"
            item["value_kind"] = "estimated"
            item["freshness_status"] = "unknown"
            item["review_requirement"] = "before_departure"
            self.stats["untrusted_grounded"] = self.stats.get("untrusted_grounded", 0) + 1
            return True
        item["source"] = source_name
        item["source_updated_at"] = updated_at
        item["verification_status"] = "partially_verified"
        item["value_kind"] = "observed"
        item["freshness_status"] = "fresh" if updated_at else "unknown"
        item["review_requirement"] = "none" if updated_at else "before_departure"
        if not has_valid_coords(poi):
            # 权威行缺坐标：item 上残留的是模型自填坐标，不能随其它字段
            # 一起获得 observed 背书，整体降级为待复核估算。
            item["verification_status"] = "unverified"
            item["value_kind"] = "estimated"
            item["freshness_status"] = "unknown"
            item["review_requirement"] = "before_departure"
        return True


def _prompt_poi(poi: dict) -> dict:
    """为模型保留规划所需字段，避免来源/描述等大字段重复进入 Prompt。"""
    fields = (
        "id",
        "name",
        "category",
        "address",
        "latitude",
        "longitude",
        "ticket_price",
        "duration_min",
        "open_time",
        "tags",
    )
    return {key: poi.get(key) for key in fields if poi.get(key) not in (None, "")}
