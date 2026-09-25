"""酒店聚合价数据层：Hotellook `cache.json`（engine.hotellook.com）。

L12 地基卡：只取数、不下结论、不进 agent 链路（接线在 L15）。这是搜索缓存价
而非实时报价；本层按行返回价格事实，名称匹配/预算判定/证据组装都在消费方。

文档核对结论（2026-09-25，入 commit message）：
- `GET https://engine.hotellook.com/api/v2/cache.json`，query 参数
  location（城市 IATA 或名）、checkIn / checkOut（YYYY-MM-DD）、currency、
  limit、token；token 走 query 是官方示例口径（该域未文档化头通道）——
  密钥不进缓存键，异常消息里的 URL 由 `external_client._redact_secrets`
  在日志出口统一脱敏；
- 官方文档页 2026-09-25 不可达（403/网关错误）；响应字段名经两个独立第三方
  绑定交叉确认（Go: hotelId/hotelName/priceAvg/stars；另 priceFrom/priceOld/
  distance/distanceUnit）。解析容错 + fixtures 锁形状，L4 cassette 实录后校正。

None 与 [] 是两种结论（places.geocode_place_rows 同款语义）：
- `None`：未配 token / 请求失败 / 应答形状不对——"没问到"；
- `[]`：问到了且该城市该日期无价格行。
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.config import settings
from app.common.external_client import BACKGROUND, ExternalClient, fetch_json
from app.common.http_client import api_client

logger = logging.getLogger(__name__)

_HOTELLOOK_CACHE = "https://engine.hotellook.com/api/v2/cache.json"
_USER_AGENT = "TravelAssistantDemo/1.0 (student-project; contact=dev@localhost.invalid)"

_hotel_client: ExternalClient = ExternalClient(
    name="hotellook_cache",
    ttl_seconds=6 * 3600,
    negative_ttl_seconds=600,
    min_interval_seconds=1.0,
    retry_attempts=1,
)

#: 行内必须可用的最小键集：没有名字的行无法在 L15 与 OTM/联网池按名归一匹配，
#: 没有均价的行没有价格事实——都直接丢弃。
_ROW_MIN_KEYS = ("hotelId", "hotelName", "priceAvg")


def hotel_prices_enabled() -> bool:
    return bool(str(settings.travelpayouts_token or "").strip())


def fetch_hotel_prices(
    location: str,
    check_in: str,
    check_out: str,
    *,
    currency: str = "cny",
    limit: int = 10,
) -> list[dict[str, Any]] | None:
    """城市 + 入/离日期 → per-hotel 价格行列表 | None。

    行 dict 透传上游全部字段（未知字段原样保留）；缺 hotelId/hotelName/priceAvg
    任一项的行丢弃。
    """
    token = str(settings.travelpayouts_token or "").strip()
    place = str(location or "").strip()
    check_in = str(check_in or "").strip()
    check_out = str(check_out or "").strip()
    if not token or not place or not check_in or not check_out:
        return None
    # 密钥绝不进缓存键；token 在 query 里，异常脱敏由 external_client 统一兜
    cache_key = f"{place}:{check_in}:{check_out}:{currency}:{int(limit)}"
    payload = _hotel_client.call(
        cache_key,
        lambda: fetch_json(
            _hotel_client,
            api_client(),
            _HOTELLOOK_CACHE,
            params={
                "location": place,
                "checkIn": check_in,
                "checkOut": check_out,
                "currency": currency,
                "limit": int(limit),
                "token": token,
            },
            headers={"User-Agent": _USER_AGENT},
        ),
        lane=BACKGROUND,
    )
    if not isinstance(payload, list):
        logger.warning("hotellook[%s %s~%s] envelope not a list", place, check_in, check_out)
        return None
    rows: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict) or _row_missing(raw):
            continue
        rows.append(dict(raw))
    return rows


def _row_missing(raw: dict[str, Any]) -> bool:
    return any(raw.get(key) is None for key in _ROW_MIN_KEYS)
