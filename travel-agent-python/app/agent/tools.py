"""面向 Agent 的检索与偏好适配工具集（高德 MCP + RAG + 知识库回退）。

职责：
- search_attractions / search_foods / search_hotels：统一检索入口；高德 MCP 开启时
  合并实时 POI 与本地权威知识，失败或为空时回退到 poi_repository；
- 把前端展示偏好标签展开为知识库关键词并据此排序；
- 省级目的地展开到具体城市（DESTINATION_CITIES），酒店房型/消费查询转发。

实现要点：
- PREFERENCE_KEYWORDS / DESTINATION_CITIES 做“展示标签 ↔ 知识库 tags/城市”的映射；
- 酒店检索保留完整可枚举候选集（不纯靠向量，避免漏掉当前档次），是生成与编辑链路共用的数据面。

依赖：amap_mcp（官方外部能力）、poi_repository（权威回退）、rag.store.poi_store（向量召回）。
"""

import re

import httpx

from app.agent import poi_repository
from app.common.config import settings
from app.integrations import amap_mcp, google_maps
from app.rag.store import poi_store
from app.agent.trace import traced


def _anchor_name_similar(query: str, candidate: str) -> bool:
    """附近推荐锚点解析的名称相似度门槛。

    高德/向量对乱码或不存在名称会做模糊召回；若候选名与查询几乎无关，
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


# 高德仅覆盖中国境内；海外目的地若继续用高德检索，会把「岚山/怀石/京都」
# 等关键词误匹配成国内同名 POI（京都行程混入岚山收费站、武夷山野菜等）。
OVERSEAS_CITIES = {
    # 日本
    "东京", "東京", "京都", "大阪", "冲绳", "沖縄", "北海道", "札幌", "奈良",
    "神户", "神戶", "福冈", "福岡", "名古屋", "横滨", "横浜", "镰仓", "鎌倉",
    "富士山", "箱根", "广岛", "広島", "仙台", "那霸",
    # 韩国
    "首尔", "首爾", "釜山", "济州", "濟州",
    # 东南亚
    "曼谷", "清迈", "清萊", "普吉", "新加坡", "吉隆坡", "河内", "胡志明",
    "马尼拉", "雅加达", "巴厘岛", "峇里島",
    # 欧美澳
    "巴黎", "伦敦", "倫敦", "纽约", "洛杉磯", "洛杉矶", "旧金山", "舊金山",
    "悉尼", "墨尔本", "墨爾本", "罗马", "羅馬", "米兰", "米蘭", "巴塞罗那",
    "柏林", "阿姆斯特丹", "迪拜", "杜拜", "莫斯科", "多伦多", "溫哥华", "温哥华",
}


def is_overseas_destination(city: str) -> bool:
    """是否海外目的地：高德不可用，禁止用其结果落坐标/灌候选。"""
    c = str(city or "").strip()
    if not c:
        return False
    if c in OVERSEAS_CITIES:
        return True
    # 「日本东京」「京都府」等带国家/后缀的写法
    for name in OVERSEAS_CITIES:
        if name and name in c:
            return True
    return False


def destination_cities(city: str) -> list[str]:
    return DESTINATION_CITIES.get(city, [city])


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
    """合并 MCP 实时 POI 与本地权威知识。

    同名 POI 保留本地票价、开放时间等业务字段，同时用 MCP 的坐标/地址补新鲜度；
    未命中本地知识的 POI 默认不进入最终候选，避免非权威事实混入生成链路。
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


@traced("tool", "amap.search_poi")
def search_amap_poi(city: str, name: str, *, category: str | None = None) -> list[dict]:
    """查询 POI，优先官方 MCP；未启用/失败时切 Google 兜底。

    Provider chain（高德 → Google）：高德仅覆盖中国境内，国外目的地**禁止**
    走高德——否则「京都/岚山/怀石」会被匹配成国内同名垃圾 POI。
    海外直接走 Google Places；未配置 key 则返回空，由联网补池/模型知识承担。
    """
    overseas = is_overseas_destination(city)
    if not overseas:
        if amap_mcp.enabled():
            payload = amap_mcp.search_poi(name[:12], city=city)
            hits = amap_mcp.normalize_pois(payload, category=category)
            hits = _filter_hits_for_city(hits, city)
            if hits:
                return hits
        hits = _search_amap_rest(name, city, category=category)
        hits = _filter_hits_for_city(hits, city)
        if hits:
            return hits
    # 国外目的地：跳过高德，直接 Google → 可选 Nominatim
    hits = google_maps.search_pois(name, city, category=category)
    if hits:
        return hits
    if settings.nominatim_enabled:
        return google_maps.search_pois_nominatim(name, city, category=category)
    return []


