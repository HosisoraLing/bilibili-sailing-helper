#!/bin/bash
# B站舰礼助手 - Docker 部署脚本
# 用法:
#   ./deploy.sh              # 普通部署（利用缓存，代码变更秒级构建）
#   ./deploy.sh --no-cache   # 强制全量重建（依赖变更时使用）
#   ./deploy.sh --pull       # 更新基础镜像（python:3.11-slim）
#   ./deploy.sh --logs       # 部署后自动跟踪日志

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# 解析参数
NO_CACHE=false
PULL_BASE=false
FOLLOW_LOGS=false
for arg in "$@"; do
    case "$arg" in
        --no-cache)  NO_CACHE=true ;;
        --pull)      PULL_BASE=true ;;
        --logs)      FOLLOW_LOGS=true ;;
        -h|--help)
            echo "用法: ./deploy.sh [选项]"
            echo "  --no-cache   强制全量重建（requirements.txt 变更时使用）"
            echo "  --pull       更新基础镜像"
            echo "  --logs       部署后跟踪日志"
            exit 0
            ;;
        *) warn "未知参数: $arg" ;;
    esac
done

# ---------- 检查环境 ----------
check_docker() {
    command -v docker &> /dev/null || error "Docker 未安装"
    docker info &> /dev/null || error "Docker 服务未启动"
    success "Docker 环境正常"
}

# ---------- 拉取最新代码 ----------
pull_latest_code() {
    if [ -d ".git" ]; then
        info "拉取最新代码..."
        git pull origin main 2>/dev/null || warn "git pull 失败，使用本地代码继续"
        success "代码更新完成"
    fi
}

# ---------- 检查配置 ----------
check_config() {
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

# ---------- 准备目录 & 权限 ----------
prepare_dirs() {
    mkdir -p data logs
    # 容器内 appuser 需要写入权限
    chmod 777 data logs
    chmod 666 data/* 2>/dev/null || true
    success "目录权限就绪"
}

# ---------- 构建镜像 ----------
build_image() {
    local build_args=""

    if $NO_CACHE; then
        info "全量重建（--no-cache）..."
        build_args="--no-cache"
    else
        info "增量构建（利用 Docker 层缓存）..."
    fi

    if $PULL_BASE; then
        info "拉取最新基础镜像..."
        docker compose pull 2>/dev/null || true
    fi

    docker compose build $build_args
    success "镜像构建完成"
}

# ---------- 启动服务 ----------
start_service() {
    # 检测是否有代码/配置变更，决定是否需要重建
    local containers
    containers=$(docker compose ps -q 2>/dev/null)

    if [ -z "$containers" ]; then
        info "首次启动..."
        docker compose up -d --build
    else
        info "重启服务..."
        docker compose up -d
    fi

    success "服务已启动"
}

# ---------- 等待就绪 ----------
wait_for_service() {
    info "等待服务就绪..."
    local retry=0
    while [ $retry -lt 15 ]; do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:80/ 2>/dev/null | grep -q "200\|302"; then
            success "服务就绪"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    warn "启动超时，检查日志: docker compose logs"
}

# ---------- 状态展示 ----------
show_status() {
    echo ""
    docker compose ps 2>/dev/null
    echo ""
    echo "访问: http://localhost"
    echo ""
    echo "常用命令:"
    echo "  日志:   docker compose logs -f"
    echo "  停止:   docker compose down"
    echo "  重启:   docker compose restart"
    echo "  错误:   docker compose logs --tail=50 app"
    echo ""
}

# ---------- 主流程 ----------
main() {
    echo "========== B站舰礼助手 =========="
    echo ""

    check_docker
    pull_latest_code
    check_config
    prepare_dirs
    build_image
    start_service
    wait_for_service
    show_status

    $FOLLOW_LOGS && docker compose logs -f
}

main
