"""预置 RAG 语义模型到本地缓存（服务运行期不隐式联网，必须先下载）。

用法（travel-agent-python 目录下）：
    uv run python scripts/fetch_rag_model.py                 # 下载 RAG_EMBEDDING_MODEL
    uv run python scripts/fetch_rag_model.py --rerank        # 追加下载精排模型
    HF_ENDPOINT=https://hf-mirror.com uv run python scripts/fetch_rag_model.py

产物：embedding 模型写入 RAG_MODEL_CACHE_DIR（默认 models/，retriever 以 cache_folder
读取）；--rerank 的精排模型写入默认 HF 缓存（CrossEncoderReranker 不传 cache_folder）。
下载后立即用语义 provider 做一次探测，确认维度与降级状态（fallback 即失败）。
"""

import argparse
import os
import sys
from pathlib import Path

# 允许脚本独立运行（sys.path[0] 是 scripts/，需补模块根）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.common.config import settings


def _download(repo_id: str, cache_dir: str | None) -> None:
    if Path(repo_id).exists():
        # RAG_EMBEDDING_MODEL 允许直接指向本地模型目录（本机已放好权重）
        print(f"skip: {repo_id} 是本地路径，无需下载")
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("缺少 huggingface_hub：先执行 `uv sync`（sentence-transformers 会带入该依赖）") from exc
    target = cache_dir or "默认 HF 缓存"
    print(f"downloading {repo_id} -> {target}")
    kwargs = {"repo_id": repo_id}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    path = snapshot_download(**kwargs)
    print(f"ok: {path}")


def _verify_embedding() -> None:
    """下载后验证：provider 必须真正加载模型（降级到 hashed 即失败）。"""
    from app.rag.retriever import create_embedding_provider

    provider = create_embedding_provider()
    dim = len(provider.embed_query("dimension-probe"))
    if getattr(provider, "fallback", False):
        raise SystemExit(
            "模型已下载但 provider 仍降级为 hashed：请检查 sentence-transformers 依赖是否安装"
            f"（cache_dir={settings.rag_model_cache_dir}）"
        )
    print(f"ok: provider={provider.identity} dim={dim}")


def main() -> None:
    parser = argparse.ArgumentParser(description="预置 RAG 语义模型到本地缓存")
    parser.add_argument(
        "--model", default=settings.rag_embedding_model, help="embedding 模型 repo id（默认取 RAG_EMBEDDING_MODEL）"
    )
    parser.add_argument("--rerank", action="store_true", help="同时下载精排模型（启用 RAG_RERANK_PROVIDER 时需要）")
    parser.add_argument("--rerank-model", default=settings.rag_rerank_model)
    args = parser.parse_args()

    cache_dir = settings.rag_model_cache_dir
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    if not os.environ.get("HF_ENDPOINT"):
        print("提示：网络受限时可设置 HF_ENDPOINT=https://hf-mirror.com 走镜像")
    _download(args.model, cache_dir)
    if args.rerank:
        # 精排读取默认 HF 缓存（CrossEncoderReranker 不传 cache_folder），
        # 故 rerank 模型默认下载到 HF 缓存目录而不是 RAG_MODEL_CACHE_DIR
        _download(args.rerank_model, None)
    _verify_embedding()


if __name__ == "__main__":
    main()
