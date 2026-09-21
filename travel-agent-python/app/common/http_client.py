"""共享 HTTP 客户端（G-3.2 自 app/services 提级到 common）。

归属说明：本模块是**基础设施**而非业务服务——agent 层（图片落地）与 services 层
（封面/图库代理）都要用它，放在 services 会让 agent 反向依赖 services（违反
「api → services → agent」分层）。common 层对两侧都可见，是唯一不破分层的落点。


超时口径：图片通道 connect 2.5s / read 7s（沿用迁移时的实测值，逐字保留）；
通用第三方通道刻意设了明确上限——第三方地图服务无超时会在生产上拖死线程池。

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
    """外部数据 API 通道（OpenTripMap/Nominatim 等结构化 JSON 接口）。"""
    global _api_client
    if _api_client is None:
        _api_client = httpx.Client(timeout=API_TIMEOUT, follow_redirects=False)
    return _api_client


def configure_clients(image: httpx.Client | None = None, api: httpx.Client | None = None) -> None:
    """测试注入点（httpx.MockTransport）。"""
    global _image_client, _api_client
    _image_client = image
    _api_client = api
