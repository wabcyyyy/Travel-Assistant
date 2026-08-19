from app.agent import poi_repository


def search_attractions(city: str, preferences: list[str], limit: int = 30) -> list[dict]:
    pois = poi_repository.search_pois(city, category="attraction", limit=limit)
    if preferences:
        preferred = [p for p in pois if _match_preferences(p, preferences)]
        if len(preferred) >= 6:
            pois = preferred + [p for p in pois if p not in preferred]
    return pois


def search_foods(city: str, limit: int = 10) -> list[dict]:
    return poi_repository.search_pois(city, category="food", limit=limit)


def get_poi_detail(city: str, name: str) -> dict | None:
    return poi_repository.get_poi(city, name)


def get_consumption(city: str) -> dict | None:
    return poi_repository.get_city_consumption(city)


def _match_preferences(poi: dict, preferences: list[str]) -> bool:
    tags = poi.get("tags") or ""
    return any(pref in tags for pref in preferences)