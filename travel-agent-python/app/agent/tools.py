"""面向 Agent 的检索与偏好适配工具集（本地知识库 + RAG；零外部地理 API）。

职责：
- search_attractions / search_foods / search_hotels：统一检索入口，全部落在本地
  `poi_knowledge`（RAG 向量召回 + 权威库 LIKE/枚举回退）；
- search_local_poi：按名称解析单个点位（grounding / 附近锚点用）；
- 把前端展示偏好标签展开为知识库关键词并据此排序；
- 省级目的地展开到具体城市（DESTINATION_CITIES），酒店房型/消费查询转发。

实现要点：
- PREFERENCE_KEYWORDS / DESTINATION_CITIES 做“展示标签 ↔ 知识库 tags/城市”的映射；
- 酒店检索保留完整可枚举候选集（不纯靠向量，避免漏掉当前档次），是生成与编辑链路共用的数据面。

依赖：poi_repository（权威本地库）、rag.store.poi_store（向量召回）。**无高德/Google/Nominatim**。

跨模块 API（G-1.2 提级，供 day_stream 共用）：anchor_name_similar。
"""

import logging
import re

import httpx

from app.agent import poi_repository
from app.agent.trace import traced
from app.common.config import settings
from app.rag.store import poi_store

logger = logging.getLogger(__name__)


def anchor_name_similar(query: str, candidate: str) -> bool:
    """附近推荐锚点解析的名称相似度门槛。

    向量/模糊 LIKE 对乱码或不存在名称也会召回；若候选名与查询几乎无关，
    不能当锚点，否则「不存在的景点」会被错误定位到市中心酒店。
    """

    def norm(s: str) -> str:
        return re.sub(r"[\s·'’\-()（）]", "", str(s or "")).lower()

    q, c = norm(query), norm(candidate)
    if not q or not c:
        return False
    if q == c or q in c or c in q:
        return True
    # 共享足够长的片段才算命中（至少 2 个字符重叠，或候选短名出现在查询中）
    shorter, longer = (q, c) if len(q) <= len(c) else (c, q)
    if len(shorter) >= 2 and shorter in longer:
        return True
    # 字符重叠率：过滤「不存在的景点XYZ123」→「湖滨大酒店」这类弱相关
    overlap = len(set(q) & set(c))
    union = len(set(q) | set(c))
    return union > 0 and overlap / union >= 0.55 and overlap >= 4


# 前端展示标签 → 知识库 tags 关键词（匹配用）
PREFERENCE_KEYWORDS = {
    "人文历史": ("人文", "历史", "文化"),
    "自然风光": ("自然",),
    "美食": ("美食",),
    "网红出片": ("网红", "地标"),
    "主题娱乐": ("娱乐", "乐园", "亲子", "演出"),
    "购物": ("购物", "商圈", "街区"),
}

# 省级目的地在行程主表中可能保留为省名；酒店/POI 知识库按具体城市维护。
DESTINATION_CITIES = {
    "浙江": ["杭州", "宁波", "嘉兴"],
    "福建": ["厦门", "福州", "泉州"],
    "河南": ["洛阳", "郑州", "开封"],
    "广东": ["广州", "深圳", "汕头"],
    "云南": ["昆明", "大理", "丽江"],
    "四川": ["成都", "乐山", "都江堰"],
    "江苏": ["南京", "苏州", "无锡"],
    "山东": ["济南", "青岛", "烟台"],
    "湖南": ["长沙", "张家界", "衡阳"],
    "湖北": ["武汉", "宜昌", "襄阳"],
    "陕西": ["西安", "咸阳", "延安"],
}


def _expand(preferences: list[str]) -> list[str]:
    """把前端展示标签展开为知识库关键词；未映射的原样保留。"""
    out: list[str] = []
    for p in preferences or []:
        out.extend(PREFERENCE_KEYWORDS.get(p, (p,)))
    return out


def _build_query(city: str, preferences: list[str]) -> str:
    parts = [city]
    parts.extend(_expand(preferences))
    return " ".join(parts)


def _sort_by_preferences(pois: list[dict], preferences: list[str]) -> list[dict]:
    if not preferences:
        return pois
    keywords = _expand(preferences)
    preferred = [p for p in pois if _match_preferences(p, keywords)]
    if len(preferred) >= 6:
        return preferred + [p for p in pois if p not in preferred]
    return pois


