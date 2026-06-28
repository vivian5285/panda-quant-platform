#!/bin/bash
# 熊猫量化 · VPS 一键部署
# 流程: 清理旧端口进程 → 拉取 GitHub 最新代码 → 构建启动 → 强制自检 → 账户接管
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/deploy_lib.sh
source "$ROOT/scripts/deploy_lib.sh"

FRONT_PORT="${FRONT_PORT:-6080}"
API_PORT="${API_PORT:-8000}"
WEBHOOK_PORT="${WEBHOOK_PORT:-6010}"
HEALTH_WAIT="${HEALTH_WAIT:-120}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

echo "========================================"
echo "  熊猫量化平台 · VPS 智能部署"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# --- 0. 依赖 ---
echo ""
echo ">>> [0] 环境依赖"
command -v docker >/dev/null 2>&1 || deploy_fail "未安装 docker"
docker compose version >/dev/null 2>&1 || deploy_fail "未安装 docker compose"
deploy_ok "Docker / Compose 可用"

# --- 1. .env ---
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo ""
  echo "⚠️  已生成 backend/.env，请先编辑以下必改项："
  echo "   SECRET_KEY / ENCRYPTION_KEY / WEBHOOK_SECRET / ADMIN_PASSWORD"
  echo "   FRONTEND_URL=http://你的VPS_IP:${FRONT_PORT}"
  echo "   DINGTALK_WEBHOOK + DINGTALK_SECRET"
  echo ""
  echo "编辑完成后重新运行: bash deploy.sh"
  exit 1
fi
deploy_ok "backend/.env 存在"

# --- 2. 清理旧进程 / 端口 ---
echo ""
echo ">>> [1] 清理旧容器与端口进程 (${FRONT_PORT}/${API_PORT}/${WEBHOOK_PORT})"
clean_platform_ports "$FRONT_PORT" "$API_PORT" "$WEBHOOK_PORT"

# --- 3. GitHub 代码对齐 ---
echo ""
echo ">>> [2] GitHub 代码同步"
if [ "$SKIP_GIT_PULL" = "1" ]; then
  deploy_info "SKIP_GIT_PULL=1，跳过 git pull"
else
  sync_github_code "$ROOT"
fi

# --- 4. 构建启动 ---
echo ""
echo ">>> [3] 构建并启动容器"
docker compose up -d --build

# --- 5. 等待 healthy ---
echo ""
echo ">>> [4] 等待 backend 健康 (${HEALTH_WAIT}s)"
elapsed=0
while [ "$elapsed" -lt "$HEALTH_WAIT" ]; do
  if docker compose ps backend 2>/dev/null | grep -q "(healthy)"; then
    deploy_ok "backend 容器 healthy"
    break
  fi
  if docker compose ps backend 2>/dev/null | grep -q "Exit"; then
    docker compose logs backend --tail 50
    deploy_fail "backend 容器启动失败"
  fi
  sleep 3
  elapsed=$((elapsed + 3))
  echo "  ... 等待中 (${elapsed}s)"
done
if ! docker compose ps backend 2>/dev/null | grep -q "(healthy)"; then
  docker compose logs backend --tail 50
  deploy_fail "backend 未在 ${HEALTH_WAIT}s 内变为 healthy"
fi

# --- 6. 容器内端口 + 账户接管 ---
echo ""
echo ">>> [5] 容器内端口 & 账户接管审计"
docker compose exec -T backend python -c "
import socket, json, urllib.request

for port, name in [(8000,'REST API'), (6010,'Webhook')]:
    s = socket.socket()
    s.settimeout(2)
    ok = s.connect_ex(('127.0.0.1', port)) == 0
    s.close()
    print(f'  [{\"OK\" if ok else \"FAIL\"}] {name} :{port}')
    if not ok:
        raise SystemExit(1)

try:
    with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5) as r:
        h = json.loads(r.read().decode())
    print(f'  [OK] active_supervisors={h.get(\"active_supervisors\",0)}')
    print(f'  [OK] startup_audits={h.get(\"startup_audits\",0)}')
    print(f'  [OK] users_with_position={h.get(\"users_with_position\",0)}')
    print(f'  [OK] dingtalk_configured={h.get(\"dingtalk_configured\")}')
except Exception as e:
    print(f'  [FAIL] health check: {e}')
    raise SystemExit(1)
" || deploy_fail "容器内自检失败"

if docker compose logs backend 2>/dev/null | grep -q "VPS STARTUP"; then
  deploy_ok "账户接管审计日志已生成"
  docker compose logs backend 2>/dev/null | grep "VPS STARTUP" | tail -5
else
  deploy_info "暂无 VPS STARTUP 日志（可能尚无绑定 API 的用户）"
fi

if docker compose ps frontend 2>/dev/null | grep -q "Up"; then
  deploy_ok "frontend 容器运行中"
else
  deploy_fail "frontend 容器未运行"
fi

# --- 7. 强制全域自检 ---
echo ""
echo ">>> [6] 强制生产级全域自检"
bash "$ROOT/production_check.sh" || deploy_fail "全域自检未通过，部署中止"

PUBLIC_IP="$(curl -sf --max-time 5 ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP')"

echo ""
echo "========================================"
echo "  部署成功 · 端口已清理 · 代码已对齐"
echo "  账户接管完成 · 雷达哨兵已就绪"
echo "  系统重启通知已推送管理员钉钉"
echo "========================================"
echo "  网页内测:  http://${PUBLIC_IP}:${FRONT_PORT}"
echo "  REST API:  http://${PUBLIC_IP}:${API_PORT}/docs"
echo "  Webhook:   http://${PUBLIC_IP}:${WEBHOOK_PORT}/webhook"
echo "  健康检查:  http://${PUBLIC_IP}:${API_PORT}/api/health"
echo ""
echo "  管理员: admin@pandaquant.com"
echo "  查看日志: docker compose logs -f backend"
echo "  接管审计: GET /api/admin/startup-audit"
echo "  跳过拉码: SKIP_GIT_PULL=1 bash deploy.sh"
echo "  复检命令: bash production_check.sh"
echo "========================================"
