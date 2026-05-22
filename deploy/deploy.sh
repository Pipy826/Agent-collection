#!/bin/bash
# Clawith Production Deployment Script
# Usage: ./deploy/deploy.sh [--skip-build] [--skip-migrate]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

SKIP_BUILD=false
SKIP_MIGRATE=false

for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --skip-migrate) SKIP_MIGRATE=true ;;
    esac
done

echo "═══════════════════════════════════════"
echo "  Clawith Deployment"
echo "═══════════════════════════════════════"

# 1. Check environment
echo ""
echo "▶ Checking environment..."
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "  ✗ .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Verify critical env vars
source "$PROJECT_ROOT/.env"
if [ "$SECRET_KEY" = "change-me-in-production" ] || [ -z "$SECRET_KEY" ]; then
    echo "  ✗ SECRET_KEY is not set. Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi
if [ "$JWT_SECRET_KEY" = "change-me-jwt-secret" ] || [ -z "$JWT_SECRET_KEY" ]; then
    echo "  ✗ JWT_SECRET_KEY is not set."
    exit 1
fi
echo "  ✓ Environment configured"

# 2. Install backend dependencies
echo ""
echo "▶ Installing backend dependencies..."
cd "$PROJECT_ROOT/backend"
pip install -e . --quiet 2>/dev/null
echo "  ✓ Backend dependencies installed"

# 3. Database migration
if [ "$SKIP_MIGRATE" = false ]; then
    echo ""
    echo "▶ Running database migrations..."
    cd "$PROJECT_ROOT/backend"
    alembic upgrade head
    echo "  ✓ Database migrated"

    echo ""
    echo "▶ Seeding initial data..."
    python seed.py
    echo "  ✓ Seed data applied"
fi

# 4. Frontend build
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "▶ Building frontend..."
    cd "$PROJECT_ROOT/frontend"
    npm ci --quiet 2>/dev/null
    npm run build
    echo "  ✓ Frontend built → frontend/dist/"
fi

# 5. Start/restart backend
echo ""
echo "▶ Starting backend..."
cd "$PROJECT_ROOT/backend"

# Stop existing process if running
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 2

# Start with production settings
nohup python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8009 \
    --workers 4 \
    --log-level info \
    > /var/log/clawith/backend.log 2>&1 &

echo "  ✓ Backend started (PID: $!)"

# 6. Summary
echo ""
echo "═══════════════════════════════════════"
echo "  ✓ Deployment complete!"
echo ""
echo "  Backend:  http://0.0.0.0:8009"
echo "  Frontend: Serve frontend/dist/ via Nginx"
echo "  Health:   curl http://localhost:8009/api/health/deep"
echo ""
echo "  Next steps:"
echo "  1. Configure Nginx (see deploy/nginx.conf)"
echo "  2. Set up SSL with certbot"
echo "  3. Configure systemd service for auto-restart"
echo "═══════════════════════════════════════"
