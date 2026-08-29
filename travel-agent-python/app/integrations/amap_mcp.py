"""高德官方 MCP Server 客户端与 POI 领域适配。

高德官方 MCP 使用 Streamable HTTP。这里保留一层很薄的客户端适配器，
让 Agent 不依赖高德 MCP 的原始 JSON，也方便统一做工具发现、超时和降级。

安全边界：API Key 只从服务端环境变量读取，不暴露给前端；本模块只暴露查询
能力，不提供保存、修改或删除行程的工具。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.common.config import settings
from app.agent.trace import record_event

logger = logging.getLogger(__name__)


_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    # 官方工具名可能随版本增加前缀或调整命名；优先精确名称，再按描述匹配。
    "search_poi": (
        "maps_text_search",
        "maps_around_search",
        "maps_search_poi",
        "search_poi",
        "poi_search",
    ),
    "poi_detail": ("maps_search_detail", "maps_poi_detail", "poi_detail"),
    "geocode": ("maps_geo", "maps_geocode", "geocode"),
}


def build_endpoint() -> str:
    """构造 MCP endpoint；不记录返回值，避免日志意外泄露 key。"""
    url = settings.amap_mcp_url.strip()
    if not url:
        return ""
    key = settings.amap_mcp_key.strip() or settings.amap_web_key.strip()
    if not key:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("key", key)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def enabled() -> bool:
    return bool(settings.amap_mcp_enabled and build_endpoint())


def _json_from_text(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 个别 MCP 服务会在 JSON 外包一层说明文字，尽量提取主体。
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _decode_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    payloads: list[Any] = []
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if text:
            parsed = _json_from_text(text)
            payloads.append(parsed if parsed is not None else text)
    if len(payloads) == 1:
        return payloads[0]
    return payloads


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or "")


def _resolve_tool(tools: list[Any], semantic_name: str) -> Any | None:
    aliases = _TOOL_ALIASES.get(semantic_name, (semantic_name,))
    by_name = {_tool_name(tool): tool for tool in tools}
    for alias in aliases:
        if alias in by_name:
            return by_name[alias]

    # 兼容官方服务后续改名：只根据工具名/描述选择只读搜索工具。
    keywords = {
        "search_poi": ("text", "search", "poi", "地点", "关键词"),
        "poi_detail": ("detail", "详情", "poi"),
        "geocode": ("geo", "地理编码"),
    }.get(semantic_name, ())
    for tool in tools:
        haystack = f"{_tool_name(tool)} {getattr(tool, 'description', '') or ''}".lower()
        if keywords and sum(1 for keyword in keywords if keyword.lower() in haystack) >= 2:
            return tool
    return None


async def _call_async(semantic_name: str, arguments: dict[str, Any]) -> Any:
    # 延迟导入：未开启 MCP 时，离线 fallback 和现有单测无需安装/初始化客户端。
    from mcp import ClientSession
    from mcp.client import streamable_http

    # MCP Python SDK 在不同小版本中曾使用过两种拼写，兼容当前锁定版本
    #（streamablehttp_client）和新版文档中的拼写。
    streamable_client = getattr(streamable_http, "streamable_http_client", None)
    if streamable_client is None:
        streamable_client = streamable_http.streamablehttp_client

    async with streamable_client(build_endpoint(), timeout=settings.amap_mcp_timeout) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            available = (await session.list_tools()).tools
            tool = _resolve_tool(available, semantic_name)
            if tool is None:
                raise RuntimeError(
                    f"高德 MCP 未找到查询工具 semantic={semantic_name}, "
                    f"available={[ _tool_name(item) for item in available ]}"
                )
            result = await session.call_tool(_tool_name(tool), arguments=arguments)
            if getattr(result, "isError", False):
                raise RuntimeError(f"高德 MCP 工具调用失败: {_tool_name(tool)}")
            return _decode_result(result)


def call(semantic_name: str, arguments: dict[str, Any]) -> Any | None:
    """同步调用官方 MCP，供当前同步 LangGraph 节点使用。失败返回 None。"""
    if not enabled():
        return None
    try:
        result = asyncio.run(asyncio.wait_for(_call_async(semantic_name, arguments), settings.amap_mcp_timeout))
        record_event("mcp", f"amap.{semantic_name}", metadata={"status": "ok"})
        return result
    except Exception as exc:  # noqa: BLE001 - 第三方能力失败必须可降级
        record_event("mcp", f"amap.{semantic_name}", status="error", error=str(exc))
        logger.warning("amap MCP call failed semantic=%s: %s", semantic_name, exc)
        return None


def search_poi(keywords: str, city: str | None = None, *, around: str | None = None,
               radius: int | None = None) -> Any | None:
    """调用高德 MCP POI 查询；参数名与官方能力保持语义一致。"""
    args: dict[str, Any] = {"keywords": keywords}
    if city:
        args["city"] = city
    if around:
        args["location"] = around
    if radius is not None:
        args["radius"] = radius
    return call("search_poi", args)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def extract_pois(payload: Any) -> list[dict]:
    """从官方 MCP 的结构化结果或文本结果中提取 POI 列表。"""
    if payload is None:
        return []
    for obj in _walk_dicts(payload):
        pois = obj.get("pois")
        if isinstance(pois, list):
            return [item for item in pois if isinstance(item, dict)]
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    return []


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_pois(payload: Any, category: str | None = None) -> list[dict]:
    """转换为项目内部 POI 契约，并附带数据来源信息。"""
    fetched_at = datetime.now(timezone.utc).isoformat()
    normalized: list[dict] = []
    for raw in extract_pois(payload):
        name = str(raw.get("name") or raw.get("title") or "").strip()
        if not name:
            continue
        location = str(raw.get("location") or "")
        lng, lat = None, None
        parts = location.split(",")
        if len(parts) == 2:
            lng, lat = _number(parts[0]), _number(parts[1])
        photos = raw.get("photos") or []
        image = None
        if isinstance(photos, list):
            for photo in photos:
                if isinstance(photo, dict) and photo.get("url"):
                    image = str(photo["url"])
                    break
        item = {
            "id": str(raw.get("id") or raw.get("poi_id") or f"amap:{name}"),
            "name": name,
            "category": category or raw.get("category") or "attraction",
            "address": raw.get("address") or None,
            "latitude": lat if lat is not None else _number(raw.get("latitude")),
            "longitude": lng if lng is not None else _number(raw.get("longitude")),
            "ticket_price": _number(raw.get("ticket_price") or raw.get("cost")),
            "duration_min": int(_number(raw.get("duration_min")) or 0) or None,
            "open_time": raw.get("open_time") or raw.get("opening_hours") or None,
            "tags": raw.get("tags") or raw.get("type") or "",
            "rating": _number(raw.get("rating")),
            "description": raw.get("description") or None,
            "image": image,
            "source": "amap-mcp",
            "source_fetched_at": fetched_at,
        }
        normalized.append(item)
    return normalized