def _filter_hits_for_city(hits: list[dict], city: str) -> list[dict]:
    """国内检索二次过滤：地址应包含目的地城市名，避免 citylimit 失败时串城。"""
    if not hits:
        return hits
    c = str(city or "").strip()
    if not c or len(c) < 2:
        return hits
    # 省级名展开后地址校验意义有限，只做轻过滤
    kept = []
    for h in hits:
        addr = str(h.get("address") or "")
        name = str(h.get("name") or "")
        # 无地址信息时保留（由后续名称相似度门槛处理）
        if not addr:
            kept.append(h)
            continue
        if c in addr or c in name or any(p in addr for p in destination_cities(c)):
            kept.append(h)
        elif any(province_hint in addr for province_hint in (c,)):
            kept.append(h)
        # 明确是其它城市的地址则丢弃
    return kept if kept else []


def _search_amap_rest(name: str, city: str, *, category: str | None = None) -> list[dict]:
    """旧高德 Web API 兼容降级，仅在 MCP 未配置/失败时使用。海外直接返回空。"""
    if not settings.amap_web_key or is_overseas_destination(city):
        return []
    try:
        resp = httpx.get(
            "https://restapi.amap.com/v3/place/text",
            params={
                "key": settings.amap_web_key,
                "keywords": name[:12],
                "city": city,
                "citylimit": "true",
                "offset": 10,
            },
            timeout=10,
        )
        return amap_mcp.normalize_pois(resp.json(), category=category)
    except Exception:
        return []


@traced("tool", "poi.search_attractions")
def search_attractions(city: str, preferences: list[str], limit: int = 30) -> list[dict]:
    poi_store.ensure_loaded()
    local = poi_store.search(
        _build_query(city, preferences), city=city, category="attraction", limit=limit,
        preferences=_expand(preferences),
    )
    if not local:
        local = [{**poi, "_authoritative": True}
                 for poi in poi_repository.search_pois(city, category="attraction", limit=limit)]
    remote = search_amap_poi(_build_query(city, preferences), city, category="attraction") if amap_mcp.enabled() else []
    return _sort_by_preferences(_merge_pois(remote[:limit], local), preferences)[:limit]


@traced("tool", "poi.search_foods")
def search_foods(city: str, limit: int = 10) -> list[dict]:
    poi_store.ensure_loaded()
    local = poi_store.search(city, city=city, category="food", limit=limit)
    if not local:
        local = [{**poi, "_authoritative": True}
                 for poi in poi_repository.search_pois(city, category="food", limit=limit)]
    remote = search_amap_poi(f"{city} 美食", city, category="food") if amap_mcp.enabled() else []
    return _merge_pois(remote[:limit], local)[:limit]


@traced("tool", "poi.search_hotels")
def search_hotels(city: str, limit: int = 6) -> list[dict]:
    # 酒店换档需要完整、可枚举的候选集；不使用向量 Top-K 截断。
    rows = [{**poi, "_authoritative": True} for poi in poi_repository.list_hotel_pois(city)]
    if not rows and city in DESTINATION_CITIES:
        rows = [{**poi, "_authoritative": True}
                for poi in poi_repository.list_hotel_pois_by_cities(DESTINATION_CITIES[city])]
    if rows:
        return rows
    if amap_mcp.enabled():
        remote = search_amap_poi(f"{city} 酒店", city, category="hotel")
        if remote:
            return remote[:limit]
    poi_store.ensure_loaded()
    return poi_store.search(f"{city} 住宿", city=city, category="hotel", limit=limit)[:limit]


def get_poi_detail(city: str, name: str) -> dict | None:
    return poi_repository.get_poi(city, name)


