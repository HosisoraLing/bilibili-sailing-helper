#!/bin/bash
# B站舰礼助手 - Docker 部署脚本
#
# 用法:
#   ./deploy.sh                      # 全量增量构建 + 重启所有服务
#   ./deploy.sh --web                # 只重建并重启 web
#   ./deploy.sh --danmaku            # 只重建并重启 danmaku-worker
#   ./deploy.sh --scheduler          # 只重建并重启 scheduler
#   ./deploy.sh --web --danmaku      # 重建并重启 web + danmaku-worker
#   ./deploy.sh --no-cache           # 全量重建（requirements.txt 变更时使用）
#   ./deploy.sh --build-only         # 只构建镜像，不重启服务
#   ./deploy.sh --restart-only       # 只重启服务，不重建镜像
#   ./deploy.sh --pull               # 拉取最新基础镜像后构建
#   ./deploy.sh --logs               # 部署后自动跟踪日志
#   ./deploy.sh --status             # 只显示服务状态
#   ./deploy.sh --update             # git pull + 增量构建 + 滚动重启

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ==================== 参数解析 ====================

NO_CACHE=false
PULL_BASE=false
FOLLOW_LOGS=false
BUILD_ONLY=false
RESTART_ONLY=false
STATUS_ONLY=false
DO_UPDATE=false
TARGET_SERVICES=()

for arg in "$@"; do
    case "$arg" in
        --no-cache)     NO_CACHE=true ;;
        --pull)         PULL_BASE=true ;;
        --logs)         FOLLOW_LOGS=true ;;
        --follow)       FOLLOW_LOGS=true ;;
        --build-only)   BUILD_ONLY=true ;;
        --restart-only) RESTART_ONLY=true ;;
        --status)       STATUS_ONLY=true ;;
        --update)       DO_UPDATE=true ;;
        --web)          TARGET_SERVICES+=("web") ;;
        --danmaku)      TARGET_SERVICES+=("danmaku-worker") ;;
        --scheduler)    TARGET_SERVICES+=("scheduler") ;;
        -h|--help)
            cat <<'EOF'
用法: ./deploy.sh [选项]

服务选择（可组合，默认全部）:
  --web            只操作 web 服务
  --danmaku        只操作 danmaku-worker 服务
  --scheduler      只操作 scheduler 服务

构建选项:
  --no-cache       全量重建（requirements.txt 变更时使用）
  --pull           拉取最新基础镜像
  --build-only     只构建镜像，不重启服务
  --restart-only   只重启服务，不重建镜像

部署选项:
  --update         git pull + 增量构建 + 滚动重启
  --logs           部署后跟踪日志（--follow 同义）
  --status         只显示服务状态，不做任何操作

示例:
  ./deploy.sh                    # 全量增量构建 + 重启
  ./deploy.sh --web              # 只重建 web
  ./deploy.sh --danmaku --logs   # 重建 danmaku-worker 并跟踪日志
  ./deploy.sh --no-cache         # 全量重建所有服务
  ./deploy.sh --restart-only     # 只重启，不重建（配置变更后）
  ./deploy.sh --update --logs    # 拉取更新 + 构建 + 重启 + 跟踪日志
EOF
            exit 0
            ;;
        *) warn "未知参数: $arg" ;;
    esac
done

