#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Clawith 一键 Docker 部署脚本
# 目标服务器: 121.43.250.191
#
# 使用方法:
#   1. 在本地执行: ./deploy/docker-deploy.sh
#      (自动打包、上传、在远程服务器上部署)
#
#   2. 在服务器上直接执行:
#      ./deploy/docker-deploy.sh --local
# ═══════════════════════════════════════════════════════════════

set -e

# ── 配置 ──────────────────────────────────────────────────────
SERVER_IP="121.43.250.191"
SERVER_USER="root"
DEPLOY_DIR="/opt/clawith"
DOMAIN="${DOMAIN:-$SERVER_IP}"
COMPOSE_FILE="docker-compose.prod.yml"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

if [ "$1" = "--local" ]; then
    LOCAL_MODE=true
else
    LOCAL_MODE=false
fi

# ═══════════════════════════════════════════════════════════════
# 远程模式：从本地推送到服务器
# ═══════════════════════════════════════════════════════════════
if [ "$LOCAL_MODE" = false ]; then
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  Clawith Docker 部署 → $SERVER_IP"
    echo "═══════════════════════════════════════════════════"
    echo ""

    # 检查 SSH
    echo "▶ 检查 SSH 连接..."
    ssh -o ConnectTimeout=10 -o BatchMode=yes ${SERVER_USER}@${SERVER_IP} "echo ok" > /dev/null 2>&1 || \
        err "无法连接 ${SERVER_USER}@${SERVER_IP}，请确认:\n  1. SSH 密钥已配置\n  2. 服务器 22 端口已开放"
    log "SSH 连接正常"

    # 创建远程目录
    ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${DEPLOY_DIR}"

    # 同步代码（排除不需要的文件，保留远程 .env）
    echo ""
    echo "▶ 同步代码到服务器..."
    rsync -avz --progress \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='.vite' \
        --exclude='frontend/dist' \
        --exclude='backend/clawith.db' \
        --exclude='backend/clawith.db-wal' \
        --exclude='backend/clawith.db-shm' \
        --exclude='*.pyc' \
        --exclude='.env' \
        ./ ${SERVER_USER}@${SERVER_IP}:${DEPLOY_DIR}/
    log "代码同步完成"

    # 远程执行
    echo ""
    echo "▶ 在服务器上执行部署..."
    ssh -t ${SERVER_USER}@${SERVER_IP} "cd ${DEPLOY_DIR} && chmod +x deploy/docker-deploy.sh && bash deploy/docker-deploy.sh --local"

    echo ""
    echo "═══════════════════════════════════════════════════"
    log "部署完成!"
    echo ""
    echo "  🌐 访问地址: http://${SERVER_IP}:3008"
    echo "  🔧 健康检查: http://${SERVER_IP}:3008/api/health"
    echo ""
    echo "  ⚠️  确保阿里云安全组已放行端口 3008 (TCP)"
    echo "═══════════════════════════════════════════════════"
    exit 0
fi

# ═══════════════════════════════════════════════════════════════
# 本地模式：在服务器上执行
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Clawith Docker 本地部署"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: 安装 Docker ───────────────────────────────────────
echo "▶ 检查 Docker..."
if ! command -v docker &> /dev/null; then
    warn "Docker 未安装，正在安装（使用阿里云镜像）..."
    curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
    systemctl enable docker
    systemctl start docker
    log "Docker 安装完成"
else
    log "Docker 已安装: $(docker --version)"
fi

if ! docker compose version &> /dev/null; then
    warn "Docker Compose 插件未安装..."
    # 尝试多种安装方式
    if command -v apt-get &> /dev/null; then
        apt-get update -qq && apt-get install -y -qq docker-compose-plugin 2>/dev/null
    elif command -v yum &> /dev/null; then
        yum install -y docker-compose-plugin 2>/dev/null
    fi

    if ! docker compose version &> /dev/null; then
        # 手动安装
        COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep tag_name | cut -d '"' -f 4)
        curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
        ln -sf /usr/local/bin/docker-compose /usr/libexec/docker/cli-plugins/docker-compose 2>/dev/null || true
    fi
    log "Docker Compose 安装完成"
else
    log "Docker Compose: $(docker compose version --short)"
fi

# ── Step 2: 配置 Docker 镜像加速（中国服务器）─────────────────
if [ ! -f /etc/docker/daemon.json ] || ! grep -q "registry-mirrors" /etc/docker/daemon.json 2>/dev/null; then
    echo "▶ 配置 Docker 镜像加速..."
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json << 'EOF'
{
    "registry-mirrors": [
        "https://mirror.ccs.tencentyun.com",
        "https://docker.m.daocloud.io"
    ]
}
EOF
    systemctl daemon-reload
    systemctl restart docker
    log "Docker 镜像加速已配置"
