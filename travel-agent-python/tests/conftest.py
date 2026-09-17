"""全局测试夹具：默认关闭内部 Token，避免本地 .env 配置导致 HTTP 测试 401。

需要测鉴权的用例可自行 monkeypatch settings.agent_internal_token。
"""

import os

import pytest

# 会话签名密钥：少数用例用 TestClient(main.app) 会触发 lifespan，而启动守卫要求
# ≥32 字符（切流量后本服务自己签发 TA_AUTH）。带 example 标记，属占位符不是真密钥。
os.environ.setdefault("JWT_SECRET", "example-only-pytest-jwt-signing-material")


@pytest.fixture(autouse=True)
def _default_clear_agent_internal_token(monkeypatch):
    from app.common.config import settings

    monkeypatch.setattr(settings, "agent_internal_token", "")
    yield


@pytest.fixture(autouse=True)
def _pin_redis_unreachable(monkeypatch):
    """离线套件的既有假设：默认环境**无可用 Redis**（CI 即如此）。

    本机 6380 若起着常驻 Redis，cache_store 会真连上去：详情缓存这类带 TTL 的键
    会跨 pytest 进程残留（实测：cover unsplash 用例读到上一进程 upload 用例写的
    旧详情——它把 evict 桩掉，无法清键），幂等占位同理。统一钉死到不可达端口，
    强制各模块走进程内降级；专门测 Redis 行为的用例自行 monkeypatch 覆盖本值。
    """
    from app.common.config import settings

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    yield


@pytest.fixture(autouse=True)
def _disable_weather(monkeypatch):
    """离线套件默认关闭 Open-Meteo 天气（C3.1）：生成链路的 synthesize 会取天气，
    不关会让研究路径打真实外网；天气语义专门由 test_weather.py 显式开启覆盖。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "weather_enabled", False)
    yield


@pytest.fixture(autouse=True)
def _clear_external_client_caches():
    """G-3.2：外部调用基类带进程内 TTL 缓存，跨用例会互相污染。

    典型症状：前一个用例把「无图」/「搜不到」的负结果存进缓存，后一个用例
    打了桩却拿到缓存的 None，表现为"桩没生效"。这里在用例前后各清一次，
    让每个用例从干净缓存出发（正/负 TTL 的语义由 test_external_client 专门覆盖）。
    """
    from app.agent import places, pricing, tools, weather, web_search

    clients = (
        tools._image_client,
        tools._wiki_client,
        places._otm_geo_client,
        places._otm_radius_client,
        places._otm_detail_client,
        places._nominatim_client,
        pricing._price_client,
        web_search._search_client,
        weather._weather_client,
    )
    for client in clients:
        client.clear_cache()
    yield
    for client in clients:
        client.clear_cache()


@pytest.fixture(autouse=True)
def _reset_addon_state_cache():
    """addons.is_enabled 的进程内 TTL 缓存（5s）同样跨用例污染。

    前序用例在它自己的 settings 补丁下读到的布尔值会被缓存住；后续用例改回
    settings 也拿不到重读——实测：test_research_agents 在 live_price_search=False
    下触发一次 is_enabled("live_price")，紧随其后的 test_format_output_golden
    把开关钉回 True 仍读到缓存的 False，实时价预算归零，golden 快照 10 处 diff
    （只有把两个文件换个顺序或走全量字母序才不红）。每个用例前后各 reset 一次，
    让 is_enabled 在当前用例的 settings 口径下重新解析；专门测缓存/TTL 语义的
    用例（test_addons）都在单用例内自洽，不受影响。
    """
    from app.common import addons

    addons.reset_cache()
    yield
    addons.reset_cache()
