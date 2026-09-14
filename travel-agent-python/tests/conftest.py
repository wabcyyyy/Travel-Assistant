"""全局测试夹具：默认关闭内部 Token，避免本地 .env 配置导致 HTTP 测试 401。

需要测鉴权的用例可自行 monkeypatch settings.agent_internal_token。
"""

import os
import tempfile

import pytest

# 测试进程的 Qdrant 路径与开发/运行实例隔离：本地模式对存储目录加进程间
# 文件锁，TestClient 启动事件的 warmup 若打到默认 data/qdrant，会与正在
# 运行的 Agent 撞锁。必须在 app 模块（settings）导入前设置。目录跨运行
# 复用，指纹增量同步使其与全量重建结果一致，重复运行不必重 embed。
os.environ.setdefault(
    "QDRANT_PATH",
    os.path.join(tempfile.gettempdir(), "ta-pytest-qdrant", "qdrant"),
)
# 测试环境禁用惰性刷新：多次 TestClient lifespan 会反复触发全量指纹比对，
# 把整档回归拖慢一个量级；单测不依赖"60 秒后数据新鲜度"语义。
os.environ.setdefault("RAG_REFRESH_SECONDS", "0")
# 单测固定 hashed 向量：零模型加载、离线确定性；默认值本身由
# test_env_example_alignment 静态校验。需验证语义路径时显式覆盖：
#   RAG_EMBEDDING_PROVIDER=semantic uv run pytest tests/test_rag_retriever.py
os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "hashed")
# 同理关闭精排模型：单测不应因本地 .env 开启 cross-encoder 而加载真实权重
os.environ.setdefault("RAG_RERANK_PROVIDER", "none")


@pytest.fixture(autouse=True)
def _default_clear_agent_internal_token(monkeypatch):
    from app.common.config import settings

    monkeypatch.setattr(settings, "agent_internal_token", "")
    yield
