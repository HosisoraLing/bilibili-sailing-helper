#!/bin/bash
# B站舰礼助手 - 一键Docker部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# 检查Docker是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker 未安装，请先安装 Docker"
    fi
    
    if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
        error "Docker Compose 未安装，请先安装 Docker Compose"
    fi
    
    # 检查Docker服务是否运行
    if ! docker info &> /dev/null; then
        error "Docker 服务未启动，请启动 Docker 服务"
    fi
    
    success "Docker 环境检查通过"
}

# 检查配置文件
check_config() {
    if [ ! -f "settings.json" ]; then
        if [ -f "settings.json.example" ]; then
            warn "settings.json 不存在，正在从示例文件创建..."
            cp settings.json.example settings.json
            warn "请编辑 settings.json 填写你的配置后重新运行此脚本"
            exit 0
        else
            error "settings.json 和 settings.json.example 都不存在"
        fi
    fi
    success "配置文件检查通过"
}

# 创建必要的目录并设置权限
prepare_dirs() {
    info "准备数据和日志目录..."
    
    mkdir -p data logs
    
    # 设置目录权限（容器内appuser需要写入权限）
    chmod 777 data logs
    
    # 设置目录内文件权限
    chmod -R 666 data/* 2>/dev/null || true
    
    success "目录准备完成"
}

# 停止旧容器
stop_old_container() {
    if docker ps -a --format '{{.Names}}' | grep -q '^bilibili-sailing-helper$'; then
        info "停止旧容器..."
        docker compose down 2>/dev/null || docker-compose down 2>/dev/null
        success "旧容器已停止"
    fi
}

# 构建镜像
build_image() {
    info "开始构建 Docker 镜像（首次构建可能需要较长时间）..."
    
    if command -v docker compose &> /dev/null; then
        docker compose build --no-cache
    else
        docker-compose build --no-cache
    fi
    
    success "镜像构建完成"
}

# 启动服务
start_service() {
    info "启动服务..."
    
    if command -v docker compose &> /dev/null; then
        docker compose up -d
    else
        docker-compose up -d
    fi
    
    success "服务已启动"
}

# 等待服务就绪
wait_for_service() {
    info "等待服务启动..."
    
    local max_retries=30
    local retry=0
    
    while [ $retry -lt $max_retries ]; do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:7111/ | grep -q "200\|302"; then
            success "服务已就绪"
            return 0
        fi
        
        retry=$((retry + 1))
        sleep 2
    done
    
    warn "服务启动超时，请检查日志: docker compose logs"
}

# 显示服务状态
show_status() {
    echo ""
    echo "=========================================="
    echo "       服务部署完成"
    echo "=========================================="
    echo ""
    
    # 获取容器状态
    if command -v docker compose &> /dev/null; then
        docker compose ps
    else
        docker-compose ps
    fi
    
    echo ""
    echo "访问地址: http://localhost:7111"
    echo ""
    echo "常用命令:"
    echo "  查看日志: docker compose logs -f"
    echo "  停止服务: docker compose down"
    echo "  重启服务: docker compose restart"
    echo "  查看错误日志: docker compose exec app cat /app/logs/error.log"
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "   B站舰礼助手 - Docker 一键部署"
    echo "=========================================="
    echo ""
    
    check_docker
    check_config
    prepare_dirs
    stop_old_container
    build_image
    start_service
    wait_for_service
    show_status
}

# 运行主函数
main
