#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Clawith 快速部署脚本（本地构建 + 镜像传输）
# 
# 核心思路：本地构建 Docker 镜像 → 导出 tar → 传到服务器 → 直接加载运行
# 跳过服务器上的 build 过程，大幅加速部署
#
# 使用方法:
#   ./deploy/fast-deploy.sh              # 完整流程（构建+传输+部署）
#   ./deploy/fast-deploy.sh --no-build   # 跳过构建，只传输已有镜像
#   ./deploy/fast-deploy.sh --server-only # 只在服务器上重启（不传输）
# ═══════════════════════════════════════════════════════════════

set -e

# ── 配置 ──────────────────────────────────────────────────────
SERVER_IP="121.43.250.191"
SERVER_USER="root"
DEPLOY_DIR="/opt/clawith"
COMPOSE_FILE="docker-compose.prod.yml"
IMAGE_BACKEND="clawith-backend:latest"
IMAGE_FRONTEND="clawith-frontend:latest"
TAR_FILE="/tmp/clawith-images.tar.gz"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[→]${NC} $1"; }

# 解析参数
NO_BUILD=false
SERVER_ONLY=false
for arg in "$@"; do
    case $arg in
        --no-build) NO_BUILD=true ;;
        --server-only) SERVER_ONLY=true ;;
    esac
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Clawith 快速部署（本地构建 → 镜像传输）"
echo "  目标: ${SERVER_IP}"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 检查 SSH ─────────────────────────────────────────────────
info "检查 SSH 连接..."
ssh -o ConnectTimeout=10 -o BatchMode=yes ${SERVER_USER}@${SERVER_IP} "echo ok" > /dev/null 2>&1 || \
    err "无法连接 ${SERVER_USER}@${SERVER_IP}"
log "SSH 连接正常"

# ═══════════════════════════════════════════════════════════════
# Step 1: 本地构建镜像
# ═══════════════════════════════════════════════════════════════
if [ "$SERVER_ONLY" = false ] && [ "$NO_BUILD" = false ]; then
    echo ""
    info "Step 1/4: 本地构建 Docker 镜像..."
    
    # 构建后端镜像
    echo "  → 构建 backend..."
    docker build \
        --build-arg CLAWITH_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
        --build-arg CLAWITH_PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
        -t ${IMAGE_BACKEND} \
        ./backend
    
    # 构建前端镜像
    echo "  → 构建 frontend..."
    docker build -t ${IMAGE_FRONTEND} ./frontend
    
    log "镜像构建完成"
fi

# ═══════════════════════════════════════════════════════════════
# Step 2: 导出并压缩镜像
# ═══════════════════════════════════════════════════════════════
if [ "$SERVER_ONLY" = false ]; then
    echo ""
    info "Step 2/4: 导出镜像为 tar.gz..."
    
    docker save ${IMAGE_BACKEND} ${IMAGE_FRONTEND} | gzip > ${TAR_FILE}
    
    TAR_SIZE=$(du -h ${TAR_FILE} | cut -f1)
    log "镜像已导出: ${TAR_FILE} (${TAR_SIZE})"

    # ═══════════════════════════════════════════════════════════════
    # Step 3: 传输到服务器
    # ═══════════════════════════════════════════════════════════════
    echo ""
    info "Step 3/4: 传输镜像到服务器（${TAR_SIZE}）..."
    
    # 使用 rsync 带进度条传输，支持断点续传
    rsync -avz --progress ${TAR_FILE} ${SERVER_USER}@${SERVER_IP}:/tmp/clawith-images.tar.gz
    
    log "镜像传输完成"

    # 同步 compose 文件和配置（轻量，几秒搞定）
    echo ""
    info "同步配置文件..."
    ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${DEPLOY_DIR}/deploy"
    rsync -avz --progress \
        docker-compose.prod.yml \
        deploy/docker-compose.prebuilt.yml \
        ${SERVER_USER}@${SERVER_IP}:${DEPLOY_DIR}/
    # 把 prebuilt compose 也放到 deploy 子目录
    rsync -avz --progress \
        deploy/ \
        ${SERVER_USER}@${SERVER_IP}:${DEPLOY_DIR}/deploy/
    
    # 同步 backend 的 entrypoint、alembic、seed 等必要文件
    rsync -avz --progress \
        --include='entrypoint.sh' \
        --include='alembic/' \
        --include='alembic/**' \
        --include='alembic.ini' \
        --include='seed.py' \
        --include='agent_template/' \
        --include='agent_template/**' \
        --exclude='*' \
        backend/ \
        ${SERVER_USER}@${SERVER_IP}:${DEPLOY_DIR}/backend/
    
    log "配置同步完成"
