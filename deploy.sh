#!/bin/bash
# 双子星AI量化 · GEMINI AI · VPS 一键部署
# 流程: 清理旧端口进程 → 拉取 GitHub 最新代码 → 构建启动 → 强制自检 → 账户接管
# 全交易所统一逻辑 — TV只发开仓+反转；VPS 挂单/监控/呼吸止损；
# 方向不一致（含重启）→强制全平对齐TV+钉钉；Webhook :6010
# 算仓铁律：合约本金余额×20%风险 ∩ ×5名义 ∩ TV.qty调整
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
echo "  双子星AI量化 · GEMINI AI · VPS 部署"
echo "  RISK20 + 呼吸止损（币安/深币/OKX/Gate 同一逻辑）"
echo "  TV: LONG/SHORT/CLOSE_QUICK_EXIT/CLOSE_RSI_EXIT"
echo "  算仓: 合约本金×20%风险 ∩ ×5名义 ∩ TV.qty调整"
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
if ! docker compose up -d --build; then
  echo ""
  echo ">>> backend 启动失败，最近日志："
  docker compose logs backend --tail 100 2>/dev/null || true
  deploy_fail "docker compose up 失败（常见原因见上方 backend 日志）"
fi

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

# 方向不一致强制平仓 / 暂停交易 关键字（便于运维核对）
if docker compose logs backend 2>/dev/null | grep -qE "FORCE_ALIGN|TRADING_PAUSED|方向不一致"; then
  deploy_info "检测到 FORCE_ALIGN / TRADING_PAUSED 相关日志（已按 TV 方向处理）"
  docker compose logs backend 2>/dev/null | grep -E "FORCE_ALIGN|TRADING_PAUSED|方向不一致" | tail -8
fi

if ! wait_compose_service frontend 60; then
  deploy_fail "frontend 未在 60s 内启动"
fi
deploy_ok "frontend 容器运行中"

# --- 7. 全域自检（内测默认不阻断 WARN）---
echo ""
echo ">>> [6] 生产级全域自检 (PRODUCTION_STRICT=${PRODUCTION_STRICT:-0})"
PRODUCTION_STRICT="${PRODUCTION_STRICT:-0}" bash "$ROOT/production_check.sh" || deploy_fail "全域自检未通过，部署中止"

PUBLIC_IP="$(curl -sf --max-time 5 ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP')"

echo ""
echo "========================================"
echo "  部署成功 · 端口已清理 · 代码已对齐"
echo "  账户接管完成 · 雷达哨兵已就绪"
echo "  系统重启通知已推送管理员钉钉"
echo "  规则: 方向不一致→强制全平对齐 TV · 连续阶梯雷达"
echo "========================================"
echo "  网页内测:  http://${PUBLIC_IP}:${FRONT_PORT}"
echo "  REST API:  http://${PUBLIC_IP}:${API_PORT}/docs"
echo "  Webhook:   http://${PUBLIC_IP}:${WEBHOOK_PORT}/webhook"
echo "  健康检查:  http://${PUBLIC_IP}:${API_PORT}/api/health"
echo ""
echo "  与同机币安/深币共存 (Nginx :80，见 deploy/nginx-vps.conf.example):"
echo "  网页:      http://${PUBLIC_IP}/"
echo "  Webhook:   http://${PUBLIC_IP}/gemini/webhook"
echo "  .env 改为 FRONTEND_URL/API_PUBLIC_URL=http://${PUBLIC_IP} 后重启 backend"
echo ""
echo "  管理员: admin@twinstar.pro"
echo "  查看日志: docker compose logs -f backend"
echo "  接管审计: GET /api/admin/startup-audit"
echo "  钱包中心: 管理后台 → 钱包中心（链上余额 / HD / 冷钱包 / 热钱包）"
echo "  跳过拉码: SKIP_GIT_PULL=1 bash deploy.sh"
echo "  内测自检: bash production_check.sh"
echo "  上线复检: PRODUCTION_STRICT=1 bash production_check.sh"
echo "  Webhook Secret 须与 TV token 一致（管理后台配置，勿硬编码）"
echo "========================================"
