#!/bin/bash
# B站舰礼助手 - 自动更新脚本
#
# 用法:
#   ./auto-update.sh          # 检查更新 + 备份 + 拉取 + 增量构建 + 重启
#   ./auto-update.sh --check  # 只检查是否有更新
#   ./auto-update.sh --force  # 跳过检查，强制拉取 + 构建 + 重启

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$SCRIPT_DIR/deploy.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

BRANCH="main"

# ==================== Git 操作 ====================

check_update() {
    if [ ! -d ".git" ]; then
        error "当前目录不是 git 仓库"
    fi

    info "检查 GitHub 更新..."
    git fetch origin "$BRANCH" 2>/dev/null || error "git fetch 失败"

    local local_hash remote_hash
    local_hash=$(git rev-parse HEAD)
    remote_hash=$(git rev-parse "origin/$BRANCH")

    if [ "$local_hash" = "$remote_hash" ]; then
        success "已是最新版本"
        return 1
    fi

    local behind
    behind=$(git rev-list --count "HEAD..origin/$BRANCH")
    success "发现 $behind 个新提交"
    return 0
}

show_changelog() {
    echo ""
    echo -e "${BLUE}========== 最近提交 ==========${NC}"
    git log --oneline -10 "HEAD..origin/$BRANCH" 2>/dev/null || git log --oneline -10
    echo ""
}

backup_data() {
    local backup_dir="/tmp/bsh-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"

    for item in data logs settings.json; do
        [ -e "$item" ] && cp -r "$item" "$backup_dir/" 2>/dev/null || true
    done

    echo "$backup_dir"
}

pull_code() {
    info "拉取最新代码..."

    local stashed=false
    if ! git diff --quiet 2>/dev/null; then
        git stash push -m "auto-update-$(date +%s)" 2>/dev/null
        stashed=true
    fi

    git pull origin "$BRANCH"

    if [ "$stashed" = true ]; then
        git stash pop 2>/dev/null || warn "本地修改恢复失败，可能需要手动处理冲突"
    fi

    success "代码更新完成"
}

# ==================== 主流程 ====================

main() {
    echo ""
    echo -e "${BLUE}========== B站舰礼助手 - 自动更新 ==========${NC}"
    echo ""

    case "${1:-}" in
        --check)
            check_update
            exit $?
            ;;
        --force)
            ;;
        *)
            check_update || exit 0
            ;;
    esac

    show_changelog

    local backup_dir
    backup_dir=$(backup_data)
    info "数据已备份到: $backup_dir"

    pull_code

    # 委托给 deploy.sh 完成构建和部署
    info "调用 deploy.sh 执行增量构建和部署..."
    exec "$DEPLOY" --update "$@"
}

main "$@"
