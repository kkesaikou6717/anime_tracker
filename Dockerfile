FROM python:3.11-slim

LABEL maintainer="Raana (Anime Tracker Dev)"
LABEL description="Anime Tracker — 自动化追番后端服务"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY src/ ./src/
COPY config/ ./config/

# 创建 data 目录挂载点
RUN mkdir -p /app/data/logs

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/api/health || exit 1

EXPOSE 8765

CMD ["python", "src/main.py"]
