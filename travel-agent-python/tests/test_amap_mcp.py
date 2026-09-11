from app.agent import tools
from app.common.config import settings
from app.integrations import amap_mcp

import asyncio

import pytest


def test_build_endpoint_adds_server_key_without_logging_or_mutating_url(monkeypatch):
    monkeypatch.setattr(settings, "amap_mcp_url", "https://mcp.amap.com/mcp")
    monkeypatch.setattr(settings, "amap_mcp_key", "secret-key")
    assert amap_mcp.build_endpoint() == "https://mcp.amap.com/mcp?key=secret-key"


def test_normalize_official_poi_payload():
    payload = {
        "pois": [{
            "id": "B0001",
            "name": "西湖",
            "location": "120.149,30.242",
            "address": "杭州市西湖区",
            "type": "风景名胜",
            "photos": [{"url": "https://img.example/x.jpg"}],
        }]
    }
    result = amap_mcp.normalize_pois(payload, category="attraction")
    assert result[0]["id"] == "B0001"
    assert result[0]["longitude"] == 120.149
    assert result[0]["latitude"] == 30.242
    assert result[0]["source"] == "amap-mcp"
    assert result[0]["image"] == "https://img.example/x.jpg"


def test_search_amap_poi_prefers_mcp(monkeypatch):
    monkeypatch.setattr(tools.amap_mcp, "enabled", lambda: True)
    monkeypatch.setattr(
        tools.amap_mcp,
        "search_poi",
        lambda *_args, **_kwargs: {"pois": [{"name": "西湖", "location": "120.149,30.242"}]},
    )
    monkeypatch.setattr(tools, "_search_amap_rest", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("MCP 已返回结果，不应调用旧 REST API")
    ))

    result = tools.search_amap_poi("杭州", "西湖", category="attraction")
    assert result[0]["name"] == "西湖"


def test_search_amap_poi_falls_back_when_mcp_has_no_result(monkeypatch):
    monkeypatch.setattr(tools.amap_mcp, "enabled", lambda: True)
    monkeypatch.setattr(tools.amap_mcp, "search_poi", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tools,
        "_search_amap_rest",
        lambda *_args, **_kwargs: [{"name": "西湖", "source": "amap-rest"}],
    )
    assert tools.search_amap_poi("杭州", "西湖")[0]["source"] == "amap-rest"


# ---------- #27：工具名缓存 + 事件循环内调用 ----------


def test_tool_name_cache_remember_and_forget():
    amap_mcp._remember_tool_name("search_poi", "maps_text_search")
    assert amap_mcp._resolved_tools.get("search_poi") == "maps_text_search"
    amap_mcp._forget_tool_name("search_poi")
    assert "search_poi" not in amap_mcp._resolved_tools


def test_call_async_skips_list_tools_on_cache_hit(monkeypatch):
    """命中缓存时不再调用 list_tools（省一次网络握手）。"""
    pytest.importorskip("mcp")
    list_tools_calls = {"n": 0}
    call_args = {}

    class FakeTools:
        tools: list = []

    class FakeSession:
        async def initialize(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools(self):
            list_tools_calls["n"] += 1
            return FakeTools()

        async def call_tool(self, name, arguments):
            call_args["name"] = name
            class R:
                isError = False
                structuredContent = {"pois": []}
                content = []
            return R()

    class FakeCtx:
        async def __aenter__(self):
            return ("r", "w", lambda: None)

        async def __aexit__(self, *exc):
            return False

    def fake_client(*_a, **_k):
        return FakeCtx()

    import mcp as _mcp_mod
    monkeypatch.setattr("mcp.client.streamable_http.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcp.ClientSession", lambda *_a, **_k: FakeSession())
    amap_mcp._remember_tool_name("search_poi", "maps_text_search")
    try:
        asyncio.run(amap_mcp._call_async("search_poi", {"keywords": "西湖"}))
    finally:
        amap_mcp._forget_tool_name("search_poi")
    assert list_tools_calls["n"] == 0  # 缓存命中，未列工具
    assert call_args["name"] == "maps_text_search"


def test_call_from_within_running_loop_does_not_crash(monkeypatch):
    """在运行中的事件循环里调用 call() 不应因 asyncio.run 嵌套而崩。"""
    monkeypatch.setattr(amap_mcp, "enabled", lambda: True)
    monkeypatch.setattr(amap_mcp, "_call_async",
                        lambda semantic, arguments: _completed("done"))

    async def _completed(value):
        return value

    async def driver():
        # 处于运行中的 loop 内调用同步 call()：旧实现会抛 RuntimeError 被吞成 None。
        return amap_mcp.call("search_poi", {"keywords": "西湖"})

    result = asyncio.run(driver())
    assert result == "done"
