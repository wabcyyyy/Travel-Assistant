# Agent 运行镜像：依赖 + 业务代码。本地模型目录通过 volume 挂载（见 compose）。
FROM python:3.12-slim

WORKDIR /app

# 系统依赖（编译部分 wheel 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# 若使用 uv 锁，可 COPY uv.lock 后 RUN pip install uv && uv sync
RUN pip install --no-cache-dir fastapi==0.111.0 "uvicorn[standard]==0.30.1" \
    pydantic==2.8.2 httpx==0.27.0 "mcp>=1.10,<2" python-dotenv==1.0.1 \
    langgraph==0.2.44 langchain-core==0.3.15 pymysql==1.2.0 chromadb==1.5.9

COPY . .

ENV AGENT_HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "main.py"]
