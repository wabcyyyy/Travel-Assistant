"""酒店观测价合并（L15）：Hotellook 缓存价与 OTM/联网池按名归一匹配。

把「LLM 估价 × 季节系数」升级为「观测价优先、估价兜底」的那一半：取价、按名
归一匹配、把观测价挂到池行上。价格**怎么用**（base_price / price_fact / reason）
由消费方决定（`editing/chat_draft/hotel.py::_hotel_options`）。

**为什么匹配与取价落在这里而不是 `search_hotels` 内部**（SPEC L15 第 1 项的
字面位置是后者）：Hotellook `cache.json` 的 `priceAvg` 是**按 (checkIn, checkOut)
窗口**的均价，而 `search_hotels(city, limit)` 的签名里没有日期——真实日期只有
换酒店那一刻的意图知道（停靠日 + 请求晚数）。在拿不到窗口的地方取价、再把价格
套到另一个窗口上，就是"价格对不上日期"的事实错误，与"真价挂错酒店"同级。
所以取价点跟着窗口走；匹配/合并的实现只此一份，谁需要谁调。

匹配纪律（SPEC 禁做：不为匹配率牺牲正确性）：
- 归一后**相等**即同一家；
- 否则按**词集合**判包含（拉丁名）或字符包含（中日韩名），且较短名 ≥
  `_MIN_MATCH_CHARS`；
- 匹配不上**不硬凑**：池里原估价行原样保留，Hotellook 行作为新候选追加。

**为什么这里不复用 `grounding.existence.same_entity`**：它服务的是长中文地名，
模糊分支用**字符集合**重叠率（Jaccard）——对多词拉丁酒店名是错的，因为它丢掉
词序与词重复。实测反例：`"Sample Hotel Diagonal"` 与 `"Hostel Sample Gothic"`
的字符集合几乎相同（字母都是 sample/hotel/diagonal/gothic 那批），重叠率
0.857 远超 0.55 阈值 → 被判同一家 → **真价挂错酒店**。酒店名必须按词判。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.core.poi_identity import norm_poi_key, strip_name_annotation
from app.agent.data import hotel_prices

logger = logging.getLogger(__name__)

#: 拉丁词切分（酒店名以英文/本地拉丁拼写为主）。
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: 模糊匹配（非相等）时较短归一名的长度下限。6 是保守取值：挡掉 "hotel"/"inn"/
#: "酒店" 这类通用词单独成名的误配，又不至于把 "Aman Tokyo"（9）这类真名挡在外面。
_MIN_MATCH_CHARS = 6
#: 观测价时效上限（与航班报价同口径：缓存价不是实时价）。
OBSERVED_TTL_SECONDS = 24 * 3600
_TZ_CST = timezone(timedelta(hours=8))


def _now_cst() -> datetime:
    return datetime.now(_TZ_CST)


def _latin_tokens(name: object) -> frozenset[str]:
    return frozenset(_LATIN_TOKEN_RE.findall(strip_name_annotation(name).casefold()))


def same_hotel(left: object, right: object) -> bool:
    """两个酒店名是不是同一家（保守口径，见模块 docstring）。"""
    a, b = norm_poi_key(left), norm_poi_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < _MIN_MATCH_CHARS:
        return False
    ta, tb = _latin_tokens(left), _latin_tokens(right)
    if ta and tb:
        # 拉丁名按词集合判包含：词序是噪声（"Sakura Hotel" = "Hotel Sakura"），
        # 但字符集合不是——"Sample Hotel Diagonal" vs "Hostel Sample Gothic"
        # 的字符集合几乎相同，按字符判就会挂错价。
        return ta <= tb or tb <= ta
    # 无拉丁词（中日韩名）：单块文本，字符包含才是有效信号
    return a in b or b in a


def _observed_row(row: dict[str, Any], *, check_in: str, check_out: str, now: datetime) -> dict[str, Any] | None:
    """Hotellook 行 → 池行（带观测价注解）；缺名/缺价返回 None。"""
    name = str(row.get("hotelName") or "").strip()
    price = _as_price(row.get("priceAvg"))
    if not name or price is None:
        return None
    return {
        "id": f"hotellook-{row.get('hotelId')}",
        "name": name,
        "category": "hotel",
        "address": None,
        "rating": _as_float(row.get("stars")),
        "ticket_price": None,
        "description": _stars_description(_as_float(row.get("stars"))),
        "tags": "住宿",
        "source": "hotellook",
        "observed_nightly_price": price,
        "observed_currency": str(row.get("currency") or "cny"),
        "observed_check_in": check_in,
        "observed_check_out": check_out,
        "observed_at": now.isoformat(timespec="seconds"),
        "observed_expires_at": (now + timedelta(seconds=OBSERVED_TTL_SECONDS)).isoformat(timespec="seconds"),
        "observed_deep_link": str(row.get("deep_link") or "") or None,
        "observed_hotel_id": str(row.get("hotelId") or "") or None,
    }


def observed_price(hotel: dict[str, Any], *, check_in: str | None, check_out: str | None) -> dict[str, Any] | None:
    """池行上的观测价注解；窗口缺失或对不上返回 None（价格属于那个窗口，不能挪用）。

    这是消费方的**唯一判据**：`_hotel_options` 拿它决定用观测价还是估价，绝不
    直接读 `observed_nightly_price` 字段——否则窗口校验会被绕过。
    """
    if not check_in or not check_out:
        return None
    price = _as_price(hotel.get("observed_nightly_price"))
    if price is None:
        return None
    if str(hotel.get("observed_check_in") or "") != check_in:
        return None
    if str(hotel.get("observed_check_out") or "") != check_out:
        return None
    return {
        "nightly_price": price,
        "currency": str(hotel.get("observed_currency") or "cny"),
        "provider": "hotellook",
        "retrieved_at": str(hotel.get("observed_at") or "") or None,
        "expires_at": str(hotel.get("observed_expires_at") or "") or None,
        "deep_link": str(hotel.get("observed_deep_link") or "") or None,
        "check_in": check_in,
        "check_out": check_out,
    }


def merge_observed_prices(
    hotels: list[dict[str, Any]], city: str, *, check_in: str | None, check_out: str | None
) -> list[dict[str, Any]]:
    """把 Hotellook 观测价并入候选池（跨模块 API，返回新列表）。

    命中已有行 → 在原行上挂观测价注解（保留它的坐标/地址/简介，只补价格）；
    未命中 → 作为新候选追加（真酒店 + 真价，只是没有坐标）。
    无窗口/无 token/上游没答 → **原池原样返回**（估价链路零变化）。
    """
    if not check_in or not check_out:
        return hotels
    if not hotel_prices.hotel_prices_enabled():
        return hotels
    rows = hotel_prices.fetch_hotel_prices(city, check_in, check_out, limit=max(len(hotels) + 10, 12))
    if not rows:
        return hotels
    now = _now_cst()
    observed = [row for raw in rows if (row := _observed_row(raw, check_in=check_in, check_out=check_out, now=now))]
    if not observed:
        return hotels

    merged = [dict(hotel) for hotel in hotels]
    matched: set[int] = set()
    for i, row in enumerate(observed):
        hit = next((j for j, hotel in enumerate(merged) if same_hotel(hotel.get("name"), row["name"])), None)
        if hit is None:
            continue
        matched.add(i)
        for key, value in row.items():
            # 名字与身份/来源一律保留原行：观测行的名字只是**匹配键**，用它改写
            # 卡片名等于让 provider 的写法静默覆盖我们自己的展示名。
            if key in ("id", "name", "category", "tags", "source"):
                continue
            if value is not None:
                merged[hit][key] = value
    # 未匹配的 Hotellook 行作为新候选追加（宁缺毋滥只针对**合并**，不针对新增）。
    # 追加后再判一次同名：同名观测行只进一条（第二条会被 merged 里刚追加的挡住）。
    for i, row in enumerate(observed):
        if i in matched or any(same_hotel(hotel.get("name"), row["name"]) for hotel in merged):
            continue
        merged.append(row)
    return merged


def _stars_description(stars: float | None) -> str | None:
    """星级 → 卡片描述：只直述官方星级，不编造卖点。

    5 星写成"五星级"是有意的：既有的档次关键词表（`hotel_intent._TIER_KEYWORDS`）
    认"五星"，写成星级数字的话 5 星酒店会被默认成"舒适型"，在"豪华型"请求里
    根本不出现。档次逻辑本卡不动，只喂真数据（stars 是官方星级，真实事实）。
    """
    if stars is None or stars <= 0:
        return None
    if stars >= 5:
        return "五星级酒店"
    return f"{int(stars)} 星级酒店"


def _as_price(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
