#!/usr/bin/env bash
# EduRAG 一键部署脚本（Linux / macOS / WSL）
# 用法: ./deploy.sh [start|stop|restart|logs]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

check_deps() {
    log "检查依赖..."
    if ! command -v docker &>/dev/null; then
        err "请先安装 Docker: https://docs.docker.com/get-docker/"
    fi
    if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null 2>&1; then
        err "请先安装 Docker Compose"
    fi
}

check_env() {
    log "检查环境变量..."
    if [ -z "$DASHSCOPE_API_KEY" ]; then
        if [ -f .env ]; then
            export $(grep -v '^#' .env | xargs)
        fi
    fi
    if [ -z "$DASHSCOPE_API_KEY" ]; then
        warn "未设置 DASHSCOPE_API_KEY 环境变量"
        warn "请执行: export DASHSCOPE_API_KEY=your-key"
        warn "或在项目根目录创建 .env 文件，写入: DASHSCOPE_API_KEY=your-key"
        echo -n "是否继续启动基础服务（不含API Key）？[y/N] "
        read -r answer
        if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
            err "已取消部署"
        fi
    fi
}

compose_cmd() {
    if docker compose version &>/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

start() {
    check_deps
    check_env
    log "构建并启动所有服务..."
    compose_cmd up -d --build
    log "等待服务就绪..."
    sleep 5
    log "服务状态:"
    compose_cmd ps
    echo ""
    log "部署完成！"
    log "API 文档: http://localhost:8000/docs"
    log "健康检查: http://localhost:8000/health"
}

stop() {
    log "停止所有服务..."
    compose_cmd down
    log "服务已停止"
}

restart() {
    log "重启所有服务..."
    compose_cmd down
    start
}

show_logs() {
    compose_cmd logs -f --tail=100
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    logs)    show_logs ;;
    *)
        echo "用法: $0 {start|stop|restart|logs}"
        exit 1
        ;;
esac