def _merge_pois(remote: list[dict], local: list[dict]) -> list[dict]:
    """合并候选与本地权威知识，并做同名去重。

    去高德后 `remote` 恒为空列表（调用点保留形参是为了不改动公开签名与既有测试），
    实际职责收敛为：本地去重 + 逐条打 `_authoritative` 标记——只有落在这张
    权威表里的事实才允许进入生成链路的引用。
    """
    local_by_name = {str(item.get("name")): item for item in local if item.get("name")}
    merged: list[dict] = []
    seen: set[str] = set()
    for item in remote:
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        if name in local_by_name:
            combined = dict(local_by_name[name])
            # 远程数据只补充图片/抓取时间；价格、坐标、营业时间等事实保留权威库值。
            for key in ("image", "source_fetched_at"):
                if item.get(key) not in (None, ""):
                    combined[key] = item[key]
            combined["_authoritative"] = True
            merged.append(combined)
            seen.add(name)
    for item in local:
        name = str(item.get("name") or "").strip()
        if name and name not in seen:
            authoritative = dict(item)
            authoritative["_authoritative"] = True
            merged.append(authoritative)
            seen.add(name)
    return merged


@traced("tool", "poi.search_local")
def search_local_poi(city: str, name: str, *, category: str | None = None) -> list[dict]:
    """本地知识库点位检索（去高德后：**不存在**远程 provider chain）。

    顺序：名称精确 → 知识库 LIKE（名称/标签/描述）→ 向量召回。命中与否只依赖
    本地 `poi_knowledge` + Chroma 索引；查不到即返回空，由上层如实降级
    （证据缺口 / 待研究草案），不再引外部地理服务兜底。
    """
    query = str(name or "").strip()
    if not query:
        return []
    exact = poi_repository.search_poi_by_name(query, category)
    if exact:
        return [{**exact, "_authoritative": True}]
    hits = poi_repository.search_pois_by_keyword(city, query, category=category, limit=5)
    if hits:
        return [{**row, "_authoritative": True} for row in hits]
    # 向量库不可用（未建索引/被其它进程占用）不得拖垮调用方：按"未命中"降级
    try:
        poi_store.ensure_loaded()
        hits = poi_store.search(query, city=city, category=category, limit=5)
    except Exception as exc:
        logger.warning("vector store unavailable, local search degrades: %s", exc)
        return []
    # 向量召回对无关词也会给 top-k：必须过名称门槛，否则「池外新地点」会被
    # 无关 POI 顶替（既污染证据池，也让该走向联网补池的缺口被静默填平）。
    return [row for row in hits if anchor_name_similar(query, str(row.get("name") or ""))]


@traced("tool", "poi.search_attractions")
def search_attractions(city: str, preferences: list[str], limit: int = 30) -> list[dict]:
    poi_store.ensure_loaded()
    local = poi_store.search(
        _build_query(city, preferences),
        city=city,
        category="attraction",
        limit=limit,
        preferences=_expand(preferences),
    )
    if not local:
        local = [
            {**poi, "_authoritative": True}
            for poi in poi_repository.search_pois(city, category="attraction", limit=limit)
        ]
    return _sort_by_preferences(_merge_pois([], local), preferences)[:limit]


@traced("tool", "poi.search_foods")
def search_foods(city: str, limit: int = 10) -> list[dict]:
    poi_store.ensure_loaded()
    local = poi_store.search(city, city=city, category="food", limit=limit)
    if not local:
        local = [
            {**poi, "_authoritative": True} for poi in poi_repository.search_pois(city, category="food", limit=limit)
        ]
    return _merge_pois([], local)[:limit]


@traced("tool", "poi.search_hotels")
def search_hotels(city: str, limit: int = 6) -> list[dict]:
    # 酒店换档需要完整、可枚举的候选集；不使用向量 Top-K 截断。
    rows = [{**poi, "_authoritative": True} for poi in poi_repository.list_hotel_pois(city)]
    if not rows and city in DESTINATION_CITIES:
        rows = [
            {**poi, "_authoritative": True}
            for poi in poi_repository.list_hotel_pois_by_cities(DESTINATION_CITIES[city])
        ]
    if rows:
        return rows
    poi_store.ensure_loaded()
    return poi_store.search(f"{city} 住宿", city=city, category="hotel", limit=limit)[:limit]


def get_poi_detail(city: str, name: str) -> dict | None:
    return poi_repository.get_poi(city, name)


