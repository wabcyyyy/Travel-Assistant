"""同源图片代理：SSRF 白名单 + 类型校验。

存在的意义：把 Unsplash/Wikimedia/Pexels 的图片转成同源响应，避免浏览器被热链
策略、防盗链或混合内容拦截；同时保证**只有白名单图床**能被服务端代取，防止
`?url=http://169.254.169.254/...` 这类内网探测。

高德/autonavi 图床已从白名单移除（2026-09-15 去高德）：存量行里可能仍存着
`store.is.autonavi.com` 的旧 URL，代理会 400，前端按既有降级链落到占位图。

与 Java 的差异（有意为之）：新增 8MB 上限。Java 是全量读进内存且无上限，
一张超大原图就能把 worker 打爆；这里超阈值直接 502。
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx
from fastapi import Response

from app.services.http_client import IMAGE_USER_AGENT, image_client

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
CACHE_CONTROL = "public, max-age=21600"  # 6 小时，与 Java CacheControl.maxAge(6h) 一致

_ALLOWED_EXACT = {
    "images.unsplash.com",
    "images.pexels.com",
    "images.weserv.nl",
    "upload.wikimedia.org",
    "wikipedia.org",
}
_ALLOWED_SUFFIX = (
    ".unsplash.com",
    ".pexels.com",
    ".wikimedia.org",
    ".wikipedia.org",
)


def is_allowed_image_host(host: str) -> bool:
    normalized = (host or "").lower()
    if not normalized:
        return False
    return normalized in _ALLOWED_EXACT or any(normalized.endswith(suffix) for suffix in _ALLOWED_SUFFIX)


def is_safe_image_url(url: str) -> bool:
    """scheme 必须 http/https、必须有 host、且 host 命中白名单。

    刻意拒绝带 userinfo 的 URL（`https://allowed.host@evil/`）：`urlsplit.hostname`
    会正确返回 evil，但某些下游库会按不同方式解析，不给自己留歧义面。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https"):
        return False
    if parts.username or parts.password:
        return False
    host = parts.hostname
    return bool(host) and is_allowed_image_host(host)


def guess_image_content_type(path: str | None) -> str:
    lowered = (path or "").lower()
    for suffix, media in (
        (".png", "image/png"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".svg", "image/svg+xml"),
        (".avif", "image/avif"),
    ):
        if lowered.endswith(suffix):
            return media
    return "image/jpeg"


def proxy_image(url: str) -> Response:
    """返回与 Java 同语义的响应：非白名单/非法 400、空 404、非图片或上游异常 502。"""
    if not is_safe_image_url(url):
        return Response(status_code=400)
    try:
        response = image_client().get(
            url,
            headers={
                "User-Agent": IMAGE_USER_AGENT,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("image proxy fetch failed: %s", exc)
        return Response(status_code=502)

    body = response.content
    if not body:
        return Response(status_code=404)
    if len(body) > MAX_IMAGE_BYTES:
        logger.warning("image proxy rejected oversized body: %d bytes from %s", len(body), urlsplit(url).hostname)
        return Response(status_code=502)

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if not content_type:
        content_type = guess_image_content_type(urlsplit(url).path)
    if not content_type.lower().startswith("image/"):
        return Response(status_code=502)
    return Response(content=body, media_type=content_type, headers={"Cache-Control": CACHE_CONTROL})
