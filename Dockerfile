# ============================================================
# 构建阶段：安装依赖
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# 使用国内镜像源
RUN sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources

# 安装系统依赖（blivedm 需要 git，cryptography 需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements 利用 Docker 层缓存
COPY requirements.txt .

# 使用阿里云pip镜像源（清华源偶发403）
RUN pip install --no-cache-dir --prefix=/install \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    --retries 3 \
    -r requirements.txt


# ============================================================
# 运行阶段：精简镜像
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# 使用国内镜像源
RUN sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources

# 安装运行时依赖（包括Playwright所需的系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 创建应用用户（带home目录）
RUN useradd -m -s /bin/bash appuser

# 复制应用代码
COPY --chown=appuser:appuser app.py config.py routes.py decorators.py constants.py migrate.py ./
COPY --chown=appuser:appuser db/        ./db/
COPY --chown=appuser:appuser services/  ./services/
COPY --chown=appuser:appuser utils/     ./utils/
COPY --chown=appuser:appuser storage/   ./storage/
COPY --chown=appuser:appuser static/    ./static/
COPY --chown=appuser:appuser templates/ ./templates/

# 创建数据和日志目录
RUN mkdir -p data logs && chown -R appuser:appuser data logs

# 切换到应用用户并安装Playwright浏览器
USER appuser
RUN playwright install chromium

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:80/')" || exit 1

CMD ["python", "app.py"]