fi

# ═══════════════════════════════════════════════════════════════
# Step 4: 在服务器上加载镜像并启动
# ═══════════════════════════════════════════════════════════════
echo ""
info "Step 4/4: 在服务器上加载镜像并启动..."

ssh ${SERVER_USER}@${SERVER_IP} bash << 'REMOTE_SCRIPT'
set -e
DEPLOY_DIR="/opt/clawith"
COMPOSE_FILE="deploy/docker-compose.prebuilt.yml"

echo "  → 加载 Docker 镜像..."
docker load < /tmp/clawith-images.tar.gz
echo "  ✓ 镜像加载完成"

# 清理 tar 文件释放空间
rm -f /tmp/clawith-images.tar.gz

cd ${DEPLOY_DIR}

# 确保 .env 存在
if [ ! -f .env ]; then
    echo "  → 生成 .env..."
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    PG_PASSWORD=$(openssl rand -hex 16)
    cat > .env << EOF
SECRET_KEY=${SECRET_KEY}
JWT_SECRET_KEY=${JWT_SECRET}
POSTGRES_PASSWORD=${PG_PASSWORD}
FRONTEND_PORT=3008
PUBLIC_BASE_URL=http://121.43.250.191:3008
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30
FEISHU_APP_ID=
FEISHU_APP_SECRET=
JINA_API_KEY=
EXA_API_KEY=
EOF
    echo "  ✓ .env 已生成"
fi

# 确保 Docker 已安装
if ! command -v docker &> /dev/null; then
    echo "  → 安装 Docker..."
    curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
    systemctl enable docker && systemctl start docker
fi

# 配置镜像加速（仅 postgres/redis/nginx 等基础镜像需要）
if [ ! -f /etc/docker/daemon.json ] || ! grep -q "registry-mirrors" /etc/docker/daemon.json 2>/dev/null; then
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json << 'DAEMON_EOF'
{
    "registry-mirrors": [
        "https://mirror.ccs.tencentyun.com",
        "https://docker.m.daocloud.io"
    ]
}
DAEMON_EOF
    systemctl daemon-reload && systemctl restart docker
    echo "  ✓ Docker 镜像加速已配置"
fi

echo "  → 启动服务..."
docker compose -f ${COMPOSE_FILE} down 2>/dev/null || true
docker compose -f ${COMPOSE_FILE} up -d

echo "  → 等待服务就绪..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3008/api/health > /dev/null 2>&1; then
        echo "  ✓ 服务已就绪!"
        break
    fi
    sleep 3
    printf "."
done
echo ""

docker compose -f ${COMPOSE_FILE} ps
REMOTE_SCRIPT

echo ""
echo "═══════════════════════════════════════════════════════"
log "部署完成!"
echo ""
echo "  🌐 访问地址:  http://${SERVER_IP}:3008"
echo "  🔧 健康检查:  http://${SERVER_IP}:3008/api/health"
echo ""
echo "  后续更新只需:"
echo "    ./deploy/fast-deploy.sh           # 完整重新构建+部署"
echo "    ./deploy/fast-deploy.sh --no-build # 只传输已有镜像"
echo "    ./deploy/fast-deploy.sh --server-only # 只重启服务"
echo ""
echo "  ⚠️  阿里云安全组需放行: 3008/TCP"
echo "═══════════════════════════════════════════════════════"
