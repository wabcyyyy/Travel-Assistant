# Agent 运行镜像：依赖来自 uv.lock（G-1.3 ⑤：禁手写 pip 列表，lock 是唯一真相源）
# + 业务代码 + RAG 语义模型（构建期预置，运行期不联网下载）。
# 多阶段：deps 阶段 uv sync --frozen 装 lock 依赖并下载模型；runtime 只带
# venv + 代码 + 模型，非 root 运行，无编译工具链。

# ---- deps：依赖与模型 ----
FROM python:3.12-slim AS deps
# uv 版本固定保证构建可重现；须 >= 生成 uv.lock 的本机 uv（0.11.x，lock revision 3）
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
WORKDIR /app
# 部分 wheel 缺预编译时的编译兜底；runtime 阶段不带
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
# torch 已随 pyproject 的 pytorch-cpu index 配置进 lock：uv sync 自动走 CPU 源，
# 不会再拉 PyPI 的 CUDA 构建（数 GB）——旧手写 pip 列表正是为绕这个，已无必要。
RUN uv sync --frozen --no-dev

# RAG 语义模型：构建期下载进镜像（bge-small-zh-v1.5 约百 MB 量级）；
# 国内构建可用 --build-arg HF_ENDPOINT=https://hf-mirror.com 走镜像。
# 离线/受限网络构建可 --build-arg DOWNLOAD_RAG_MODEL=false 跳过下载
# （镜像内无模型将无法起跑 RAG，运行期须自行挂载模型目录）。
ARG RAG_MODEL=BAAI/bge-small-zh-v1.5
ARG HF_ENDPOINT=
ARG DOWNLOAD_RAG_MODEL=true
# 新版 huggingface_hub 默认走 Xet 存储（cas-bridge.xethub.hf.co），CN 网络不可达
# 且不经 HF_ENDPOINT 镜像代理；禁用后回落经典 HTTP 路径，镜像端点才生效。
ENV RAG_MODEL_CACHE_DIR=/app/models \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HUB_DISABLE_XET=1
RUN if [ "$DOWNLOAD_RAG_MODEL" = "true" ]; then \
        uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('${RAG_MODEL}', cache_dir='/app/models')"; \
    fi
# 跳过下载时也要有该目录，runtime 阶段 COPY 才不会失败
RUN mkdir -p /app/models

# ---- runtime：venv + 代码 + 模型，非 root ----
FROM python:3.12-slim
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /app/models /app/models
COPY . .
ENV PATH="/app/.venv/bin:$PATH" \
    RAG_MODEL_CACHE_DIR=/app/models \
    AGENT_HOST=0.0.0.0
EXPOSE 8000
# 非 root 运行。注意：compose 把宿主机 data/ 目录 bind mount 到 /app/data
# （上传图与 PDF 导出落盘处），宿主目录 UID 与 1000 不一致时需宿主侧 chown。
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/agent/health', timeout=4)"]
CMD ["python", "main.py"]
