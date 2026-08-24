from app.agent import poi_repository
from app.rag.store import poi_store


def _build_query(city: str, preferences: list[str]) -> str:
    parts = [city]
    if preferences:
        parts.extend(preferences)
    return " ".join(parts)


def _sort_by_preferences(pois: list[dict], preferences: list[str]) -> list[dict]:
    if not preferences:
        return pois
    preferred = [p for p in pois if _match_preferences(p, preferences)]
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
    poi_store.ensure_loaded()
    hits = poi_store.search(f"{city} 住宿", city=city, category="hotel", limit=limit)
    if hits:
        return hits[:limit]
    return poi_repository.search_pois(city, category="hotel", limit=limit)


def get_poi_detail(city: str, name: str) -> dict | None:
    return poi_repository.get_poi(city, name)


def get_consumption(city: str) -> dict | None:
    return poi_repository.get_city_consumption(city)


def _match_preferences(poi: dict, preferences: list[str]) -> bool:
    tags = poi.get("tags") or ""
    return any(pref in tags for pref in preferences)