fi

# ── Step 3: 生成 .env ─────────────────────────────────────────
echo ""
echo "▶ 配置环境变量..."
if [ ! -f .env ]; then
    # 生成随机密钥
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
    JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
    PG_PASSWORD=$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | xxd -p)

    cat > .env << EOF
# Clawith Production Environment
# Generated: $(date -Iseconds)
# Server: ${DOMAIN}

SECRET_KEY=${SECRET_KEY}
JWT_SECRET_KEY=${JWT_SECRET}
POSTGRES_PASSWORD=${PG_PASSWORD}

# 前端端口
FRONTEND_PORT=3008

# 公网访问地址
PUBLIC_BASE_URL=http://${DOMAIN}:3008

# Token 过期时间
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30

# 使用国内 pip 镜像加速构建
CLAWITH_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
CLAWITH_PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# 可选: 飞书 SSO
FEISHU_APP_ID=
FEISHU_APP_SECRET=

# 可选: AI 搜索 API
JINA_API_KEY=
EXA_API_KEY=
EOF
    log ".env 已生成（密钥随机，PostgreSQL 密码随机）"
else
    log ".env 已存在，保留现有配置"
fi

# ── Step 4: 确保 swap 足够（防止构建 OOM）─────────────────────
echo ""
echo "▶ 检查内存..."
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
SWAP_SIZE=$(free -m | awk '/^Swap:/{print $2}')
if [ "$TOTAL_MEM" -lt 3000 ] && [ "$SWAP_SIZE" -lt 2000 ]; then
    warn "内存不足 3G 且 swap 不足，创建 2G swap..."
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
        log "2G swap 已创建"
    fi
fi
log "内存: ${TOTAL_MEM}MB, Swap: $(free -m | awk '/^Swap:/{print $2}')MB"

# ── Step 5: 构建并启动 ───────────────────────────────────────
echo ""
echo "▶ 构建 Docker 镜像（首次可能需要 5-10 分钟）..."
docker compose -f ${COMPOSE_FILE} build

echo ""
echo "▶ 启动服务..."
docker compose -f ${COMPOSE_FILE} down 2>/dev/null || true
docker compose -f ${COMPOSE_FILE} up -d

# ── Step 6: 等待就绪 ─────────────────────────────────────────
echo ""
echo "▶ 等待服务启动..."
MAX_WAIT=90
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    # 通过前端 nginx 代理检查后端健康
    if curl -sf http://localhost:3008/api/health > /dev/null 2>&1; then
        break
    fi
    sleep 3
    WAITED=$((WAITED + 3))
    printf "."
done
echo ""

if [ $WAITED -ge $MAX_WAIT ]; then
    warn "启动超时，查看日志排查问题:"
    echo "  docker compose -f ${COMPOSE_FILE} logs backend --tail=50"
    echo "  docker compose -f ${COMPOSE_FILE} logs postgres --tail=20"
    echo ""
    docker compose -f ${COMPOSE_FILE} logs backend --tail=20
else
    log "所有服务已就绪!"
fi

# ── Step 7: 防火墙 ───────────────────────────────────────────
echo ""
echo "▶ 配置防火墙..."
if command -v ufw &> /dev/null; then
    ufw allow 3008/tcp 2>/dev/null && log "UFW: 端口 3008 已开放" || true
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-port=3008/tcp 2>/dev/null && firewall-cmd --reload 2>/dev/null && log "Firewalld: 端口 3008 已开放" || true
else
    warn "请手动确认端口 3008 已开放"
fi

# ── Step 8: 状态 ─────────────────────────────────────────────
echo ""
echo "▶ 服务状态:"
docker compose -f ${COMPOSE_FILE} ps
echo ""

# 测试访问
if curl -sf http://localhost:3008/api/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://localhost:3008/api/health)
    echo "  健康检查: $HEALTH"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ 部署完成!"
echo ""
echo "  🌐 访问地址:  http://${DOMAIN}:3008"
echo "  🔧 健康检查:  http://${DOMAIN}:3008/api/health"
echo ""
echo "  常用命令:"
echo "    查看日志:   docker compose -f ${COMPOSE_FILE} logs -f"
echo "    重启:       docker compose -f ${COMPOSE_FILE} restart"
echo "    停止:       docker compose -f ${COMPOSE_FILE} down"
echo "    更新:       git pull && docker compose -f ${COMPOSE_FILE} up -d --build"
echo ""
echo "  ⚠️  阿里云安全组需放行: 3008/TCP (入方向)"
echo "═══════════════════════════════════════════════════"
