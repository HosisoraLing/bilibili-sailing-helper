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

# 运行时只需 git（blivedm 运行时可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 复制应用代码（settings.json 和 data/ 通过 volume 挂载，不打入镜像）
COPY app.py config.py routes.py decorators.py constants.py migrate.py ./
COPY db/        ./db/
COPY services/  ./services/
COPY utils/     ./utils/
COPY storage/   ./storage/
COPY static/    ./static/
COPY templates/ ./templates/

# 创建数据和日志目录（volume 挂载后会覆盖，这里只是保证目录存在）
RUN mkdir -p data logs

# 非 root 用户运行（安全最佳实践）
RUN useradd -r -s /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:80/')" || exit 1

CMD ["python", "app.py"]
