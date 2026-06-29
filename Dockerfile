# ============================================================
# 构建阶段：安装依赖
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

ARG CN_MIRROR=0

# CN_MIRROR=1 时使用阿里云镜像源（国内网络加速）
RUN if [ "$CN_MIRROR" = "1" ]; then \
        sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 变更频率最低，放最前面最大化缓存命中
COPY requirements.txt .

# CN_MIRROR=1 时使用阿里云 pip 镜像（GitHub Actions 默认用 PyPI）
RUN if [ "$CN_MIRROR" = "1" ]; then \
        pip install --no-cache-dir --prefix=/install \
            -i https://mirrors.aliyun.com/pypi/simple/ \
            --trusted-host mirrors.aliyun.com \
            -r requirements.txt; \
    else \
        pip install --no-cache-dir --prefix=/install -r requirements.txt; \
    fi


# ============================================================
# 运行阶段：精简镜像
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

ARG CN_MIRROR=0

RUN if [ "$CN_MIRROR" = "1" ]; then \
        sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN useradd -m -s /bin/bash appuser

# -----------------------------------------------------------
# 层排序策略：变更频率从低到高
#
#   最低频  requirements.txt (builder 阶段已处理)
#   ↓       根入口 + db + utils — 业务骨架，很少改动
#   ↓       storage + static — 资源文件，偶尔改动
#   ↓       runtime — 运行角色入口，偶尔改动
#   ↓       services + route_handlers — 核心业务，频繁改动
#   最高频  templates — 前端页面，最频繁改动
#
# 当 services/ 或 route_handlers/ 变更时，其上游层（utils、
# static 等）仍命中缓存，仅重建变更层及其下游。
# -----------------------------------------------------------

# 根入口 + 数据层（很少改动）
COPY --chown=appuser:appuser app.py config.py routes.py decorators.py constants.py migrate.py ./
COPY --chown=appuser:appuser db/     ./db/
COPY --chown=appuser:appuser utils/  ./utils/

# 资源文件（偶尔改动）
COPY --chown=appuser:appuser storage/  ./storage/
COPY --chown=appuser:appuser static/   ./static/

# 运行角色入口（偶尔改动）
COPY --chown=appuser:appuser runtime/  ./runtime/

# 核心业务逻辑（频繁改动）
COPY --chown=appuser:appuser services/        ./services/
COPY --chown=appuser:appuser route_handlers/  ./route_handlers/

# 前端页面（最频繁改动）
COPY --chown=appuser:appuser templates/ ./templates/

# -----------------------------------------------------------

RUN mkdir -p data logs && chown -R appuser:appuser data logs

USER appuser

EXPOSE 7111

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7111/')" || exit 1

CMD ["python", "-m", "runtime.web"]
