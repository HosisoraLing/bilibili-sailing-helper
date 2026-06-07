#!/bin/bash
# B站舰礼助手 - 自动更新脚本

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

REPO_URL="https://github.com/HosisoraLing/bilibili-sailing-helper.git"
BRANCH="main"

# 检查是否有更新
check_update() {
    info "检查GitHub更新..."
    
    # 获取远程最新提交
    git fetch origin $BRANCH 2>/dev/null
    
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/$BRANCH)
    
    if [ "$LOCAL" = "$REMOTE" ]; then
        info "已是最新版本"
        return 1
    else
        BEHIND=$(git rev-list --count HEAD..origin/$BRANCH)
        success "发现 $BEHIND 个新提交"
        return 0
    fi
}

# 备份当前版本
backup_current() {
    info "备份当前版本..."
    BACKUP_DIR="/tmp/bilibili-sailing-helper-backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # 备份配置和数据
    cp -r data "$BACKUP_DIR/" 2>/dev/null || true
    cp -r logs "$BACKUP_DIR/" 2>/dev/null || true
    cp settings.json "$BACKUP_DIR/" 2>/dev/null || true
    
    echo "$BACKUP_DIR"
}

# 拉取更新
pull_update() {
    info "拉取最新代码..."
    
    # 保存本地修改
    STASHED=false
    if ! git diff --quiet; then
        git stash push -m "auto-update-stash-$(date +%s)" 2>/dev/null
        STASHED=true
    fi
    
    # 拉取更新
    git pull origin $BRANCH
    
    # 恢复本地修改
    if [ "$STASHED" = true ]; then
        git stash pop 2>/dev/null || warn "本地修改恢复失败，可能需要手动处理冲突"
    fi
    
    success "代码更新完成"
}

# 重建Docker镜像
rebuild_docker() {
    info "重建Docker镜像..."
    
    # 停止并删除旧容器
    if command -v docker compose &> /dev/null; then
        docker compose down
        docker compose build --no-cache
        docker compose up -d
    else
        docker-compose down
        docker-compose build --no-cache
        docker-compose up -d
    fi
    
    success "Docker服务已重启"
}

# 检查是否需要重建Docker
check_docker_rebuild() {
    if [ -f "/tmp/need_rebuild" ]; then
        info "检测到需要重建Docker镜像"
        rm -f /tmp/need_rebuild
        return 0
    fi
    return 1
}

# 重启服务（非Docker）
restart_service() {
    info "重启服务..."
    
    # 查找并停止旧进程
    pkill -f "python app.py" 2>/dev/null || true
    sleep 2
    
    # 启动新服务
    nohup python app.py > /dev/null 2>&1 &
    
    success "服务已重启"
}

# 检查服务健康
check_health() {
    info "检查服务健康状态..."
    sleep 5
    
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:7111/ | grep -q "200\|302"; then
        success "服务运行正常"
    else
        warn "服务可能未正常启动，请检查日志"
    fi
}

# 显示更新日志
show_changelog() {
    echo ""
    echo "=========================================="
    echo "           更新日志"
    echo "=========================================="
    git log --oneline -10
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "   B站舰礼助手 - 自动更新"
    echo "=========================================="
    echo ""
    
    # 检查是否在git仓库中
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        error "当前目录不是git仓库"
        exit 1
    fi
    
    # 检查是否需要重建Docker（由应用内部触发）
    if check_docker_rebuild; then
        rebuild_docker
        check_health
        exit 0
    fi
    
    # 检查更新
    if ! check_update; then
        exit 0
    fi
    
    # 显示更新日志
    show_changelog
    
    # 备份
    BACKUP_DIR=$(backup_current)
    info "备份已保存到: $BACKUP_DIR"
    
    # 拉取更新
    pull_update
    
    # 重启服务
    if [ -f "docker-compose.yml" ] && command -v docker &> /dev/null; then
        rebuild_docker
    else
        restart_service
    fi
    
    # 检查健康
    check_health
    
    echo ""
    success "更新完成！"
    echo "备份位置: $BACKUP_DIR"
    echo ""
}

# 支持命令行参数
case "${1:-}" in
    --check)
        check_update
        ;;
    --check-rebuild)
        check_docker_rebuild && rebuild_docker
        ;;
    --force)
        pull_update
        if [ -f "docker-compose.yml" ] && command -v docker &> /dev/null; then
            rebuild_docker
        else
            restart_service
        fi
        ;;
    *)
        main
        ;;
esac
