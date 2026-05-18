#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Clawith 一键部署脚本
# 目标服务器: 121.43.250.191
# 用法: ./deploy.sh [选项]
#
# 选项:
#   --skip-build    跳过本地构建，直接上传源码到服务器构建
#   --first-time    首次部署（安装 Docker 等依赖）
#   --restart       仅重启服务（不重新构建）
#   --help          显示帮助
# ═══════════════════════════════════════════════════════════════

set -e

# ─── 配置 ───────────────────────────────────────────────────
SERVER_IP="121.43.250.191"
SERVER_USER="root"
REMOTE_DIR="/opt/clawith"
PROJECT_NAME="clawith"
FRONTEND_PORT=3008

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── 参数解析 ─────────────────────────────────────────────────
SKIP_BUILD=false
FIRST_TIME=false
RESTART_ONLY=false

for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --first-time) FIRST_TIME=true ;;
        --restart) RESTART_ONLY=true ;;
        --help)
            echo "用法: ./deploy.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --skip-build    跳过本地构建，在服务器上构建"
            echo "  --first-time    首次部署（安装 Docker 等依赖）"
            echo "  --restart       仅重启服务（不重新构建镜像）"
            echo "  --help          显示帮助"
            exit 0
            ;;
    esac
done

# ─── 工具函数 ─────────────────────────────────────────────────
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

ssh_cmd() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${SERVER_USER}@${SERVER_IP}" "$@"
}

# ─── 检查本地环境 ─────────────────────────────────────────────
check_local() {
    log_info "检查本地环境..."

    if ! command -v ssh &>/dev/null; then
        log_err "未找到 ssh 命令"
        exit 1
    fi

    if ! command -v rsync &>/dev/null && ! command -v scp &>/dev/null; then
        log_err "未找到 rsync 或 scp，请安装其中之一"
        exit 1
    fi

    log_ok "本地环境检查通过"
}

# ─── 首次部署：安装服务器依赖 ──────────────────────────────────
setup_server() {
    log_info "首次部署：安装服务器依赖..."

    ssh_cmd << 'EOF'
set -e

echo ">>> 更新系统包..."
apt-get update -y || yum update -y

# 安装 Docker
if ! command -v docker &>/dev/null; then
    echo ">>> 安装 Docker..."
    if command -v apt-get &>/dev/null; then
        apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
        curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg 2>/dev/null || true
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
        apt-get update -y
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    elif command -v yum &>/dev/null; then
        yum install -y yum-utils
        yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
        yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi
    systemctl enable docker
    systemctl start docker
    echo ">>> Docker 安装完成"
else
    echo ">>> Docker 已安装"
fi

# 配置 Docker 镜像加速
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'DAEMON'
{
    "registry-mirrors": [
        "https://mirror.ccs.tencentyun.com",
        "https://docker.mirrors.ustc.edu.cn"
    ],
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3"
    }
}
DAEMON
systemctl daemon-reload
systemctl restart docker

# 安装 docker compose (v2)
if ! docker compose version &>/dev/null; then
    echo ">>> 安装 docker-compose-plugin..."
    if command -v apt-get &>/dev/null; then
        apt-get install -y docker-compose-plugin
    else
        COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep tag_name | cut -d '"' -f 4)
        curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
fi

# 创建项目目录
mkdir -p /opt/clawith

# 开放防火墙端口
if command -v ufw &>/dev/null; then
    ufw allow 3008/tcp
    ufw allow 8000/tcp
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-port=3008/tcp
    firewall-cmd --permanent --add-port=8000/tcp
    firewall-cmd --reload
fi

echo ">>> 服务器环境准备完成！"
EOF

    log_ok "服务器依赖安装完成"
}

# ─── 同步代码到服务器 ──────────────────────────────────────────
sync_code() {
    log_info "同步代码到服务器 ${SERVER_IP}:${REMOTE_DIR}..."

    # 创建远程目录
    ssh_cmd "mkdir -p ${REMOTE_DIR}"

    if command -v rsync &>/dev/null; then
        rsync -avz --progress \
            --exclude 'node_modules' \
            --exclude '.venv' \
            --exclude '__pycache__' \
            --exclude '.git' \
            --exclude '.vite' \
            --exclude '*.pyc' \
            --exclude '.data' \
            --exclude 'dist' \
            --exclude '.env' \
            ./ "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/"
    else
        # fallback to scp
        log_warn "rsync 不可用，使用 scp（速度较慢）..."
        scp -r \
            backend/ frontend/ docker-compose.yml .env.example \
            "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/"
    fi

    # 同步 .env 文件（如果本地存在）
    if [ -f .env ]; then
        log_info "同步 .env 配置文件..."
        if command -v rsync &>/dev/null; then
            rsync -avz .env "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/.env"
        else
            scp .env "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/.env"
        fi
    else
        log_warn "本地 .env 不存在，将在服务器上使用 .env.example 创建"
        ssh_cmd "cd ${REMOTE_DIR} && [ ! -f .env ] && cp .env.example .env || true"
    fi

    log_ok "代码同步完成"
}

