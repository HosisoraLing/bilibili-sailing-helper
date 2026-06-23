# ============================================================
# 构建阶段：安装依赖
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# 使用国内镜像源
RUN sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources

# 安装系统依赖（cryptography 需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements 利用 Docker 层缓存
COPY requirements.txt .

# GitHub Actions 构建默认使用 PyPI，避免国内镜像源在 CI 中反而变慢。
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# 本地网络需要加速时，可改用阿里云 pip 镜像源：
# RUN pip install --no-cache-dir --prefix=/install \
#     -i https://mirrors.aliyun.com/pypi/simple/ \
#     --trusted-host mirrors.aliyun.com \
#     --retries 3 \
#     -r requirements.txt


# ============================================================
# 运行阶段：精简镜像
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# 使用国内镜像源
RUN sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 创建应用用户（带home目录）
RUN useradd -m -s /bin/bash appuser

COPY --chown=appuser:appuser app.py config.py routes.py decorators.py constants.py migrate.py ./
COPY --chown=appuser:appuser db/        ./db/
COPY --chown=appuser:appuser route_handlers/ ./route_handlers/
COPY --chown=appuser:appuser runtime/   ./runtime/
COPY --chown=appuser:appuser services/  ./services/
COPY --chown=appuser:appuser utils/     ./utils/
COPY --chown=appuser:appuser storage/   ./storage/
COPY --chown=appuser:appuser static/    ./static/
COPY --chown=appuser:appuser templates/ ./templates/

# 创建数据和日志目录
RUN mkdir -p data logs && chown -R appuser:appuser data logs

# 切换到应用用户运行
USER appuser

EXPOSE 7111

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7111/')" || exit 1

CMD ["python", "-m", "runtime.web"]
