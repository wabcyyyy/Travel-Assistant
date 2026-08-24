from app.agent import poi_repository
from app.rag.store import poi_store

# 前端展示标签 → 知识库 tags 关键词（匹配用）
PREFERENCE_KEYWORDS = {
    "人文历史": ("人文", "历史", "文化"),
    "自然风光": ("自然",),
    "美食": ("美食",),
    "网红出片": ("网红", "地标"),
    "主题娱乐": ("娱乐", "乐园", "亲子", "演出"),
    "购物": ("购物", "商圈", "街区"),
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


def search_attractions(city: str, preferences: list[str], limit: int = 30) -> list[dict]:
    poi_store.ensure_loaded()
    hits = poi_store.search(_build_query(city, preferences), city=city, category="attraction", limit=limit)
    if hits:
        return _sort_by_preferences(hits, preferences)[:limit]
    pois = poi_repository.search_pois(city, category="attraction", limit=limit)
    return _sort_by_preferences(pois, preferences)


def search_foods(city: str, limit: int = 10) -> list[dict]:
    poi_store.ensure_loaded()
    hits = poi_store.search(city, city=city, category="food", limit=limit)
    if hits:
        return hits[:limit]
    return poi_repository.search_pois(city, category="food", limit=limit)


def search_hotels(city: str, limit: int = 6) -> list[dict]:
    # 酒店换档需要完整、可枚举的候选集；向量召回适合相关性搜索，但可能漏掉当前档次。
    rows = poi_repository.search_pois(city, category="hotel", limit=limit)
    if rows:
        return rows
    poi_store.ensure_loaded()
    return poi_store.search(f"{city} 住宿", city=city, category="hotel", limit=limit)[:limit]


def get_poi_detail(city: str, name: str) -> dict | None:
    return poi_repository.get_poi(city, name)


def get_consumption(city: str) -> dict | None:
    return poi_repository.get_city_consumption(city)


def search_hotel_room_types(poi_ids: list[int]) -> list[dict]:
    return poi_repository.search_hotel_room_types(poi_ids)


def _match_preferences(poi: dict, keywords: list[str]) -> bool:
    tags = poi.get("tags") or ""
    return any(k in tags for k in keywords)
