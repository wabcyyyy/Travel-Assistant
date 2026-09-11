"""全局测试夹具：默认关闭内部 Token，避免本地 .env 配置导致 HTTP 测试 401。

需要测鉴权的用例可自行 monkeypatch settings.agent_internal_token。
"""

import pytest


@pytest.fixture(autouse=True)
def _default_clear_agent_internal_token(monkeypatch):
    from app.common.config import settings

    monkeypatch.setattr(settings, "agent_internal_token", "")
    yield