# ─── 在服务器上构建并启动 ──────────────────────────────────────
deploy_remote() {
    log_info "在服务器上构建并启动服务..."

    ssh_cmd << EOF
set -e
cd ${REMOTE_DIR}

echo ">>> 设置环境变量..."
export FRONTEND_PORT=${FRONTEND_PORT}
export COMPOSE_PROJECT_NAME=${PROJECT_NAME}

# 确保 .env 存在
if [ ! -f .env ]; then
    cp .env.example .env
    echo ">>> 已从 .env.example 创建 .env，请稍后修改配置"
fi

# 确保 ss-nodes.json 存在（docker-compose 需要）
if [ ! -f ss-nodes.json ]; then
    echo '[]' > ss-nodes.json
fi

echo ">>> 停止旧容器..."
docker compose down --remove-orphans 2>/dev/null || true

echo ">>> 构建镜像..."
docker compose build --no-cache

echo ">>> 启动服务..."
docker compose up -d

echo ">>> 等待服务就绪..."
sleep 10

# 检查服务状态
echo ">>> 服务状态:"
docker compose ps

# 健康检查
echo ""
echo ">>> 健康检查..."
for i in \$(seq 1 30); do
    if curl -s -o /dev/null -m 3 http://localhost:${FRONTEND_PORT} 2>/dev/null; then
        echo "✅ 前端服务就绪 (\${i}s)"
        break
    fi
    if [ \$i -eq 30 ]; then
        echo "⚠️  前端服务启动超时，请检查日志: docker compose logs frontend"
    fi
    sleep 1
done

for i in \$(seq 1 30); do
    if curl -s -m 3 http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
        echo "✅ 后端服务就绪 (\${i}s)"
        break
    fi
    if [ \$i -eq 30 ]; then
        echo "⚠️  后端服务启动超时，请检查日志: docker compose logs backend"
    fi
    sleep 1
done

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅ Clawith 部署完成！"
echo "═══════════════════════════════════════════════"
echo ""
echo "  访问地址: http://${SERVER_IP}:${FRONTEND_PORT}"
echo "  API 地址: http://${SERVER_IP}:8000"
echo ""
echo "  常用命令:"
echo "    查看日志:   cd ${REMOTE_DIR} && docker compose logs -f"
echo "    重启服务:   cd ${REMOTE_DIR} && docker compose restart"
echo "    停止服务:   cd ${REMOTE_DIR} && docker compose down"
echo "    查看状态:   cd ${REMOTE_DIR} && docker compose ps"
echo ""
EOF

    log_ok "部署完成！"
}

# ─── 仅重启服务 ───────────────────────────────────────────────
restart_remote() {
    log_info "重启远程服务..."

    ssh_cmd << EOF
set -e
cd ${REMOTE_DIR}
export FRONTEND_PORT=${FRONTEND_PORT}
export COMPOSE_PROJECT_NAME=${PROJECT_NAME}

docker compose restart
sleep 5
docker compose ps

echo ""
echo "✅ 服务已重启"
echo "  访问地址: http://${SERVER_IP}:${FRONTEND_PORT}"
EOF

    log_ok "重启完成"
}

# ─── 主流程 ───────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Clawith 一键部署脚本${NC}"
    echo -e "${GREEN}  目标: ${SERVER_IP}${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo ""

    check_local

    # 首次部署
    if [ "$FIRST_TIME" = true ]; then
        setup_server
    fi

    # 仅重启
    if [ "$RESTART_ONLY" = true ]; then
        restart_remote
        exit 0
    fi

    # 同步代码
    sync_code

    # 构建并部署
    deploy_remote

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  🎉 部署成功！${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${CYAN}访问地址:${NC} http://${SERVER_IP}:${FRONTEND_PORT}"
    echo -e "  ${CYAN}API 地址:${NC} http://${SERVER_IP}:8000"
    echo ""
}

main "$@"
