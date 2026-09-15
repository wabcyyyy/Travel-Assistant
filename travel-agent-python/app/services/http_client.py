"""共享 HTTP 客户端。

超时口径迁移说明：Java 的 `imageRestClient` 是 connect 2.5s / read 7s（见
`RestClientConfig.java:33-40`），这里逐字对齐；而 Java 调高德 Web API 用的默认
`RestClient` **没有设超时**（挂起时会一直等）。这里给它一个明确上限，属于有意改进，
不是等价移植——第三方地图服务无超时会在生产上拖死线程池。

`follow_redirects=False` 与 Java `SimpleClientHttpRequestFactory` 的默认行为一致：
跨主机重定向不自动跟随，避免白名单被 302 绕过。
"""

from __future__ import annotations

import httpx

IMAGE_TIMEOUT = httpx.Timeout(7.0, connect=2.5)
API_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

IMAGE_USER_AGENT = "Travel-Assistant/1.0"
WIKI_USER_AGENT = "TravelAssistantDemo/1.0"

_image_client: httpx.Client | None = None
_api_client: httpx.Client | None = None


def image_client() -> httpx.Client:
    """取图片/第三方图库通道（慢、只读、可容忍失败）。"""
    global _image_client
    if _image_client is None:
        _image_client = httpx.Client(timeout=IMAGE_TIMEOUT, follow_redirects=False)
    return _image_client


def api_client() -> httpx.Client:
    """高德 Web 服务 API 通道。"""
    global _api_client
    if _api_client is None:
        _api_client = httpx.Client(timeout=API_TIMEOUT, follow_redirects=False)
    return _api_client


def configure_clients(image: httpx.Client | None = None, api: httpx.Client | None = None) -> None:
    """测试注入点（httpx.MockTransport）。"""
    global _image_client, _api_client
    _image_client = image
    _api_client = api
