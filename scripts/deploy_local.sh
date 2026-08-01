#!/bin/bash
# 双子星AI量化 · GEMINI AI · VPS 本地快速部署
# 用法（VPS ssh 后执行）:
#   cd ~/panda-quant-platform
#   bash scripts/deploy_local.sh
#
# 前提: 代码已 git pull 到本地，backend/.env 已存在
# 推送到 GitHub 后，在 VPS 上执行此脚本拉取并部署
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=scripts/deploy_lib.sh
source "$SCRIPT_DIR/deploy_lib.sh" 2>/dev/null || true

FRONT_PORT="${FRONT_PORT:-6080}"
API_PORT="${API_PORT:-8000}"
WEBHOOK_PORT="${WEBHOOK_PORT:-6010}"
HEALTH_WAIT="${HEALTH_WAIT:-120}"
SKIP_BUILD="${SKIP_BUILD:-0}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "========================================"
echo "  双子星AI量化 · VPS 本地快速部署"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  ROOT: $ROOT_DIR"
echo "========================================"

# --- 0. 前置确认 ---
echo ""
echo ">>> [0] 前置检查"

if [ ! -f backend/.env ]; then
  fail "backend/.env 不存在，请先配置环境变量"
fi
ok "backend/.env 存在"

if [ ! -d .git ]; then
  fail "当前目录不是 git 仓库"
fi
ok "Git 仓库正常"

LOCAL_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
REMOTE_HEAD=$(git rev-parse --short origin/main 2>/dev/null || echo "?")

echo "    本地 HEAD:     $LOCAL_HEAD"
echo "    origin/main:    $REMOTE_HEAD"

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
  info "版本已对齐，无需 pull"
else
  echo "    版本不一致，执行 git pull ..."
  git pull origin main
  ok "git pull 完成 ($(git rev-parse --short HEAD))"
fi

# --- 1. Docker 检查 ---
echo ""
echo ">>> [1] Docker 检查"
command -v docker >/dev/null 2>&1 || fail "Docker 未安装"
docker info >/dev/null 2>&1 || fail "Docker daemon 未运行（请 sudo systemctl start docker）"
ok "Docker 可用"

# --- 2. 构建 ---
echo ""
echo ">>> [2] 构建镜像"
if [ "$SKIP_BUILD" = "1" ]; then
  info "SKIP_BUILD=1，跳过构建"
else
  if ! docker compose build backend; then
    echo ""
    echo ">>> 构建失败，日志:"
    docker compose logs backend --tail 30
    fail "docker compose build 失败"
  fi
  ok "backend 镜像构建完成"
fi

# --- 3. 启动 ---
echo ""
echo ">>> [3] 启动容器"
if ! docker compose up -d backend; then
  fail "docker compose up -d 失败"
fi
ok "容器已启动"

# --- 4. 等待健康 ---
echo ""
echo ">>> [4] 等待 backend 健康 (${HEALTH_WAIT}s)"
elapsed=0
while [ "$elapsed" -lt "$HEALTH_WAIT" ]; do
  if docker compose ps backend 2>/dev/null | grep -q "(healthy)"; then
    ok "backend 健康检查通过"
    break
  fi
  if docker compose ps backend 2>/dev/null | grep -q "Exit"; then
    docker compose logs backend --tail 30
    fail "backend 容器退出"
  fi
  sleep 3
  elapsed=$((elapsed + 3))
  echo "  ... 等待中 (${elapsed}s)"
done

if ! docker compose ps backend 2>/dev/null | grep -q "(healthy)"; then
  docker compose logs backend --tail 30
  fail "backend 未在 ${HEALTH_WAIT}s 内变为 healthy"
fi

# --- 5. 健康检查 ---
echo ""
echo ">>> [5] 健康检查"

API_HEALTH=$(curl -sf --max-time 5 "http://127.0.0.1:${API_PORT}/api/health" 2>/dev/null || echo "")
if [ -n "$API_HEALTH" ]; then
  STATUS=$(echo "$API_HEALTH" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('status','?')), d.get('active_supervisors',0), d.get('startup_audits',0)" 2>/dev/null || echo "?")
  ok "/api/health 正常 ($STATUS)"
else
  fail "/api/health 不可达"
fi

WH_HEALTH=$(curl -sf --max-time 5 "http://127.0.0.1:${WEBHOOK_PORT}/health" 2>/dev/null || echo "")
if [ -n "$WH_HEALTH" ]; then
  ok "Webhook /health 正常"
else
  fail "Webhook /health 不可达"
fi

# --- 6. 启动接管日志 ---
echo ""
echo ">>> [6] 账户接管状态"
if docker compose logs backend 2>/dev/null | grep -q "VPS STARTUP"; then
  ok "VPS STARTUP 审计日志已生成"
  docker compose logs backend 2>/dev/null | grep "VPS STARTUP" | tail -3
else
  info "暂无 VPS STARTUP（无绑定用户时正常）"
fi

# --- 7. 快速自检 ---
echo ""
echo ">>> [7] TV Webhook 连通性（生产关键）"
TV_HOST="twinstar.pro"
TV_URL="https://twinstar.pro/gemini/webhook"

echo -n "    DNS 解析 ... "
if getent hosts "$TV_HOST" >/dev/null 2>&1; then
  IP=$(getent hosts "$TV_HOST" | awk '{print $1}' | head -1)
  ok "$TV_HOST → $IP"
else
  fail "DNS 解析失败"
fi

echo -n "    HTTPS GET /health ... "
TV_CODE=$(curl -sf --max-time 10 -o /dev/null -w "%{http_code}" \
  "${TV_URL}/health" 2>/dev/null || echo "000")
if [ "$TV_CODE" = "200" ]; then
  ok "HTTP $TV_CODE"
else
  fail "HTTP $TV_CODE（VPS 无法访问 twinstar.pro）"
fi

# --- 8. 显示服务地址 ---
PUBLIC_IP="$(curl -sf --max-time 5 ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP')"

echo ""
echo "========================================"
ok "部署成功！"
echo "  TV Webhook:  https://twinstar.pro/gemini/webhook"
echo "  REST API:    http://${PUBLIC_IP}:${API_PORT}/docs"
echo "  Webhook:     http://${PUBLIC_IP}:${WEBHOOK_PORT}/webhook"
echo "  健康检查:    http://${PUBLIC_IP}:${API_PORT}/api/health"
echo "  前端:        http://${PUBLIC_IP}:${FRONT_PORT}/"
echo ""
echo "  查看日志:    docker compose logs -f backend"
echo "  完整自检:   bash production_check.sh"
echo "  快速巡检:   bash scripts/selfcheck.sh"
echo "========================================"
