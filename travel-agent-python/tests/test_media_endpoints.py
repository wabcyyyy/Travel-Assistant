"""图片域端点验证（去高德版，全离线 MockTransport）。

钉住的仍不是"能不能返回 200"，而是几个**出错就有害**的行为：
SSRF 白名单不可被 userinfo/后缀拼接绕过、图库查询禁止携带城市词、
维基系熔断只在连接异常时触发、空结果负缓存不重放外网链路。
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import security
from app.api.business.media import router as media_router
from app.common import redis_client
from app.common.envelope import install_exception_handlers
from app.services import cache_store, image_proxy, poi_photo
from app.services.http_client import configure_clients
from app.services.image_proxy import is_safe_image_url

UNSPLASH_KEY = "test-unsplash-key"
PEXELS_KEY = "test-pexels-key"


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def _dispatch(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return self.handler(request)

        return httpx.MockTransport(_dispatch)

    def params_of(self, fragment: str) -> dict:
        for call in self.calls:
            if fragment in str(call.url):
                query = call.url.query
                query = query.decode("utf-8") if isinstance(query, bytes) else query
                return {k: v[0] for k, v in parse_qs(query).items()}
        return {}


def _json(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


@pytest.fixture
def env(monkeypatch):
    """默认：所有上游都"无图"，各测试按需覆盖具体 host 的响应。"""

    def default_handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if "wikipedia.org" in host or "wikimedia.org" in host:
            return _json({})
        return _json({"results": [], "photos": []})

    recorder = Recorder(default_handler)
    client = httpx.Client(transport=recorder.transport(), follow_redirects=False)
    configure_clients(image=client, api=client)
    cache_store.reset_for_tests()
    poi_photo.reset_state_for_tests()

    monkeypatch.setattr(poi_photo.settings, "unsplash_access_key", UNSPLASH_KEY)
    monkeypatch.setattr(poi_photo.settings, "pexels_access_key", PEXELS_KEY)
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(security, "authenticate", lambda token: security.AuthUser(id=1, username="alice", role="user"))

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(media_router)
    # follow_redirects=False：否则 poi-photo 的 302 会被自动跟到图片代理，
    # 断言不到重定向本身（且 Mock 上游返回 JSON 会表现为 502）
    yield app, recorder, TestClient(app, follow_redirects=False)
    configure_clients(None, None)


@pytest.fixture
def as_client(env):
    app, recorder, _ = env
    return TestClient(app, follow_redirects=False), recorder


# ---------- SSRF 白名单（高德/autonavi 图床已移除） ----------


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://images.unsplash.com/a.jpg", True),
        ("https://upload.wikimedia.org/x/y.png", True),
        ("https://a.b.wikipedia.org/x", True),
        ("https://imgs.unsplash.com/x", True),  # .unsplash.com 子域，与 Java 后缀规则一致
        ("https://store.is.autonavi.com/showpic/1", False),  # 高德图床已移出白名单
        ("http://restapi.amap.com/v3/staticmap", False),
        ("https://evil.com/x.jpg", False),
        ("https://notunsplash.com/x", False),  # 近似域名，不可靠前缀混淆
        ("https://images.unsplash.com.evil.com/x", False),  # 后缀拼接绕过
        ("https://images.unsplash.com@evil.com/x", False),  # userinfo 混淆
        ("http://169.254.169.254/latest/meta-data", False),  # 元数据端点
        ("file:///etc/passwd", False),
        ("https:///no-host", False),
        ("not a url", False),
    ],
)
def test_image_url_allowlist(url, allowed):
    assert is_safe_image_url(url) is allowed, url


def test_image_proxy_rejects_without_touching_upstream(env):
    app, recorder, _ = env
    response = _client(app).get("/api/image-proxy", params={"url": "http://169.254.169.254/x"})
    assert response.status_code == 400
    assert recorder.calls == []


def test_image_proxy_maps_empty_non_image_and_oversized(env):
    app, _recorder, _ = env
    cases = {
        "empty": httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b""),
        "html": httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"),
        "huge": httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=b"x" * (image_proxy.MAX_IMAGE_BYTES + 1)
        ),
    }
    expected = {"empty": 404, "html": 502, "huge": 502}
    for name, canned in cases.items():
        client = httpx.Client(transport=httpx.MockTransport(lambda _r, c=canned: c), follow_redirects=False)
        configure_clients(image=client, api=client)
        response = _client(app).get("/api/image-proxy", params={"url": "https://images.unsplash.com/a.jpg"})
        assert response.status_code == expected[name], name
    good = httpx.Response(200, headers={"content-type": "image/png"}, content=b"pngbytes")
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: good), follow_redirects=False)
    configure_clients(image=client, api=client)
    ok_response = _client(app).get("/api/image-proxy", params={"url": "https://images.unsplash.com/a.png"})
    assert ok_response.status_code == 200
    assert ok_response.headers["content-type"].startswith("image/png")
    assert ok_response.headers["cache-control"] == "public, max-age=21600"


def _client(app: FastAPI) -> TestClient:
    """统一入口：不自动跟随重定向，才能断言 poi-photo 的 302 本身。"""
    return TestClient(app, follow_redirects=False)


# ---------- POI 实景图多源解析（维基 → 图库；无高德） ----------


def test_poi_photo_gallery_queries_must_not_include_city(as_client):
    """图库只按名称检索：带上城市会命中该城泛化风景图，整页卡片变成无关照片。"""
    client, recorder = as_client

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"results": [{"urls": {"regular": "https://images.unsplash.com/x.jpg"}}]})

    recorder.handler = handler
    response = client.get("/api/poi-photo", params={"name": "灵隐寺", "city": "杭州"})
    assert response.status_code == 302
    assert response.headers["location"].startswith("/api/image-proxy?url=")
    params = recorder.params_of("api.unsplash.com")
    assert params.get("query") == "灵隐寺"
    assert "city" not in params and "杭州" not in json.dumps(params, ensure_ascii=False)


def test_poi_photo_prefers_wikipedia_over_gallery(as_client):
    client, recorder = as_client

    def handler(request: httpx.Request) -> httpx.Response:
        if "wikipedia.org" in (request.url.host or ""):
            return _json({"query": {"pages": {"1": {"thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"}}}}})
        return _json({"results": [{"urls": {"regular": "https://images.unsplash.com/x.jpg"}}]})

    recorder.handler = handler
    response = client.get("/api/poi-photo", params={"name": "西湖", "city": "杭州"})
    assert response.status_code == 302
    assert "upload.wikimedia.org" in response.headers["location"]


def test_poi_photo_never_calls_amap(as_client):
    """去高德后：任何情况下都不应再出现对高德域的请求。"""
    client, recorder = as_client
    client.get("/api/poi-photo", params={"name": "Fushimi Inari", "city": "京都"})
    client.get("/api/poi-photo", params={"name": "西湖", "city": "杭州"})
    assert not [c for c in recorder.calls if "amap.com" in (c.url.host or "")]


def test_poi_photo_404_when_no_source_and_negative_result_is_cached(as_client):
    client, recorder = as_client
    response = client.get("/api/poi-photo", params={"name": "不存在的地方", "city": "杭州"})
    assert response.status_code == 404
    first = len(recorder.calls)
    assert client.get("/api/poi-photo", params={"name": "不存在的地方", "city": "杭州"}).status_code == 404
    assert len(recorder.calls) == first, "空结果未缓存 → 每次开页都重放整条外网链路"


def test_poi_photo_validates_name_and_city_length(as_client):
    client, _ = as_client
    assert client.get("/api/poi-photo", params={"name": "名" * 65, "city": "杭州"}).status_code == 400
    assert client.get("/api/poi-photo", params={"name": "西湖", "city": ""}).status_code == 400


def test_wiki_cooldown_skips_wiki_sources_after_connection_error(env):
    app, recorder, _ = env

    def failing_wiki(request: httpx.Request) -> httpx.Response:
        if "wikipedia.org" in (request.url.host or ""):
            raise httpx.ConnectError("blocked")
        return _json({"results": [{"urls": {"regular": "https://images.unsplash.com/y.jpg"}}]})

    recorder.handler = failing_wiki
    client = _client(app)
    assert client.get("/api/poi-photo", params={"name": "西湖", "city": "杭州"}).status_code == 302
    wiki_calls_after_first = len([c for c in recorder.calls if "pedia" in (c.url.host or "")])
    assert wiki_calls_after_first >= 1, "首次请求应尝试过维基系"
    # 换一个点位名以避开 LRU 命中，真正检验冷却期是否跳过维基
    assert client.get("/api/poi-photo", params={"name": "断桥", "city": "杭州"}).status_code == 302
    wiki_calls_after_second = len([c for c in recorder.calls if "pedia" in (c.url.host or "")])
    assert wiki_calls_after_second == wiki_calls_after_first, "熔断期内不应再打维基"


def test_http_200_without_image_does_not_trip_breaker(as_client):
    """正常响应但无图 ≠ 维基不可达：误判会让整进程 5 分钟内都不出百科图。"""
    client, recorder = as_client
    recorder.handler = lambda _r: _json({})
    client.get("/api/poi-photo", params={"name": "断桥", "city": "杭州"})
    assert poi_photo.wiki_available() is True


def test_english_name_resolution_for_pexels(as_client):
    """Pexels 中文几乎无命中：非 ASCII 名先经 langlinks 换英文标题。"""
    client, recorder = as_client
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        query = parse_qs(request.url.query.decode("utf-8"))
        if "langlinks" in query.get("prop", [""])[0] and host.endswith("zh.wikipedia.org"):
            return _json({"query": {"pages": {"1": {"langlinks": [{"*": "West Lake"}]}}}})
        if "pexels" in host:
            seen["query"] = query.get("query", [""])[0]
            return _json({"photos": [{"src": {"large": "https://images.pexels.com/p.jpg"}}]})
        return _json({})

    recorder.handler = handler
    response = client.get("/api/poi-photo", params={"name": "西湖", "city": "杭州"})
    assert response.status_code == 302
    assert seen.get("query") == "West Lake"


def test_pexels_uses_bare_key_not_bearer(as_client):
    client, recorder = as_client

    def handler(request: httpx.Request) -> httpx.Response:
        if "pexels" in (request.url.host or ""):
            return _json({"photos": [{"src": {"medium": "https://images.pexels.com/m.jpg"}}]})
        return _json({})

    recorder.handler = handler
    client.get("/api/poi-photo", params={"name": "Tower Bridge", "city": "伦敦"})
    auth = next((c.headers.get("authorization") for c in recorder.calls if "pexels" in (c.url.host or "")), None)
    assert auth == PEXELS_KEY and not auth.startswith("Bearer")