@traced("tool", "poi.find_nearby")
def find_nearby_pois(city: str, name: str | None = None,
                     latitude: float | None = None, longitude: float | None = None,
                     limit: int = 5, radius_m: int | None = None,
                     category: str | None = None) -> list[dict]:
    """查找权威知识库中的同城近邻 POI（轻量 GraphRAG，真实坐标网格）。

    坐标优先使用显式传入值；仅给名称时依次尝试权威库详情、知识库检索、
    高德 POI 检索解析真实坐标，并排除锚点自身（“西湖附近”不应包含西湖）。
    带坐标但带名称时也做轻量锚点解析用于排除自身。全部失败（无真实坐标）
    时返回空列表，不伪造“附近推荐”。
    """
    exclude: str | None = None
    anchor: dict | None = None
    if latitude is None or longitude is None:
        anchor = get_poi_detail(city, str(name or ""))
        if not anchor:
            poi_store.ensure_loaded()
            # 语义检索对乱名也会返回 top-k；必须过名称门槛，否则会错锚。
            for row in poi_store.search(str(name or ""), city=city, limit=5):
                if _anchor_name_similar(str(name or ""), str(row.get("name") or "")):
                    anchor = row
                    break
        if not anchor:
            # 名称在权威库解析不到（如开放模式的自选点），用高德解析真实坐标；
            # 高德结果即真实坐标，不是伪造，只是锚点定位而非数据来源。
            # MCP 未启用/失败时 search_amap_poi 内部已回退 Web API，仍无则返回空。
            try:
                remote = search_amap_poi(city, str(name or ""))
            except Exception:  # noqa: BLE001 - 高德失败按无坐标处理
                remote = []
            # 只接受名称足够接近的召回，避免模糊命中把乱名锚到任意 POI。
            for row in remote or []:
                if _anchor_name_similar(str(name or ""), str(row.get("name") or "")):
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
    return poi_store.nearby(city, latitude, longitude, limit=limit,
                            radius_m=radius_m, category=category, exclude=exclude)


@traced("tool", "poi.get_consumption")
def get_consumption(city: str) -> dict | None:
    return poi_repository.get_city_consumption(city)


def search_hotel_room_types(poi_ids: list[int]) -> list[dict]:
    return poi_repository.search_hotel_room_types(poi_ids)


_poi_image_cache: dict[tuple[str, str], str | None] = {}


def _is_map_thumbnail(photo: dict) -> bool:
    """高德 POI 的 photos 常含一张“地图位置图”缩略图，按标题过滤掉。"""
    title = photo.get("title") or ""
    return "地图" in title or "位置" in title


def _amap_photo_url(name: str, city: str) -> str | None:
    """从高德 POI 检索取首张“非地图位置图”的图片 URL（高德多为位置图，仅作兜底）。"""
    if amap_mcp.enabled():
        for poi in search_amap_poi(city, name):
            if poi.get("image"):
                return poi["image"]
        return None
    if not settings.amap_web_key:
        return None
    try:
        resp = httpx.get(
            "https://restapi.amap.com/v3/place/text",
            params={
                "key": settings.amap_web_key,
                "keywords": name[:12],
                "city": city,
                "citylimit": "true",
                "offset": 1,
            },
            timeout=10,
        )
        pois = resp.json().get("pois") or []
        if pois and isinstance(pois[0], dict):
            for photo in pois[0].get("photos") or []:
                if isinstance(photo, dict) and not _is_map_thumbnail(photo) and photo.get("url"):
                    return photo["url"]
    except Exception:
        return None
    return None


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
        results = (resp.json().get("results") or [])
        if results and isinstance(results[0], dict):
            return ((results[0].get("urls") or {}).get("regular")
                    or (results[0].get("urls") or {}).get("full"))
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
    """取 POI 图片：优先维基百科真实照片，其次 Unsplash 实景图，最后回退高德（已过滤地图位置图）。"""
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
    if not url:
        url = _amap_photo_url(name, city)
    _poi_image_cache[key] = url
    return url


def attach_poi_images(plan: list[dict], city: str) -> list[dict]:
    """为行程项补充 POI 图片：仅对景点/餐饮且尚未有 image 的项调用高德检索。"""
    for day in plan:
        for item in day.get("items") or []:
            if item.get("item_type") in ("attraction", "food") and not item.get("image"):
                item["image"] = poi_image(item.get("poi_name"), city)
    return plan


def _match_preferences(poi: dict, keywords: list[str]) -> bool:
    tags = poi.get("tags") or ""
    return any(k in tags for k in keywords)