@traced("tool", "poi.find_nearby")
def find_nearby_pois(
    city: str,
    name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    limit: int = 5,
    radius_m: int | None = None,
    category: str | None = None,
) -> list[dict]:
    """查找权威知识库中的同城近邻 POI（轻量 GraphRAG，真实坐标网格）。

    坐标优先使用显式传入值；仅给名称时依次尝试权威库详情、知识库检索解析真实
    坐标，并排除锚点自身（“西湖附近”不应包含西湖）。名称在本地库解析不到时
    返回空列表——**不伪造“附近推荐”**，也不再引外部地理服务代解析坐标。
    """
    exclude: str | None = None
    anchor: dict | None = None
    if latitude is None or longitude is None:
        anchor = get_poi_detail(city, str(name or ""))
        if not anchor:
            poi_store.ensure_loaded()
            # 语义检索对乱名也会返回 top-k；必须过名称门槛，否则会错锚。
            for row in poi_store.search(str(name or ""), city=city, limit=5):
                if anchor_name_similar(str(name or ""), str(row.get("name") or "")):
                    anchor = row
                    break
        try:
            latitude = float(anchor.get("latitude")) if anchor else None  # type: ignore[union-attr]
            longitude = float(anchor.get("longitude")) if anchor else None  # type: ignore[union-attr]
        except (TypeError, ValueError):
            latitude = longitude = None
        if latitude in (None, 0.0) or longitude in (None, 0.0):
            return []
    elif name:
        # 坐标已给：仅做轻量锚点解析（不做高德回退），把锚点自身从结果中排除。
        anchor = get_poi_detail(city, name)
        if not anchor:
            poi_store.ensure_loaded()
            for row in poi_store.search(name, city=city, limit=1):
                anchor = row
                break
    if anchor and anchor.get("id") is not None:
        exclude = str(anchor.get("id"))
    return poi_store.nearby(
        city, latitude, longitude, limit=limit, radius_m=radius_m, category=category, exclude=exclude
    )


@traced("tool", "poi.get_consumption")
def get_consumption(city: str) -> dict | None:
    return poi_repository.get_city_consumption(city)


def search_hotel_room_types(poi_ids: list[int]) -> list[dict]:
    return poi_repository.search_hotel_room_types(poi_ids)


_poi_image_cache: dict[tuple[str, str], str | None] = {}


def _unsplash_image(name: str, city: str) -> str | None:
    """从 Unsplash 检索 POI 实景照片（免费 API，返回真实摄影图，非地图位置图）。"""
    if not settings.unsplash_access_key:
        return None
    query = " ".join(x for x in (name, city) if x).strip()
    if not query:
        return None
    try:
        resp = httpx.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query[:60], "per_page": 1, "orientation": "landscape", "content_filter": "high"},
            headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
            timeout=8,
        )
        results = resp.json().get("results") or []
        if results and isinstance(results[0], dict):
            return (results[0].get("urls") or {}).get("regular") or (results[0].get("urls") or {}).get("full")
    except Exception:
        return None
    return None


def _wikipedia_image(name: str) -> str | None:
    """按名称从中文维基百科检索真实照片（知名景点覆盖好，餐厅等可能无图）。"""
    title = re.sub(r"[（(][^（）()]*[)）]", "", name or "").strip()
    if not title:
        return None
    try:
        resp = httpx.get(
            "https://zh.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": title,
                "gsrlimit": "1",
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": "500",
                "format": "json",
            },
            timeout=4,
            headers={"User-Agent": "TravelAssistantDemo/1.0 (student-project; contact=dev@localhost.invalid)"},
        )
        pages = (resp.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                return thumb
    except Exception:
        return None
    return None


def poi_image(name: str | None, city: str) -> str | None:
    """取 POI 图片：优先维基百科真实照片，其次 Unsplash 实景图。

    都取不到时返回 None（**不再回退高德实拍**）——前端拿到 404 后落本地分类
    占位图，比一张错的地图截图更诚实。
    """
    if not name:
        return None
    key = (city, name)
    if key in _poi_image_cache:
        return _poi_image_cache[key]
    url: str | None = None
    if settings.poi_image_wiki:
        url = _wikipedia_image(name)
    if not url:
        url = _unsplash_image(name, city)
    _poi_image_cache[key] = url
    return url


def attach_poi_images(plan: list[dict], city: str) -> list[dict]:
    """为行程项补充 POI 图片：仅对景点/餐饮且尚未有 image 的项走维基/图库检索。"""
    for day in plan:
        for item in day.get("items") or []:
            if item.get("item_type") in ("attraction", "food") and not item.get("image"):
                item["image"] = poi_image(item.get("poi_name"), city)
    return plan


def _match_preferences(poi: dict, keywords: list[str]) -> bool:
    tags = poi.get("tags") or ""
    return any(k in tags for k in keywords)
