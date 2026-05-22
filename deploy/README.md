# Clawith 部署指南

## 一键 Docker 部署到服务器

### 前提条件
- 本地已配置 SSH 免密登录到目标服务器
- 目标服务器: Ubuntu 20.04+ / CentOS 7+
- 阿里云安全组已放行端口 3008

### 部署步骤

```bash
# 方式一：从本地推送部署（推荐）
chmod +x deploy/docker-deploy.sh
./deploy/docker-deploy.sh

# 方式二：在服务器上直接部署
# 先将代码传到服务器 /opt/clawith/
cd /opt/clawith
chmod +x deploy/docker-deploy.sh
./deploy/docker-deploy.sh --local
```

### 部署完成后

- 访问地址: `http://121.43.250.191:3008`
- 后端 API: `http://121.43.250.191:8000/api/health`
- 深度检查: `http://121.43.250.191:8000/api/health/deep`

### 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f
docker compose logs -f backend
docker compose logs -f frontend

# 重启服务
docker compose restart

# 更新部署
git pull
docker compose up -d --build

# 停止服务
docker compose down

# 清理数据（危险！会删除所有数据）
docker compose down -v
```

### 配置说明

部署脚本会自动生成 `.env` 文件，包含随机生成的密钥。如需修改配置：

```bash
vim /opt/clawith/.env
docker compose restart
```

关键配置项：
- `SECRET_KEY` — 数据加密密钥（自动生成）
- `JWT_SECRET_KEY` — JWT 签名密钥（自动生成）
- `PUBLIC_BASE_URL` — 公网访问地址
- `FRONTEND_PORT` — 前端端口（默认 3008）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` — 飞书 SSO（可选）

### 使用域名

如果有域名，修改 `.env`：
```
PUBLIC_BASE_URL=https://your-domain.com
```

然后配置 Nginx 反向代理或使用 Cloudflare。

### 阿里云安全组

确保以下端口已放行：
- **3008** (TCP) — 前端访问
- **22** (TCP) — SSH 管理
