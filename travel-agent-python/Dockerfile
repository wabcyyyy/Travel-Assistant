# Agent 运行镜像：依赖 + 业务代码 + RAG 语义模型（构建期预置，运行期不联网下载）。
FROM python:3.12-slim

WORKDIR /app

# RAG 语义模型：构建期下载进镜像（bge-small-zh-v1.5 约百 MB 量级）；
# 国内构建可用 --build-arg HF_ENDPOINT=https://hf-mirror.com 走镜像。
ARG RAG_MODEL=BAAI/bge-small-zh-v1.5
ARG HF_ENDPOINT=
ENV RAG_MODEL_CACHE_DIR=/app/models
ENV HF_ENDPOINT=${HF_ENDPOINT}

# 系统依赖（编译部分 wheel 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# torch 先走 CPU 源单独安装，避免默认 PyPI 的 CUDA 构建把镜像撑到数 GB
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir fastapi==0.111.0 "uvicorn[standard]==0.30.1" \
    pydantic==2.8.2 httpx==0.27.0 "mcp>=1.10,<2" python-dotenv==1.0.1 \
    langgraph==0.2.44 langchain-core==0.3.15 pymysql==1.2.0 "qdrant-client>=1.10,<2" \
    "redis>=5.2,<6" "sentence-transformers>=3.0,<6" \
    "sqlalchemy>=2.0,<3" "alembic>=1.13,<2" "bcrypt>=4,<6" "reportlab>=4.1,<5" \
    && python -c "from huggingface_hub import snapshot_download; snapshot_download('${RAG_MODEL}', cache_dir='/app/models')"

COPY . .

ENV AGENT_HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "main.py"]
