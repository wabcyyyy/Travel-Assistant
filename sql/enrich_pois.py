#!/usr/bin/env python3
"""P0 数据管线：把真实 POI 数据灌入 poi_knowledge（替代种子假数据）。

流水线（2026-09-10 定稿：零 LLM 为默认模式）：
  1. 高德 Web API 采集（真坐标/地址/评分/人均，extensions=all），
     按 attraction/food/hotel 类别与目标数量过滤、去重、清洗；
  2. Wikivoyage（英文为主）MediaWiki API 采集 See/Do/Eat/Drink/Sleep listing，
     默认直接以**原文**（名称/描述/价格/时间）构建记录并入库（零模型成本，
     每城分钟级）；指定 --with-llm 时改为 LLM 翻译成中文并按坐标 <200m 与
     高德结果交叉合并；
  3. LLM 兜底补齐（仅 --with-llm）：高德记录缺项 description/tags/duration_min/open_time；
  4. 清洗校验：坐标必须落目标城市范围（不造假坐标）、名称去重、长度截断；
  5. pymysql 增量 upsert：按 (city, 归一化名称) 匹配已有行，字段"新值非空才覆盖"，
     source 记录真实来源，source_updated_at 填真实时间；
  6. 结尾调 poi_store.ensure_loaded(force=True) 立即同步 Chroma 索引。

source 取值：amap.poi / wikivoyage / llm，多来源用 + 连接（如 amap.poi+llm、
wikivoyage、wikivoyage+llm）。Wikivoyage 内容遵循 CC BY-SA，署名落在 source 字段。

注意（零 LLM 模式的语言/字段取舍）：
- Wikivoyage 原文多为英文，中文查询 + hashed 词袋向量下检索命中弱；如知识库服务
  中文查询，建议搭配 bge-m3 语义向量或改用中文维基（zh.wikivoyage.org）采集源。
- 零 LLM 模式缺 tags/open_time/duration_min：tags 用规则推导，其余留空如实降级。

用法（请使用 travel-agent-python/.venv 的 Python 运行）：
    python sql/enrich_pois.py --cities 北京 --dry-run          # 最小试跑，零 LLM，不写库
    python sql/enrich_pois.py --cities 北京 杭州                # 零 LLM 默认模式增量灌库
    python sql/enrich_pois.py --cities 北京 --with-llm          # 可选：LLM 翻译+补齐（高质量）
    python sql/enrich_pois.py --cities 巴黎 东京               # 国外城市：Nominatim 免 key + Wikivoyage 原文
    python sql/enrich_pois.py                                   # 全部默认城市

国外城市（CITY_CONFIG 中无 adcode，如 巴黎/东京/纽约/伦敦）自动走
Nominatim 免 key 采集 + Wikivoyage 原文入库（零 LLM、零模型费）；国内城市
需要 AMAP_WEB_KEY。新增国外城市只需在 CITY_CONFIG 加 {wv_title, bbox}。

注意：
- 默认（零 LLM）每城约 1-3 分钟纯 API 调用、零模型费用；--with-llm 时全程数分钟
  到几十分钟（主要耗时在 LLM 批量补齐/翻译）。
- 脚本会在同进程内同步 Chroma 索引文件；运行中的 FastAPI 服务会在
  RAG_REFRESH_SECONDS（默认 60s）内惰性感知数据变化并增量同步，无需重启。
- 首次部署需先执行 sql/add_poi_avg_cost_and_unique.sql（avg_cost 列 +
  (city,name) 唯一键 + 历史重复行收敛），否则本脚本写库会因缺列失败。
- --prune-seed 为可选的种子清理：删除本次运行城市中 source 仍为
  'mysql.poi_knowledge'（默认种子来源）且未被本管线匹配更新的旧行；
  手工增补 SQL（如杭州分档酒店）若未被高德命中也会被删，请谨慎使用。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "travel-agent-python"))

from app.common.config import settings  # noqa: E402  依赖上面的 sys.path 注入
from app.common import db_pool  # noqa: E402


def _pooled_connect():
    """管线写库也走连接池，与 Agent 只读路径共享建连参数与超时。"""
    return db_pool.acquire()

# ---------------------------------------------------------------------------
# 城市与类别配置
# ---------------------------------------------------------------------------

CITY_CONFIG: dict[str, dict] = {
    # 国内城市（含 adcode）：走高德采集
    "北京": {"wv_title": "Beijing", "adcode": "110000", "bbox": (115.4, 39.4, 117.5, 41.1)},
    "上海": {"wv_title": "Shanghai", "adcode": "310000", "bbox": (120.8, 30.6, 122.2, 31.9)},
    "成都": {"wv_title": "Chengdu", "adcode": "510100", "bbox": (102.9, 30.1, 104.9, 31.5)},
    "西安": {"wv_title": "Xi'an", "adcode": "610100", "bbox": (107.4, 33.7, 109.8, 34.8)},
    "三亚": {"wv_title": "Sanya", "adcode": "460200", "bbox": (108.9, 17.8, 110.0, 18.6)},
    "杭州": {"wv_title": "Hangzhou", "adcode": "330100", "bbox": (118.3, 29.2, 120.9, 30.6)},
    # 国外城市（无 adcode）：自动走 Nominatim 免 key + Wikivoyage 原文采集
    "巴黎": {"wv_title": "Paris", "bbox": (2.22, 48.79, 2.47, 48.93)},
    "东京": {"wv_title": "Tokyo", "bbox": (139.60, 35.55, 139.90, 35.80)},
    "纽约": {"wv_title": "New York City", "bbox": (-74.26, 40.49, -73.70, 40.92)},
    "伦敦": {"wv_title": "London", "bbox": (-0.51, 51.28, 0.33, 51.69)},
}

# 高德分类编码：风景名胜 / 餐饮服务 / 住宿服务
AMAP_TYPES = {"attraction": "110000", "food": "050000", "hotel": "100000"}
CATEGORIES = ("attraction", "food", "hotel")
CATEGORY_CN = {"attraction": "景点", "food": "美食", "hotel": "酒店"}

# 评分下限（过滤低质连锁/杂项；酒店放宽以覆盖经济档，供换档测试）
RATING_FLOOR = {"attraction": 3.8, "food": 4.0, "hotel": 3.5}

# 类型/名称黑名单：过滤非旅游场景（舞厅、批发、招待所等低质类目）
BLACKLIST_TYPE_WORDS = (
    "舞厅", "夜总会", "卡拉OK", "KTV", "网吧", "棋牌", "桑拿", "洗浴", "按摩", "足疗",
    "美容", "美发", "招待所", "批发", "菜市场", "劳务", "人才市场", "五金", "建材",
    "装修", "维修", "加油", "加气", "充电", "停车场", "收费站", "票务", "公司", "工厂",
    "学校", "幼儿园", "培训", "医院", "诊所", "药店", "银行", "证券", "保险",
    "房地产", "公寓式办公楼", "写字楼", "殡仪", "公墓",
)
BLACKLIST_NAME_WORDS = ("停车场", "公厕", "收费站", "加油站", "售票处", "游客中心")

TAG_SET = ("人文", "历史", "文化", "自然", "美食", "网红", "地标", "娱乐", "乐园",
           "亲子", "演出", "购物", "商圈", "街区")

# Wikivoyage listing 模板 → 项目类别。部分页面（如 Beijing）统一用 {{listing|type=see}}
# 通用模板，type= 参数决定类别（buy 等不在映射内的跳过）；其余页面用 see/do 简写。
WV_TEMPLATE_CATEGORY = {
    "see": "attraction", "do": "attraction",
    "eat": "food", "drink": "food",
    "sleep": "hotel",
}
WV_CONTAINER_TEMPLATE = "listing"

SOURCE_ORDER = {"amap.poi": 0, "wikivoyage": 1, "llm": 2, "nominatim": 3}

WV_HEADERS = {"User-Agent": "TravelAssistantEnrich/0.1 (local course project; one-off batch)"}


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def norm_name(name: str) -> str:
    """归一化名称用于匹配：统一括号/去空白/去首尾标点/大小写折叠。

    casefold 是必须的：poi_knowledge 的 (city,name,category) 唯一键用 MySQL 的
    CI 排序规则（大小写不敏感），"Lush酒吧" 与 "lush酒吧" 在库里算同一行。若
    Python 匹配键保留大小写，二者被判为不同 → 走 INSERT → 撞 1062。折叠后
    Python 的匹配粒度与 DB 唯一键一致（甚至更粗，因还剥空白/括号），保证任何
    会撞唯一键的情况都先被 Python 归为同一行、走 UPDATE 而非 INSERT。
    """
    s = str(name or "").strip()
    s = s.replace("（", "(").replace("）", ")").replace("　", "")
    s = re.sub(r"\s+", "", s)
    return s.strip(" ,.;:、，。；：").casefold()


def clean_text(value, limit: int) -> str | None:
    """清洗为定长字符串；空值返回 None。"""
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s[:limit] if s else None


def to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group()) if m else None


def distance_m(lng1, lat1, lng2, lat2) -> float:
    dx = (lng1 - lng2) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat1 - lat2) * 110540.0
    return math.hypot(dx, dy)


def in_bbox(bbox, lng: float, lat: float) -> bool:
    min_lng, min_lat, max_lng, max_lat = bbox
    return min_lng <= lng <= max_lng and min_lat <= lat <= max_lat


def compose_source(parts: set[str]) -> str:
    ordered = sorted((p for p in parts if p in SOURCE_ORDER), key=SOURCE_ORDER.get)
    return "+".join(ordered) or "amap.poi"


def new_record(city: str, name: str, category: str) -> dict:
    return {
        "city": city, "name": name, "category": category,
        "address": None, "latitude": None, "longitude": None,
        "ticket_price": None, "avg_cost": None, "duration_min": None, "open_time": None,
        "tags": None, "rating": None, "description": None,
        "_source_parts": set(), "_amap_id": None,
    }


# ---------------------------------------------------------------------------
# 高德采集
# ---------------------------------------------------------------------------

def amap_get(path: str, params: dict, retries: int = 2) -> dict:
    url = f"https://restapi.amap.com/{path}"
    last_info = ""
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, params=params, timeout=15)
            data = resp.json()
            if str(data.get("status")) == "1":
                return data
            last_info = f"{data.get('infocode')} {data.get('info')}"
        except Exception as exc:  # noqa: BLE001 - 网络抖动重试
            last_info = str(exc)
        if attempt < retries:
            time.sleep(1.0 + attempt)
    print(f"    [warn] 高德请求失败 {path}: {last_info}")
    return {}


def fetch_city_bbox(city: str, fallback: tuple, adcode: str | None = None) -> tuple:
    """用高德行政区 API 动态求城市范围，失败退回硬编码 bbox。

    用 adcode 精确查询：全国有多个同名/重名区县（如牡丹江市"西安区"），
    按"西安"关键词会匹配到错误行政区，导致 bbox 校验误杀全部 POI。
    """
    data = amap_get("v3/config/district", {
        "key": settings.amap_web_key, "keywords": adcode or city,
        "subdistrict": 0, "extensions": "all", "output": "json",
    })
    districts = data.get("districts") or []
    polyline = (districts[0].get("polyline") or "") if districts else ""
    points: list[tuple[float, float]] = []
    for ring in polyline.split("|"):
        for pair in ring.split(";"):
            parts = pair.split(",")
            if len(parts) == 2:
                try:
                    points.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    continue
    if len(points) >= 3:
        lngs = [p[0] for p in points]
        lats = [p[1] for p in points]
        bbox = (min(lngs), min(lats), max(lngs), max(lats))
        # 防御：行政区匹配错位时（如"西安"命中牡丹江西安区），bbox 不含参考中心点
        center_lng = (fallback[0] + fallback[2]) / 2
        center_lat = (fallback[1] + fallback[3]) / 2
        if in_bbox(bbox, center_lng, center_lat):
            return bbox
        print(f"    [warn] 行政区 bbox 异常（不含 {city} 参考中心点），改用硬编码 bbox")
    return fallback


def rule_tags(name: str, type_str: str, category: str) -> list[str]:
    """规则兜底打标（LLM 不可用时仍能映射到 PREFERENCE_KEYWORDS 体系）。"""
    joined = f"{name} {type_str}"
    tags: list[str] = []
    if re.search(r"博物馆|美术馆|展览|科技馆|天文馆|纪念馆|美术馆", joined):
        tags += ["人文", "历史"]
    if re.search(r"寺|庙|观|教堂|清真|塔|陵|祠|故居|遗址|碑", joined):
        tags += ["历史", "人文"]
    if re.search(r"公园|山|湖|海|岛|湾|森林|湿地|峡谷|瀑布|泉|滩|溪|草原", joined):
        tags += ["自然"]
    if re.search(r"广场|电视塔|地标|大厦|中心大厦|双塔|塔", joined):
        tags += ["地标"]
    if re.search(r"步行街|商圈|商场|百货|购物|城|街|巷|胡同|坊", joined):
        tags += ["购物", "街区"]
    if re.search(r"乐园|游乐园|主题|水上|欢乐|梦幻", joined):
        tags += ["乐园", "娱乐"]
    if re.search(r"剧场|剧院|演艺|千古情|印象|秀场", joined):
        tags += ["演出"]
    if re.search(r"动物园|植物园|海洋馆|水族馆|恐龙|熊猫", joined):
        tags += ["亲子"]
    if re.search(r"古镇|古城|老街|历史街区|文化街", joined):
        tags += ["人文", "街区"]
    if re.search(r"网红|打卡|潮流", joined):
        tags += ["网红"]
    if category == "food":
        tags.append("美食")
    out: list[str] = []
    for t in tags:
        if t in TAG_SET and t not in out:
            out.append(t)
    return out[:3]


def parse_amap_poi(raw: dict, city: str, category: str, bbox: tuple) -> dict | None:
    name = str(raw.get("name") or "").strip()
    if not name or any(w in name for w in BLACKLIST_NAME_WORDS):
        return None
    if category == "attraction" and re.search(
        r"-[^-]{1,8}(殿|门|楼|阁|亭|厅|馆|台|塔|桥|廊|院|墓|窟|碑|码头|索道|停车场)$", name
    ):
        return None  # 过滤"故宫博物院-中和殿"这类子殿宇级 POI，只留主入口
    type_str = str(raw.get("type") or "")
    if any(w in type_str for w in BLACKLIST_TYPE_WORDS):
        return None

    location = str(raw.get("location") or "")
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        lng, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not in_bbox(bbox, lng, lat):
        return None

    biz = raw.get("biz_ext") or {}
    rating = to_float(biz.get("rating"))
    if rating is None or rating < RATING_FLOOR[category]:
        return None
    cost = to_float(biz.get("cost"))

    open_time = None
    for key in ("opentime2", "opentime_week", "opentime_today", "open_time"):
        if biz.get(key):
            open_time = clean_text(biz.get(key), 62)
            break

    rec = new_record(city, name, category)
    rec.update({
        "address": clean_text(raw.get("address"), 254) or None,
        "latitude": round(lat, 6), "longitude": round(lng, 6),
        # 高德 biz_ext.cost 是"人均消费"。对景点它不是门票价，落 avg_cost，
        # ticket_price 留给真实门票来源（Wikivoyage/LLM 明确给出的门票价），
        # 避免"人均"冒充"门票"造成景点票价系统性偏差；餐饮/酒店沿用
        # ticket_price 承载人均/房价（下游预算按此列取价，保持既有契约）。
        "avg_cost": (round(cost, 2) if category == "attraction" and cost is not None and cost >= 0 else None),
        "ticket_price": (round(cost, 2) if category != "attraction" and cost is not None and cost >= 0 else None),
        "open_time": open_time,
        "rating": min(round(rating, 1), 5.0),
        "tags": ",".join(rule_tags(name, type_str, category)) or None,
        "_amap_id": str(raw.get("id") or ""),
    })
    rec["_source_parts"].add("amap.poi")
    return rec


def brand_of(name: str) -> str:
    """去掉尾部括号分店名得到品牌名，用于连锁去重。"""
    return re.sub(r"[（(].*?[）)]\s*$", "", name).strip()


def fetch_amap_pois(city: str, category: str, target: int, pages: int, bbox: tuple) -> list[dict]:
    """按类别分页采集高德 POI：黑名单过滤 → 评分门槛 → 去重 → 截断目标数量。"""
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    best_by_brand: dict[str, dict] = {}
    base_params = {
        "key": settings.amap_web_key, "city": city, "citylimit": "true",
        "types": AMAP_TYPES[category], "offset": 25, "extensions": "all", "output": "json",
    }
    for page in range(1, pages + 1):
        data = amap_get("v3/place/text", {**base_params, "page": page})
        pois = data.get("pois") or []
        if not pois:
            break
        for raw in pois:
            poi_id = str(raw.get("id") or "")
            if poi_id and poi_id in seen_ids:
                continue
            rec = parse_amap_poi(raw, city, category, bbox)
            if rec is None:
                continue
            if poi_id:
                seen_ids.add(poi_id)
            key = norm_name(rec["name"])
            if key in seen_names:
                continue
            seen_names.add(key)
            if category in ("food", "hotel"):
                # 连锁分店只保留评分最高的一家，避免品牌刷屏。
                brand = brand_of(rec["name"])
                old = best_by_brand.get(brand)
                if old is not None:
                    if (rec["rating"] or 0) > (old["rating"] or 0):
                        out[out.index(old)] = rec
                        best_by_brand[brand] = rec
                    continue
                best_by_brand[brand] = rec
            out.append(rec)
        time.sleep(0.15)
        if len(out) >= target:
            break
    out.sort(key=lambda r: r["rating"] or 0.0, reverse=True)
    return out[:target]


# ---------------------------------------------------------------------------
# 国外采集（Nominatim 免 key + Wikivoyage 原文）
# ---------------------------------------------------------------------------

# Nominatim 品类检索词（OSM 无类型过滤，用关键词 + 城市边界收敛）
NOMINATIM_KEYWORDS = {
    "attraction": "tourist attraction museum landmark",
    "food": "restaurant",
    "hotel": "hotel",
}


def parse_nominatim_poi(raw: dict, city: str, category: str, bbox: tuple) -> dict | None:
    """Nominatim 结果 → 内部 POI 契约（source=nominatim，坐标必须落城市范围）。"""
    latitude, longitude = to_float(raw.get("lat")), to_float(raw.get("lon"))
    if latitude is None or longitude is None or not in_bbox(bbox, longitude, latitude):
        return None
    display = str(raw.get("display_name") or "").strip()
    short_name = str(raw.get("name") or "").strip()
    name = clean_text(short_name or display.split(",")[0], 126)
    if not name or any(w in name for w in BLACKLIST_NAME_WORDS):
        return None
    rec = new_record(city, name, category)
    rec.update({
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "address": clean_text(display, 200),
        "description": clean_text(display, 200),
        "rating": to_float((raw.get("extratags") or {}).get("rating")),
    })
    rec["_source_parts"] |= {"nominatim"}
    return rec


def fetch_nominatim_pois(city: str, category: str, target: int, bbox: tuple) -> list[dict]:
    """Nominatim 免 key 采集：viewbox 边界检索真实坐标；遵循 1 req/s 限流。"""
    out: list[dict] = []
    seen_names: set[str] = set()
    query = f"{city} {NOMINATIM_KEYWORDS[category]}"
    viewbox = f"{bbox[0]},{bbox[3]},{bbox[2]},{bbox[1]}"  # left,top,right,bottom
    for page in range(1, 4):
        try:
            resp = httpx.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 50, "viewbox": viewbox,
                        "bounded": 1, "addressdetails": 0, "extratags": 1},
                headers={"User-Agent": "travel-agent/1.0 (itinerary; demo)",
                         "Accept-Language": "zh-CN,en"},
                timeout=30,
            )
            resp.raise_for_status()
            rows = resp.json() or []
        except Exception as exc:  # noqa: BLE001 - 外部服务失败允许降级
            print(f"    [warn] Nominatim 采集失败（{city}/{category} 第{page}页）: {exc}")
            break
        if not rows:
            break
        for raw in rows:
            rec = parse_nominatim_poi(raw, city, category, bbox)
            if rec is None:
                continue
            key = norm_name(rec["name"])
            if key in seen_names:
                continue
            seen_names.add(key)
            out.append(rec)
        if len(out) >= target:
            break
        time.sleep(1.0)  # Nominatim 使用政策：≥1 req/s 间隔
    out.sort(key=lambda r: r["rating"] or 0.0, reverse=True)
    return out[:target]


# ---------------------------------------------------------------------------
# Wikivoyage 采集（英文 MediaWiki API）
# ---------------------------------------------------------------------------

def match_braces(text: str, start: int) -> int:
    """返回与 text[start:start+2] == '{{' 配对的 '}}' 之后的下标；失败返回 -1。"""
    depth, i = 0, start
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return -1


def split_template_params(body: str) -> list[str]:
    """按深度为 0 的 '|' 切分模板参数（正确跳过嵌套模板/链接）。"""
    parts: list[str] = []
    buf: list[str] = []
    depth, i = 0, 0
    while i < len(body):
        if body.startswith("{{", i):
            depth += 1
            buf.append(body[i:i + 2])
            i += 2
            continue
        if body.startswith("}}", i):
            depth -= 1
            buf.append(body[i:i + 2])
            i += 2
            continue
        if body.startswith("[[", i):
            depth += 1
            buf.append("[[")
            i += 2
            continue
        if body.startswith("]]", i):
            depth -= 1
            buf.append("]]")
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def clean_wikitext(value: str | None) -> str:
    if not value:
        return ""
    s = value
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\[\[(?:File|Image):[^\]]+\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]+)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


_SECTION_RE = re.compile(r"^\s*(={2,5})\s*(.+?)\s*\1\s*$", re.M)
_SECTION_RESET_RE = re.compile(
    r"\bunderstand\b|\bget in\b|\bget around\b|\btalk\b|\bclimate\b|\bbuy\b|\bitinerary\b"
    r"|\bregion\b|\bdistrict\b|\barrival\b|\bdeparture\b|\bvisa\b|\bother\b|\bcontact\b"
    r"|\bstay safe\b|\bcope\b|\brespect\b|\bemergency\b|\bhealth\b|\blearn\b|\bwork\b|\bnext\b"
    r"|\bembass|\buniversit|\bschool\b|\bmobil\b|\binternet\b|\bworship\b|\bpayment\b"
)


def section_category(title: str) -> str | None:
    """Wikivoyage 章节标题 → 类别；None 表示重置/未知（其下无 type 的 listing 丢弃）。"""
    t = re.sub(r"[^\w\s]+", " ", title.lower())
    if _SECTION_RESET_RE.search(t):
        return None
    if re.search(r"\bsee\b|sight|attraction|landmark|view", t):
        return "attraction"
    if re.search(r"\bdo\b|activit|experience|entertainment", t):
        return "attraction"
    if re.search(r"\beat\b|cuisine|\bfood\b", t):
        return "food"
    if re.search(r"\bdrink\b|nightlife|\bbar\b", t):
        return "food"
    if re.search(r"\bsleep\b|accommodation|hotel|\bstay\b|lodge", t):
        return "hotel"
    return "unknown"  # 未知标题不重置上一章节状态


def iter_listings(wikitext: str):
    """按顺序产出 (模板名, 模板体, 当前章节类别)；同时跟踪 == 标题 === 位置。"""
    sections = [(m.start(), m.group(2)) for m in _SECTION_RE.finditer(wikitext)]
    si, current = 0, None
    i, n = 0, len(wikitext)
    matchable = set(WV_TEMPLATE_CATEGORY) | {WV_CONTAINER_TEMPLATE}

    def advance_to(pos: int) -> None:
        nonlocal si, current
        while si < len(sections) and sections[si][0] < pos:
            cat = section_category(sections[si][1])
            if cat in WV_TEMPLATE_CATEGORY.values() or cat is None:
                current = cat
            si += 1

    while i < n:
        advance_to(i)
        start = wikitext.find("{{", i)
        if start < 0:
            return
        advance_to(start)
        end = match_braces(wikitext, start)
        if end < 0:
            return
        body = wikitext[start + 2:end - 2]
        header = body.split("|", 1)[0].strip().lower()
        if header in matchable:
            yield header, body, current
        i = end


def fetch_wikivoyage_subpages(title: str, limit: int = 12) -> list[str]:
    """大城市（如 Beijing）把 listing 拆分到地区子页；用 allpages API 列出 {title}/ 子页。"""
    try:
        resp = httpx.get(
            "https://en.wikivoyage.org/w/api.php",
            params={
                "action": "query", "list": "allpages", "apprefix": f"{title}/",
                "apnamespace": 0, "aplimit": 50, "format": "json", "formatversion": 2,
            },
            headers=WV_HEADERS, timeout=30, follow_redirects=True,
        )
        resp.raise_for_status()
        pages = ((resp.json().get("query") or {}).get("allpages") or [])
        titles = [p.get("title") for p in pages if p.get("title") and "/" in str(p.get("title"))]
        return titles[:limit]
    except Exception as exc:  # noqa: BLE001 - 子页列举失败不影响主页面
        print(f"    [warn] Wikivoyage 子页列举失败（title={title}）: {exc}")
        return []


def fetch_wikivoyage_listings(title: str, retries: int = 3) -> list[dict]:
    """拉取 Wikivoyage 页面并解析 listing（含名称/坐标/价格/时间/描述）。"""
    wikitext = ""
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(
                "https://en.wikivoyage.org/w/api.php",
                params={
                    "action": "parse", "page": title, "prop": "wikitext",
                    "format": "json", "formatversion": 2, "redirects": 1,
                },
                headers=WV_HEADERS, timeout=30, follow_redirects=True,
            )
            resp.raise_for_status()
            wikitext = (resp.json().get("parse") or {}).get("wikitext") or ""
            break
        except Exception as exc:  # noqa: BLE001 - Wikimedia 限流/不可达时重试
            if attempt >= retries:
                print(f"    [warn] Wikivoyage 采集失败（title={title}）: {exc}")
                return []
            time.sleep(8.0 * (attempt + 1))  # 429 限流退避

    listings: list[dict] = []
    for tpl, body, section in iter_listings(wikitext):
        named: dict[str, str] = {}
        unnamed: list[str] = []
        for part in split_template_params(body)[1:]:
            m = re.match(r"\s*([A-Za-z_][A-Za-z_0-9 ]*?)\s*=(.*)", part, re.S)
            if m:
                named[m.group(1).strip().lower()] = m.group(2)
            else:
                unnamed.append(part)
        if tpl == WV_CONTAINER_TEMPLATE:
            # {{listing|type=see|...}}：由 type= 参数决定类别；缺省时按所在章节标题
            # 推断（见 ==See==/==Eat== 等），两者都没有则跳过。
            tpl = str(named.get("type") or "").strip().lower()
            if tpl not in WV_TEMPLATE_CATEGORY:
                tpl = section or ""
            if tpl not in WV_TEMPLATE_CATEGORY:
                continue
        content = clean_wikitext(named.get("content") or (unnamed[0] if unnamed else ""))
        name = clean_wikitext(named.get("name"))
        lat, lng = to_float(named.get("lat")), to_float(named.get("long"))
        if not name:
            # 无坐标条目保留（后续用高德按中文名反查真实坐标），无名称才丢弃。
            continue
        listings.append({
            "template": tpl,
            "category": WV_TEMPLATE_CATEGORY[tpl],
            "name": name,
            "latitude": lat, "longitude": lng,
            "price_raw": clean_wikitext(named.get("price")) or None,
            "hours_raw": clean_wikitext(named.get("hours")) or None,
            "content": content,
        })

    # 同名去重（不同章节重复列出）
    seen: set[str] = set()
    unique: list[dict] = []
    for item in listings:
        key = (item["category"], norm_name(item["name"]).lower())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# LLM 批量处理（补齐 / 翻译）
# ---------------------------------------------------------------------------

def _llm_json_call(user_prompt: str, max_tokens: int = 3000) -> dict | None:
    """调用 LLM（json_mode）并解析为 JSON；失败返回 None。"""
    try:
        from app.common.llm_client import get_llm_client

        content = get_llm_client().chat(
            [
                {"role": "system", "content": "你是旅游知识库编辑，只输出 JSON，不要输出其他文字。"},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3, max_tokens=max_tokens, json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - LLM 失败可整体降级
        print(f"    [warn] LLM 调用失败: {exc}")
        return None
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def llm_translate_wv_listings(city: str, listings: list[dict], batch: int = 8) -> list[dict]:
    """Wikivoyage 英文条目 → 中文数据（名称/描述/tags/票价/时长）。"""
    out: list[dict] = []
    for start in range(0, len(listings), batch):
        chunk = listings[start:start + batch]
        lines = []
        for idx, item in enumerate(chunk):
            content = item["content"][:300]
            lines.append(
                f"{idx}|name: {item['name']}|type: {item['template']}|"
                f"price: {item['price_raw'] or 'unknown'}|hours: {item['hours_raw'] or 'unknown'}|"
                f"content: {content}"
            )
        prompt = (
            f"以下是中国{city}的 Wikivoyage 英文条目（维基导游，格式：序号|name:英文名|type:see/do/eat/drink/sleep|"
            f"price|hours|content）。把每条翻译整理为中文旅游数据：\n"
            f"1. name_cn：中文通用译名（保留常见叫法，如 Forbidden City→故宫）；\n"
            f"2. description：30~80字中文介绍，只写普遍成立的事实，禁止编造具体价格与营业时间；\n"
            f"3. tags：从 {'、'.join(TAG_SET)} 中选 1~3 个；\n"
            f"4. ticket_price_cny：门票/人均参考价（元，数字），不确定为 null；\n"
            f"5. duration_min：建议游玩分钟数（数字），不确定为 null。\n"
            f'严格输出 JSON：{{"items":[{{"i":0,"name_cn":"","description":"","tags":[],'
            f'"ticket_price_cny":null,"duration_min":null}}]}}\n\n'
            + "\n".join(lines)
        )
        data = _llm_json_call(prompt)
        items = (data or {}).get("items") or []
        by_index = {}
        for entry in items:
            if isinstance(entry, dict) and isinstance(entry.get("i"), int):
                by_index[entry["i"]] = entry
        for idx, item in enumerate(chunk):
            entry = by_index.get(idx)
            if not entry:
                continue
            name_cn = clean_text(entry.get("name_cn"), 126)
            desc = clean_text(entry.get("description"), 500)
            if not name_cn or not desc:
                continue
            tags = [t for t in (entry.get("tags") or []) if t in TAG_SET][:3]
            rec = new_record(city, name_cn, item["category"])
            wv_price = to_float(entry.get("ticket_price_cny"))
            rec.update({
                "latitude": round(item["latitude"], 6) if item["latitude"] is not None else None,
                "longitude": round(item["longitude"], 6) if item["longitude"] is not None else None,
                "description": desc,
                "tags": ",".join(tags) or None,
                "open_time": clean_text(item["hours_raw"], 62),
                "duration_min": int(entry["duration_min"]) if to_float(entry.get("duration_min")) else None,
                # Wikivoyage/LLM 给出的是门票/人均参考价，按下游契约统一落 ticket_price。
                "ticket_price": (round(wv_price, 2) if wv_price and item["category"] in ("attraction", "food") else None),
            })
            rec["_source_parts"] |= {"wikivoyage", "llm"}
            out.append(rec)
        time.sleep(0.3)
    return out


def build_wv_records(city: str, listings: list[dict]) -> list[dict]:
    """零 LLM 模式：直接以 Wikivoyage 原文（名称/描述/价格/时间）构建记录。

    描述字段 = listing 原文（已 clean_wikitext）；名称 = 原文名（可能为英文）；
    tags 用规则推导（中文模式，英文名多命中为空或仅"美食"）；source = wikivoyage
    （不带 +llm）。供 --with-llm 关闭时使用，保证知识库铺城市零模型成本。
    """
    out: list[dict] = []
    for item in listings:
        name = clean_text(item["name"], 126)
        desc = clean_text(item["content"], 500)
        if not name or not desc:
            continue
        rec = new_record(city, name, item["category"])
        price = to_float(item["price_raw"])
        rec.update({
            "latitude": round(item["latitude"], 6) if item["latitude"] is not None else None,
            "longitude": round(item["longitude"], 6) if item["longitude"] is not None else None,
            "description": desc,
            "tags": ",".join(rule_tags(name, item["template"] or item["category"], item["category"])) or None,
            "open_time": clean_text(item["hours_raw"], 62),
            "ticket_price": (round(price, 2) if price and item["category"] in ("attraction", "food") else None),
        })
        rec["_source_parts"] |= {"wikivoyage"}
        out.append(rec)
    return out


def llm_enrich_records(city: str, category: str, records: list[dict], batch: int) -> None:
    """为高德记录补齐缺项：description/tags/duration_min/open_time/价格（不覆盖已有值）。"""
    pending = [r for r in records if not r.get("description") or not r.get("tags")
               or r.get("duration_min") is None or not r.get("open_time")
               or (r.get("ticket_price") is None and category == "attraction")
               or (r.get("avg_cost") is None and category == "food")]
    if not pending:
        return
    type_map = {"attraction": "景点", "food": "餐厅/美食", "hotel": "酒店"}
    for start in range(0, len(pending), batch):
        chunk = pending[start:start + batch]
        lines = [
            f"{idx}|{r['name']}|{r.get('address') or '地址未知'}|{type_map[category]}|{r.get('rating') or '-'}"
            for idx, r in enumerate(chunk)
        ]
        prompt = (
            f"以下是中国{city}的{CATEGORY_CN[category]}列表（格式：序号|名称|地址|类型|评分）。为每条补充：\n"
            f"1. description：30~80字中文介绍，写普遍成立的事实（特色、历史背景、适合人群），禁止编造具体价格与营业时间；\n"
            f"2. tags：从 {'、'.join(TAG_SET)} 中选 1~3 个；\n"
            f"3. duration_min：建议游玩/用餐分钟数（数字），不确定为 null；\n"
            f"4. open_time：常见开放时间文本（如 08:30-17:00），不确定为 null；\n"
            f"5. ticket_price_cny：{('景点门票参考价' if category == 'attraction' else '人均消费参考价')}（元，数字），不确定为 null。\n"
            f'严格输出 JSON：{{"items":[{{"i":0,"description":"","tags":[],"duration_min":null,'
            f'"open_time":null,"ticket_price_cny":null}}]}}\n\n'
            + "\n".join(lines)
        )
        data = _llm_json_call(prompt)
        items = (data or {}).get("items") or []
        by_index = {}
        for entry in items:
            if isinstance(entry, dict) and isinstance(entry.get("i"), int):
                by_index[entry["i"]] = entry
        for idx, rec in enumerate(chunk):
            entry = by_index.get(idx)
            if not entry:
                continue
            filled = False
            if not rec.get("description") and clean_text(entry.get("description"), 500):
                rec["description"] = clean_text(entry["description"], 500)
                filled = True
            if not rec.get("tags"):
                tags = [t for t in (entry.get("tags") or []) if t in TAG_SET][:3]
                if tags:
                    rec["tags"] = ",".join(tags)
                    filled = True
            if rec.get("duration_min") is None and to_float(entry.get("duration_min")):
                rec["duration_min"] = int(to_float(entry["duration_min"]))
                filled = True
            if not rec.get("open_time") and clean_text(entry.get("open_time"), 62):
                rec["open_time"] = clean_text(entry["open_time"], 62)
                filled = True
            # 价格按品类落位：景点门票 → ticket_price；餐饮人均 → avg_cost。
            if category in ("attraction", "food") and to_float(entry.get("ticket_price_cny")):
                price = to_float(entry["ticket_price_cny"])
                if 0 < price < 10000:
                    target_field = "ticket_price" if category == "attraction" else "avg_cost"
                    if rec.get(target_field) is None:
                        rec[target_field] = round(price, 2)
                        filled = True
            if filled:
                rec["_source_parts"].add("llm")
        print(f"    LLM 补齐 {city}/{category} 批次 {start // batch + 1}/{(len(pending) + batch - 1) // batch}")
        time.sleep(0.3)


# ---------------------------------------------------------------------------
# 合并与清洗
# ---------------------------------------------------------------------------

def backfill_existing_pois(city: str, known_names: set[str], bbox: tuple) -> list[dict]:
    """对 DB 已有但本轮类型搜索未命中的行按名称定向补抓真值（修复种子假坐标）。

    背景：高德 text search+types 过滤会漏掉多 typecode 的主 POI（如故宫
    110201|140100），而关键词搜索能命中。这类行多为种子名单里的知名 POI。
    只接受返回结果中与查询名完全同名且落 bbox 的命中，宁缺毋滥。
    """
    conn = _pooled_connect()
    try:
        with conn.cursor() as cursor:
            # 只补仍为默认种子来源的行：真实来源行已含真值，重搜是浪费请求。
            cursor.execute(
                "SELECT name, category FROM poi_knowledge WHERE city = %s "
                "AND (source = 'mysql.poi_knowledge' OR source IS NULL OR source = '')",
                (city,),
            )
            rows = cursor.fetchall()
    finally:
        db_pool.release(conn)

    def pick(pois: list[dict]) -> tuple[dict, float, float] | None:
        """先取名称完全相等的命中，再退回包含式匹配（核心名+分店后缀都要在场）。"""
        for exact in (True, False):
            for raw in pois:
                raw_key = norm_name(str(raw.get("name") or ""))
                if exact:
                    if raw_key != key:
                        continue
                elif not (core in raw_key and (not branch or branch in raw_key)):
                    continue
                parts = str(raw.get("location") or "").split(",")
                if len(parts) != 2:
                    continue
                try:
                    lng, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                if in_bbox(bbox, lng, lat):
                    return raw, lng, lat
        return None

    out: list[dict] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        key = norm_name(name)
        if not key or key in known_names:
            continue
        # 包含式匹配依据：去掉括号分店后缀的核心名（"天涯海角"能命中高德的
        # "天涯海角游览区"）；带分店后缀时要求后缀同时出现在命中名里，
        # 防止"全聚德烤鸭店"错配到其他分店。
        m = re.match(r"^(.*?)\s*[（(](.*?)[)）]\s*$", key)
        core, branch = (m.group(1), m.group(2)) if m else (key, "")
        # 全名查不到时，再去掉括号后缀重试一次。
        queries = [name[:12]]
        if core and core != key:
            queries.append(core[:12])
        hit = None
        for q in queries:
            data = amap_get("v3/place/text", {
                "key": settings.amap_web_key, "keywords": q, "city": city,
                "citylimit": "true", "offset": 25, "page": 1, "output": "json",
            })
            hit = pick(data.get("pois") or [])
            if hit:
                break
            time.sleep(0.15)
        time.sleep(0.15)
        if hit is None:
            continue
        raw, lng, lat = hit
        biz = raw.get("biz_ext") or {}
        rating = to_float(biz.get("rating"))
        cost = to_float(biz.get("cost"))
        type_str = str(raw.get("type") or "")
        open_time = None
        for key2 in ("opentime2", "opentime_week", "opentime_today", "open_time"):
            if biz.get(key2):
                open_time = clean_text(biz.get(key2), 62)
                break
        rec = new_record(city, name, str(row.get("category") or "attraction"))
        rec.update({
            "address": clean_text(raw.get("address"), 254) or None,
            "latitude": round(lat, 6), "longitude": round(lng, 6),
            # 同 parse_amap_poi：高德 cost 是人均消费，不是门票价。
            "avg_cost": round(cost, 2) if cost is not None and cost >= 0 else None,
            "open_time": open_time,
            "rating": min(round(rating, 1), 5.0) if rating is not None else None,
            "tags": ",".join(rule_tags(name, type_str, rec["category"])) or None,
        })
        rec["_source_parts"].add("amap.poi")
        out.append(rec)
    return out


def geocode_records_via_amap(city: str, records: list[dict], bbox: tuple) -> list[dict]:
    """无坐标记录用高德文本搜索按中文名反查真实坐标；查不到即丢弃（不造假坐标）。"""
    kept: list[dict] = []
    for rec in records:
        if rec.get("latitude") is not None:
            kept.append(rec)
            continue
        data = amap_get("v3/place/text", {
            "key": settings.amap_web_key, "keywords": rec["name"][:12], "city": city,
            "citylimit": "true", "offset": 3, "page": 1, "output": "json",
        })
        hit = None
        for raw in data.get("pois") or []:
            parts = str(raw.get("location") or "").split(",")
            if len(parts) != 2:
                continue
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            if in_bbox(bbox, lng, lat):
                hit = (raw, lng, lat)
                break
        time.sleep(0.15)
        if hit is None:
            continue
        raw, lng, lat = hit
        rec["latitude"], rec["longitude"] = round(lat, 6), round(lng, 6)
        if not rec.get("address"):
            rec["address"] = clean_text(raw.get("address"), 254)
        rec["_source_parts"].add("amap.poi")  # 坐标/地址事实来自高德
        kept.append(rec)
    return kept


def _name_compatible(name_a: str, name_b: str) -> bool:
    """Wikivoyage 与高德记录名称是否可视为同一实体。

    仅凭"同类别 + <200m"合并会在城市核心区误并（隔壁另一家店）。追加名称
    门槛：归一化全等，或一方核心名以另一方开头（互为前缀），否则不合并。
    """
    a, b = norm_name(name_a), norm_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    # 去掉括号分店后缀再比较核心名，且要求较短者是较长者的前缀。
    ca, cb = brand_of(a), brand_of(b)
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return len(shorter) >= 2 and longer.startswith(shorter)


def merge_wv_into_amap(wv_records: list[dict], amap_by_cat: dict[str, list[dict]]) -> list[dict]:
    """坐标 <200m、同类别且名称可对齐的 Wikivoyage 记录并入高德记录；其余原样返回。"""
    standalone: list[dict] = []
    for wv in wv_records:
        target = None
        best = 1e18
        for rec in amap_by_cat.get(wv["category"], []):
            if rec.get("latitude") is None:
                continue
            if not _name_compatible(wv.get("name"), rec.get("name")):
                continue
            d = distance_m(wv["longitude"], wv["latitude"], rec["longitude"], rec["latitude"])
            if d < best:
                best, target = d, rec
        if target is not None and best < 200.0:
            if not target.get("description"):
                target["description"] = wv.get("description")
            if not target.get("open_time") and wv.get("open_time"):
                target["open_time"] = wv["open_time"]
            if target.get("ticket_price") is None and wv.get("ticket_price") is not None:
                target["ticket_price"] = wv["ticket_price"]
            if target.get("avg_cost") is None and wv.get("avg_cost") is not None:
                target["avg_cost"] = wv["avg_cost"]
            wv_tags = [t for t in str(wv.get("tags") or "").split(",") if t]
            tags = [t for t in str(target.get("tags") or "").split(",") if t]
            merged = [t for t in tags + wv_tags if t in TAG_SET]
            target["tags"] = ",".join(list(dict.fromkeys(merged))[:3]) if merged else target.get("tags")
            target["_source_parts"].add("wikivoyage")
        else:
            standalone.append(wv)
    return standalone


def finalize_records(records: list[dict], category: str, bbox: tuple) -> list[dict]:
    """清洗：坐标必需且落城市范围、名称去重（保留高分）、数值/长度收敛。"""
    out: list[dict] = []
    seen: set[str] = set()
    for rec in records:
        lng, lat = rec.get("longitude"), rec.get("latitude")
        if lng is None or lat is None or not in_bbox(bbox, lng, lat):
            continue
        key = norm_name(rec["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        if rec.get("rating") is not None:
            rec["rating"] = min(max(round(rec["rating"], 1), 0.0), 5.0)
        if rec.get("ticket_price") is not None:
            rec["ticket_price"] = round(max(rec["ticket_price"], 0.0), 2)
        if rec.get("avg_cost") is not None:
            rec["avg_cost"] = round(max(rec["avg_cost"], 0.0), 2)
        if rec.get("duration_min") is not None:
            rec["duration_min"] = int(max(min(rec["duration_min"], 1440), 0))
        rec["name"] = clean_text(rec["name"], 126) or rec["name"]
        rec["address"] = clean_text(rec.get("address"), 254)
        rec["open_time"] = clean_text(rec.get("open_time"), 62)
        rec["description"] = clean_text(rec.get("description"), 500)
        rec["source"] = compose_source(rec["_source_parts"])
        if not rec.get("tags") and category in ("attraction", "food"):
            rec["tags"] = ",".join(rule_tags(rec["name"], "", category)) or None
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 数据库 upsert 与索引同步
# ---------------------------------------------------------------------------

def _source_union(old_source: str | None, new_source: str | None) -> str:
    """source 取并集而非无条件覆盖：旧行更完整的来源标记（如 amap.poi+wikivoyage）
    不应被仅含 amap.poi 的新值降级。"""
    parts = {p.strip() for p in str(old_source or "").split("+") if p.strip()}
    parts |= {p.strip() for p in str(new_source or "").split("+") if p.strip()}
    parts.discard("mysql.poi_knowledge")  # 默认种子来源不算事实来源
    return compose_source(parts) if parts else (new_source or "amap.poi")


def _row_completeness(row: dict) -> int:
    fields = ("address", "latitude", "longitude", "ticket_price", "avg_cost",
              "open_time", "description", "rating", "tags")
    return sum(row.get(f) is not None for f in fields)


def upsert_pois(records: list[dict]) -> tuple[int, int, int]:
    """按 (city, 归一化名称) 增量 upsert：字段"新值非空才覆盖"，坐标一律以真值为准。

    幂等性：读取时把同名重复行按信息完整度选出保留行、其余删除，使历史脏数据
    向 (city, name) 唯一键收敛；source 取并集，避免更权威来源被降级覆盖。
    """
    conn = _pooled_connect()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = updated = unchanged = 0
    try:
        with conn.cursor() as cursor:
            # fail-fast：库若被 schema.sql 重建（avg_cost 列与唯一键消失），必须
            # 在写库入口立刻报清楚，而不是采集 50 分钟后才抛 1054 让全部工作作废。
            cursor.execute("SHOW COLUMNS FROM poi_knowledge LIKE 'avg_cost'")
            if cursor.fetchone() is None:
                raise RuntimeError(
                    "poi_knowledge 缺少 avg_cost 列（库可能被 sql/schema.sql 重建过）："
                    "请先执行 sql/add_poi_avg_cost_and_unique.sql 再跑管线")
            cursor.execute(
                "SELECT id, city, name, category, address, latitude, longitude, ticket_price, "
                "avg_cost, duration_min, open_time, tags, rating, description, source FROM poi_knowledge"
            )
            # 同名可能有多行（历史无唯一键遗留）：按 (city, 归一化名称, category)
            # 归组，选信息最完整的一行为保留行、其余删除，避免旧 dict 折叠后
            # 重复行永远不被更新。category 必须在键内——"和平饭店"这类酒店内
            # 餐厅是同名不同品类的合法双记录，不能互相覆盖。
            grouped: dict[tuple, list[dict]] = {}
            for r in cursor.fetchall():
                grouped.setdefault(
                    (r["city"], norm_name(r["name"]), str(r.get("category") or "")), []).append(r)
            existing: dict[tuple, dict] = {}
            for key, rows in grouped.items():
                keep = max(rows, key=lambda row: (_row_completeness(row), row["id"]))
                existing[key] = keep
                for dup in rows:
                    if dup["id"] != keep["id"]:
                        cursor.execute("DELETE FROM poi_knowledge WHERE id = %s", (dup["id"],))

            for rec in records:
                key = (rec["city"], norm_name(rec["name"]), str(rec.get("category") or ""))
                old = existing.get(key)
                new_vals = (
                    rec["category"], rec.get("address"), rec.get("latitude"), rec.get("longitude"),
                    rec.get("ticket_price"), rec.get("avg_cost"), rec.get("duration_min"),
                    rec.get("open_time"), rec.get("tags"), rec.get("rating"), rec.get("description"),
                    rec.get("source") or "amap.poi", now,
                )
                if old is None:
                    cursor.execute(
                        "INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude, "
                        "ticket_price, avg_cost, duration_min, open_time, tags, rating, description, source, "
                        "source_updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (rec["city"], rec["name"], *new_vals),
                    )
                    inserted += 1
                    # 登记进 existing：批内后续同键记录走 UPDATE 而非再 INSERT，
                    # 否则两条同 (city,name,category) 记录会撞唯一键 1062。
                    existing[key] = {
                        "id": cursor.lastrowid, "city": rec["city"], "name": rec["name"],
                        "category": new_vals[0], "address": new_vals[1], "latitude": new_vals[2],
                        "longitude": new_vals[3], "ticket_price": new_vals[4], "avg_cost": new_vals[5],
                        "duration_min": new_vals[6], "open_time": new_vals[7], "tags": new_vals[8],
                        "rating": new_vals[9], "description": new_vals[10], "source": new_vals[11],
                    }
                    continue

                merged = {
                    "category": new_vals[0],
                    "address": new_vals[1] if new_vals[1] else old["address"],
                    # 坐标：真实采集值永远覆盖种子假坐标
                    "latitude": new_vals[2] if new_vals[2] is not None else old["latitude"],
                    "longitude": new_vals[3] if new_vals[3] is not None else old["longitude"],
                    "ticket_price": new_vals[4] if new_vals[4] is not None else old["ticket_price"],
                    "avg_cost": new_vals[5] if new_vals[5] is not None else old["avg_cost"],
                    "duration_min": new_vals[6] if new_vals[6] is not None else old["duration_min"],
                    "open_time": new_vals[7] if new_vals[7] else old["open_time"],
                    "tags": new_vals[8] if new_vals[8] else old["tags"],
                    "rating": new_vals[9] if new_vals[9] is not None else old["rating"],
                    "description": new_vals[10] if new_vals[10] else old["description"],
                    "source": _source_union(old["source"], new_vals[11]),
                    "source_updated_at": new_vals[12],
                }
                changed = (
                    str(old["category"]) != str(merged["category"])
                    or (old["address"] or None) != merged["address"]
                    or round(float(old["latitude"] or 0), 6) != (merged["latitude"] or 0)
                    or round(float(old["longitude"] or 0), 6) != (merged["longitude"] or 0)
                    or (float(old["ticket_price"]) if old["ticket_price"] is not None else None) != merged["ticket_price"]
                    or (float(old["avg_cost"]) if old.get("avg_cost") is not None else None) != merged["avg_cost"]
                    or (int(old["duration_min"]) if old["duration_min"] is not None else None) != merged["duration_min"]
                    or (old["open_time"] or None) != merged["open_time"]
                    or (old["tags"] or None) != merged["tags"]
                    or (float(old["rating"]) if old["rating"] is not None else None) != merged["rating"]
                    or (old["description"] or None) != merged["description"]
                    or (old["source"] or None) != merged["source"]
                )
                if not changed:
                    unchanged += 1
                    continue
                cursor.execute(
                    "UPDATE poi_knowledge SET category=%s, address=%s, latitude=%s, longitude=%s, "
                    "ticket_price=%s, avg_cost=%s, duration_min=%s, open_time=%s, tags=%s, rating=%s, "
                    "description=%s, source=%s, source_updated_at=%s WHERE id=%s",
                    (*[merged[k] for k in ("category", "address", "latitude", "longitude", "ticket_price",
                                           "avg_cost", "duration_min", "open_time", "tags", "rating",
                                           "description", "source", "source_updated_at")], old["id"]),
                )
                updated += 1
        conn.commit()
    finally:
        db_pool.release(conn)
    return inserted, updated, unchanged


def prune_seed_rows(cities: list[str]) -> int:
    """删除指定城市中 source 仍为默认种子来源的行（未被本管线匹配的旧种子数据）。"""
    placeholders = ",".join(["%s"] * len(cities))
    conn = _pooled_connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM poi_knowledge WHERE city IN ({placeholders}) AND source = 'mysql.poi_knowledge'",
                cities,
            )
            deleted = cursor.rowcount
        conn.commit()
    finally:
        db_pool.release(conn)
    return deleted


def prune_fake_seed_rows(cities: list[str]) -> int:
    """删除种子来源且描述命中种子模板的行（可证伪的假坐标行）。

    与 --prune-seed 的区别：种子酒店行与手工 SQL 增补行（如杭州分档酒店）
    的坐标是人工校对过的（描述为手写文案），必须保留；只有描述命中
    "{城市}热门…打卡地，适合…出行体验" 模板、且定向补抓也搜不到的行，
    才可断定坐标是城市中心随机撒点的假值。
    """
    placeholders = ",".join(["%s"] * len(cities))
    conn = _pooled_connect()
    try:
        with conn.cursor() as cursor:
            # LIKE 模式必须走参数传递，避免 pymysql 把 % 当作格式化占位符。
            cursor.execute(
                f"DELETE FROM poi_knowledge WHERE city IN ({placeholders}) "
                "AND (source = 'mysql.poi_knowledge' OR source IS NULL OR source = '') "
                "AND description LIKE %s",
                [*cities, "%热门%打卡地，适合%出行体验%"],
            )
            deleted = cursor.rowcount
        conn.commit()
    finally:
        db_pool.release(conn)
    return deleted


def sync_chroma_index() -> None:
    """本进程内强制同步 MySQL → Chroma（指纹增量 upsert）。"""
    try:
        from app.rag.store import poi_store

        print("正在同步 RAG 索引（MySQL → Chroma）……")
        poi_store.ensure_loaded(force=True)
        info = poi_store.index_info
        print(
            f"RAG 索引同步完成：总数={info.get('poi_count')}，更新={info.get('changed_count')}，"
            f"删除={info.get('deleted_count')}，全量重建={info.get('full_rebuild')}"
        )
    except Exception as exc:  # noqa: BLE001 - 同步失败不影响落库结果
        print(f"[warn] Chroma 索引同步失败：{exc}（可重启 Python 服务触发 warmup_rag 完成同步）")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="P0 数据管线：高德 + Wikivoyage + LLM → poi_knowledge")
    parser.add_argument("--cities", nargs="+", default=list(CITY_CONFIG), help="目标城市（默认全部 6 城）")
    parser.add_argument("--categories", nargs="+", default=list(CATEGORIES), choices=CATEGORIES)
    parser.add_argument("--attractions", type=int, default=120, help="每城景点目标数量")
    parser.add_argument("--foods", type=int, default=60, help="每城美食目标数量")
    parser.add_argument("--hotels", type=int, default=40, help="每城酒店目标数量")
    parser.add_argument("--pages", type=int, default=10, help="高德每类别最大翻页数（25 条/页）")
    parser.add_argument("--wv-limit", type=int, default=80, help="每城最多入知识库的 Wikivoyage 条目数")
    parser.add_argument("--llm-batch", type=int, default=20, help="LLM 补齐批大小（仅 --with-llm）")
    parser.add_argument("--no-wikivoyage", action="store_true", help="跳过 Wikivoyage 采集")
    parser.add_argument("--with-llm", action="store_true",
                        help="启用 LLM 翻译/补齐（默认关闭：Wikivoyage 原文直接入库，零模型成本）")
    parser.add_argument("--no-llm", action="store_true",
                        help="（已弃用）默认即零 LLM 行为，保留兼容")
    parser.add_argument("--dry-run", action="store_true", help="只采集与汇总，不写库不同步索引")
    parser.add_argument("--no-sync", action="store_true", help="落库后不触发 Chroma 同步")
    parser.add_argument("--backfill-only", action="store_true",
                        help="跳过采集/LLM，仅对 DB 已有行做名称定向补抓（低成本修复种子假坐标）")
    parser.add_argument("--prune-seed", action="store_true",
                        help="落库后删除本次城市中 source 仍为默认种子来源的旧行（谨慎）")
    parser.add_argument("--prune-fake-template", action="store_true",
                        help="落库后仅删除描述命中种子模板的种子行（可证伪假坐标，保留手工/酒店真实行）")
    args = parser.parse_args()

    targets = {"attraction": args.attractions, "food": args.foods, "hotel": args.hotels}
    cities = [c for c in args.cities if c in CITY_CONFIG]
    unknown = [c for c in args.cities if c not in CITY_CONFIG]
    if unknown:
        print(f"[warn] 忽略不支持的城市：{unknown}（支持：{list(CITY_CONFIG)}）")
    if not cities:
        print("[error] 没有可处理的城市")
        sys.exit(1)

    domestic = [c for c in cities if "adcode" in CITY_CONFIG[c]]
    foreign = [c for c in cities if "adcode" not in CITY_CONFIG[c]]
    if domestic and not settings.amap_web_key:
        print("[error] 未配置 AMAP_WEB_KEY，无法采集国内城市高德数据；请检查 .env")
        sys.exit(1)
    if foreign and not settings.amap_web_key:
        print("[info] 国外城市走 Nominatim 免 key + Wikivoyage 原文，无需 AMAP_WEB_KEY")
    llm_ok = bool(settings.llm_api_key) and args.with_llm and not args.no_llm
    if args.with_llm and not settings.llm_api_key:
        print("[warn] 已指定 --with-llm 但未配置 LLM_API_KEY，自动退回零 LLM 模式（Wikivoyage 原文入库）")

    def collect_wv_records(city: str, cfg: dict, bbox: tuple, args, llm_ok: bool) -> list[dict]:
        """采集并解析 Wikivoyage listing（LLM 翻译或零 LLM 原文），国内/国外共用。"""
        # 大城市 listing 拆分在地区子页（如 Beijing/Dongcheng），主页面+子页一起抓。
        wv_pages = [cfg["wv_title"], *fetch_wikivoyage_subpages(cfg["wv_title"])]
        print(f"  [Wikivoyage] 抓取 {len(wv_pages)} 个页面…")
        listings: list[dict] = []
        seen_wv: set[tuple] = set()
        for page_title in wv_pages:
            for item in fetch_wikivoyage_listings(page_title):
                key = (item["category"], norm_name(item["name"]).lower())
                if key not in seen_wv:
                    seen_wv.add(key)
                    listings.append(item)
            time.sleep(2.5)  # Wikimedia 对连续抓页限流，页间留间隔
        by_cat: dict[str, list[dict]] = {}
        for item in listings:
            if item["category"] not in args.categories:
                continue
            # 无坐标条目保留（后续反查）；有坐标的必须落城市范围。
            if item["latitude"] is None or in_bbox(bbox, item["longitude"], item["latitude"]):
                by_cat.setdefault(item["category"], []).append(item)
        for cat in list(by_cat):
            by_cat[cat].sort(key=lambda x: len(x["content"]), reverse=True)
            by_cat[cat] = by_cat[cat][:args.wv_limit]
        total = sum(len(v) for v in by_cat.values())
        flat_wv = [x for cat in args.categories for x in by_cat.get(cat, [])]
        if llm_ok:
            print(f"  [Wikivoyage] 有效 listing {total} 条，开始 LLM 翻译…")
            return llm_translate_wv_listings(city, flat_wv)
        print(f"  [Wikivoyage] 有效 listing {total} 条，零 LLM 模式：原文直接构建记录…")
        return build_wv_records(city, flat_wv)

    def run_foreign_pipeline(city: str) -> list[dict]:
        """国外城市管线：Nominatim 免 key 采集 → Wikivoyage 原文合并 → 清洗（零 LLM）。"""
        cfg = CITY_CONFIG[city]
        print(f"\n=== {city}（国外，Nominatim + Wikivoyage 原文） ===")
        bbox = cfg["bbox"]
        print(f"  城市范围 bbox={tuple(round(v, 3) for v in bbox)}")

        pois_by_cat: dict[str, list[dict]] = {}
        for category in args.categories:
            records = fetch_nominatim_pois(city, category, targets[category], bbox)
            pois_by_cat[category] = records
            print(f"  [{CATEGORY_CN[category]}] Nominatim 采集并清洗后 {len(records)} 条")

        if not args.no_wikivoyage:
            wv_records = collect_wv_records(city, cfg, bbox, args, llm_ok=False)
            # 国外不走高德反查（高德仅中国）；无坐标的 Wikivoyage 条目在 finalize 丢弃。
            standalone = merge_wv_into_amap(wv_records, pois_by_cat)
            for rec in standalone:
                if rec["category"] in pois_by_cat:
                    pois_by_cat[rec["category"]].append(rec)
            print(f"  [Wikivoyage] 并入 Nominatim {len(wv_records) - len(standalone)} 条，"
                  f"新增独立 {len(standalone)} 条")

        city_records: list[dict] = []
        for category in args.categories:
            final = finalize_records(pois_by_cat[category], category, bbox)
            city_records.extend(final)
            print(f"  [{CATEGORY_CN[category]}] 最终有效 {len(final)} 条")
        return city_records

    def run_city_pipeline(city: str) -> list[dict]:
        """单城市完整管线：高德采集 → Wikivoyage 合并 → 定向补抓 → LLM 补齐 → 清洗。"""
        cfg = CITY_CONFIG[city]
        print(f"\n=== {city} ===")
        bbox = fetch_city_bbox(city, cfg["bbox"], cfg.get("adcode"))
        print(f"  城市范围 bbox={tuple(round(v, 3) for v in bbox)}")

        amap_by_cat: dict[str, list[dict]] = {}
        for category in args.categories:
            records = fetch_amap_pois(city, category, targets[category], args.pages, bbox)
            amap_by_cat[category] = records
            print(f"  [{CATEGORY_CN[category]}] 高德采集并清洗后 {len(records)} 条")

        if not args.no_wikivoyage:
            wv_records = collect_wv_records(city, cfg, bbox, args, llm_ok)
            unmatched_coord = sum(1 for r in wv_records if r.get("latitude") is None)
            wv_records = geocode_records_via_amap(city, wv_records, bbox)
            if unmatched_coord:
                print(f"  [Wikivoyage] 高德反查坐标：成功 {len(wv_records)} / 待查 {unmatched_coord}，其余丢弃")
            standalone = merge_wv_into_amap(wv_records, amap_by_cat)
            for rec in standalone:
                if rec["category"] in amap_by_cat:
                    amap_by_cat[rec["category"]].append(rec)
            merged = len(wv_records) - len(standalone)
            print(f"  [Wikivoyage] 并入高德 {merged} 条，新增独立 {len(standalone)} 条")

        # 定向补抓：DB 已有但类型搜索漏掉的行（如多 typecode 主 POI 故宫），
        # 按名称逐个搜索高德回填真值，覆盖种子假坐标。
        known = {norm_name(r["name"]) for cat in args.categories for r in amap_by_cat.get(cat, [])}
        backfilled = backfill_existing_pois(city, known, bbox)
        for rec in backfilled:
            if rec["category"] in amap_by_cat:
                amap_by_cat[rec["category"]].append(rec)
        if backfilled:
            print(f"  [定向补抓] DB 已有名点回填真值 {len(backfilled)} 条")

        if llm_ok:
            for category in args.categories:
                llm_enrich_records(city, category, amap_by_cat[category], args.llm_batch)

        city_records: list[dict] = []
        for category in args.categories:
            final = finalize_records(amap_by_cat[category], category, bbox)
            city_records.extend(final)
            print(f"  [{CATEGORY_CN[category]}] 最终有效 {len(final)} 条")
        return city_records

    all_records: list[dict] = []
    if args.backfill_only:
        # 定向补抓模式：不采集不调 LLM，只按 DB 已有行名逐个搜索高德回填。
        for city in cities:
            print(f"\n=== {city}（定向补抓） ===")
            cfg = CITY_CONFIG[city]
            bbox = fetch_city_bbox(city, cfg["bbox"], cfg.get("adcode"))
            got = backfill_existing_pois(city, set(), bbox)
            print(f"  命中并回填 {len(got)} 条")
            grouped: dict[str, list[dict]] = {}
            for rec in got:
                grouped.setdefault(rec["category"], []).append(rec)
            for cat, recs in grouped.items():
                all_records.extend(finalize_records(recs, cat, bbox))
    else:
        for city in cities:
            # 国外城市（无 adcode）自动走 Nominatim 免 key + Wikivoyage 原文管线。
            pipeline = run_foreign_pipeline if "adcode" not in CITY_CONFIG[city] else run_city_pipeline
            all_records.extend(pipeline(city))

    # ---- 汇总 ----
    print(f"\n=== 汇总：共 {len(all_records)} 条 ===")
    source_counter: dict[str, int] = {}
    for rec in all_records:
        source_counter[rec["source"]] = source_counter.get(rec["source"], 0) + 1
    for source, count in sorted(source_counter.items(), key=lambda x: -x[1]):
        print(f"  source={source}: {count}")
    described = sum(1 for r in all_records if r.get("description"))
    print(f"  含中文描述：{described}/{len(all_records)}")

    if args.dry_run:
        print("\n[dry-run] 不写库。示例记录：")
        for rec in all_records[:5]:
            print(f"  - {rec['city']} {rec['name']} ({rec['category']}) {rec['latitude']},{rec['longitude']} "
                  f"评分={rec.get('rating')} 价={rec.get('ticket_price')} source={rec['source']}")
        return

    inserted, updated, unchanged = upsert_pois(all_records)
    print(f"\n落库完成：新增 {inserted}，更新 {updated}，无变化跳过 {unchanged}")

    if args.prune_seed:
        deleted = prune_seed_rows(cities)
        print(f"种子清理：删除 source='mysql.poi_knowledge' 的旧行 {deleted} 条")

    if args.prune_fake_template:
        deleted = prune_fake_seed_rows(cities)
        print(f"假种子清理：删除描述命中种子模板的行 {deleted} 条")

    if not args.no_sync:
        sync_chroma_index()
    print("\n完成。若 FastAPI 服务正在运行，请重启以刷新其内存 RAG 索引。")


if __name__ == "__main__":
    main()