# 默认：操作所有服务
if [ ${#TARGET_SERVICES[@]} -eq 0 ]; then
    TARGET_SERVICES=("web" "danmaku-worker" "scheduler")
fi

# 构建 compose 服务列表（用于 docker compose 命令）
COMPOSE_SERVICES="${TARGET_SERVICES[*]}"

# ==================== 工具函数 ====================

compose() {
    docker compose "$@"
}

service_names() {
    echo "${TARGET_SERVICES[*]}"
}

# ==================== 环境检查 ====================

check_docker() {
    command -v docker &> /dev/null || error "Docker 未安装"
    docker info &> /dev/null || error "Docker 服务未启动"
    compose version &> /dev/null || error "docker compose 不可用"
    success "Docker 环境正常"
}

check_config() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            warn ".env 不存在，从 .env.example 创建..."
            cp .env.example .env
        fi
        warn "请编辑 .env，固定设置 INTERNAL_API_SECRET 后重新运行"
        exit 0
    fi
    if ! grep -Eq '^INTERNAL_API_SECRET=.{16,}$' .env || grep -q 'replace-with-one-stable' .env; then
        error ".env 中 INTERNAL_API_SECRET 未设置为固定密钥"
    fi
    if [ ! -f "settings.json" ]; then
        if [ -f "settings.json.example" ]; then
            warn "settings.json 不存在，从示例文件创建..."
            cp settings.json.example settings.json
            warn "请编辑 settings.json 后重新运行"
            exit 0
        else
            error "settings.json 不存在"
        fi
    fi
    success "配置文件就绪"
}

prepare_dirs() {
    mkdir -p data logs
    chmod 777 data logs 2>/dev/null || true
    chmod 666 data/* 2>/dev/null || true
    # bind mount 的 settings.json 需要容器内 appuser 可写
    [ -f settings.json ] && chmod 666 settings.json 2>/dev/null || true
    success "目录权限就绪"
}

# ==================== Git 更新 ====================

pull_latest_code() {
    if [ ! -d ".git" ]; then
        warn "非 git 仓库，跳过代码更新"
        return 0
    fi

    info "拉取最新代码..."

    # 保存本地修改
    local stashed=false
    if ! git diff --quiet 2>/dev/null; then
        git stash push -m "deploy-stash-$(date +%s)" 2>/dev/null
        stashed=true
    fi

    if git pull origin main 2>/dev/null; then
        success "代码更新完成"
    else
        warn "git pull 失败，使用本地代码继续"
    fi

    # 恢复本地修改
    if [ "$stashed" = true ]; then
        git stash pop 2>/dev/null || warn "本地修改恢复失败，可能需要手动处理冲突"
    fi
}

# ==================== 构建 ====================

build_services() {
    if $RESTART_ONLY; then
        info "跳过构建（--restart-only）"
        return 0
    fi

    local build_args=""

    if $NO_CACHE; then
        info "全量重建（--no-cache）..."
        build_args="--no-cache"
    else
        info "增量构建（利用 Docker 层缓存）..."
    fi

    if $PULL_BASE; then
        info "拉取最新基础镜像..."
        compose pull 2>/dev/null || true
    fi

    info "构建服务: $(service_names)"
    compose build $build_args ${COMPOSE_SERVICES}
    success "镜像构建完成"
}

# ==================== 部署 ====================

deploy_services() {
    if $BUILD_ONLY; then
        info "跳过部署（--build-only）"
        return 0
    fi

    info "部署服务: $(service_names)"

    # 使用 --build 确保代码变更被应用
    # --no-deps 不重建依赖服务
    if $RESTART_ONLY; then
        compose up -d --no-deps ${COMPOSE_SERVICES}
    else
        compose up -d --build --no-deps ${COMPOSE_SERVICES}
    fi

    success "服务已启动"
}

# ==================== 健康检查 ====================

wait_for_web() {
    info "等待 web 服务就绪..."
    local retry=0
    while [ $retry -lt 15 ]; do
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:7111/ 2>/dev/null || echo "000")
        if echo "$code" | grep -q "200\|302"; then
            success "web 服务就绪"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    warn "web 启动超时，检查日志: docker compose logs web"
    return 1
}

check_service_health() {
    local service="$1"
    local container
    container=$(compose ps -q "$service" 2>/dev/null)

    if [ -z "$container" ]; then
        echo -e "  ${RED}●${NC} $service — 未运行"
        return
    fi

    local state
    state=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")

    if [ "$state" = "running" ]; then
        # 检查是否有 healthcheck
        local health
        health=$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")

        if [ "$health" = "healthy" ]; then
            echo -e "  ${GREEN}●${NC} $service — 运行中 (healthy)"
        elif [ "$health" = "unhealthy" ]; then
            echo -e "  ${RED}●${NC} $service — 运行中 (unhealthy)"
        else
            echo -e "  ${GREEN}●${NC} $service — 运行中"
        fi
    elif [ "$state" = "exited" ]; then
        local exit_code
        exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$container" 2>/dev/null || echo "?")
        echo -e "  ${RED}●${NC} $service — 已退出 (exit $exit_code)"
    else
        echo -e "  ${YELLOW}●${NC} $service — $state"
    fi
}

show_status() {
    echo ""
    echo -e "${CYAN}========== 服务状态 ==========${NC}"
    echo ""

    # 检查所有三个角色（无论 TARGET_SERVICES 是什么）
    check_service_health "web"
    check_service_health "danmaku-worker"
    check_service_health "scheduler"

    echo ""
    echo -e "${CYAN}========== 访问信息 ==========${NC}"
    echo ""
    echo "  首页:     http://localhost:7111"
    echo "  管理后台: http://localhost:7111/admin/panel"
    echo "  鉴权页面: http://localhost:7111/auth?uid=<B站UID>"
    echo ""
    echo -e "${CYAN}========== 常用命令 ==========${NC}"
    echo ""
    echo "  日志:     docker compose logs -f"
    echo "  Web日志:  docker compose logs -f web"
    echo "  弹幕日志: docker compose logs -f danmaku-worker"
    echo "  停止:     docker compose down"
    echo "  重启:     docker compose restart"
    echo ""
}

# ==================== 主流程 ====================

main() {
    echo ""
    echo -e "${CYAN}========== B站舰礼助手 ==========${NC}"
    echo ""

    # --status 只显示状态
    if $STATUS_ONLY; then
        show_status
        exit 0
    fi

    check_docker

    # --update 先拉代码
    if $DO_UPDATE; then
        pull_latest_code
    fi

    check_config
    prepare_dirs
    build_services
    deploy_services

    # 等待 web 就绪（如果部署了 web）
    for svc in "${TARGET_SERVICES[@]}"; do
        if [ "$svc" = "web" ]; then
            wait_for_web || true
            break
        fi
    done

    show_status

    $FOLLOW_LOGS && compose logs -f ${COMPOSE_SERVICES}
}

main
