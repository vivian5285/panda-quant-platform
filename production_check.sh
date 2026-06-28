#!/bin/bash
# 熊猫量化 · 生产级全域自检（部署后必跑，任一 FAIL 则 exit 1）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

FRONT_PORT="${FRONT_PORT:-6080}"
API_PORT="${API_PORT:-8000}"
WEBHOOK_PORT="${WEBHOOK_PORT:-6010}"

FAILURES=0
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "[OK]   $1"; }
warn() { echo "[WARN] $1"; }

echo "========================================"
echo "  熊猫量化 · 生产级全域自检"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# --- A. Docker ---
echo ""
echo ">>> [A] Docker 容器状态"
command -v docker >/dev/null 2>&1 || { fail "docker 未安装"; echo "FAIL=$FAILURES"; exit 1; }

docker compose ps || true

for svc in backend frontend; do
  if docker compose ps --status running 2>/dev/null | grep -q "$svc"; then
    ok "$svc 容器运行中"
  else
    fail "$svc 容器未运行"
  fi
done

if docker compose ps backend 2>/dev/null | grep -q "(healthy)"; then
  ok "backend healthcheck = healthy"
else
  fail "backend 未通过 Docker healthcheck"
fi

# --- B. 宿主机端口 ---
echo ""
echo ">>> [B] 宿主机端口监听"
check_host_port() {
  local port=$1 name=$2
  if curl -sf --max-time 3 "http://127.0.0.1:${port}/" >/dev/null 2>&1 || \
     curl -sf --max-time 3 "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1 || \
     curl -sf --max-time 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    ok "${name} :${port} 可访问"
  else
    fail "${name} :${port} 不可访问"
  fi
}

check_host_port "$API_PORT" "REST API"
check_host_port "$WEBHOOK_PORT" "Webhook"
check_host_port "$FRONT_PORT" "前端"

# --- C. 后端 Python 全域自检 ---
echo ""
echo ">>> [C] 后端模块自检 (check_system.py --strict)"
if docker compose ps --status running 2>/dev/null | grep -q backend; then
  if docker compose exec -T backend python scripts/check_system.py --strict; then
    ok "check_system.py --strict 通过"
  else
    fail "check_system.py --strict 未通过"
  fi
else
  fail "backend 未运行，跳过 Python 自检"
fi

# --- D. 功能模块 HTTP 探测 ---
echo ""
echo ">>> [D] 功能模块 HTTP 探测"

HEALTH=$(curl -sf --max-time 5 "http://127.0.0.1:${API_PORT}/api/health" 2>/dev/null || echo "")
if [ -n "$HEALTH" ]; then
  echo "$HEALTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('status') == 'ok', 'status != ok'
print(f\"  production_ready={d.get('production_ready')}\")
print(f\"  dingtalk_configured={d.get('dingtalk_configured')}\")
print(f\"  active_supervisors={d.get('active_supervisors')}\")
print(f\"  security_warnings={d.get('security_warnings')}\")
if not d.get('production_ready'):
    sys.exit(2)
" && ok "/api/health production_ready=true" || fail "/api/health production_ready=false 或响应异常"
else
  fail "无法读取 /api/health"
fi

WH=$(curl -sf --max-time 5 "http://127.0.0.1:${WEBHOOK_PORT}/health" 2>/dev/null || echo "")
if echo "$WH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok'" 2>/dev/null; then
  ok "Webhook /health 正常"
else
  fail "Webhook /health 异常"
fi

# Webhook 安全：无 secret 应拒绝
WH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  -X POST "http://127.0.0.1:${WEBHOOK_PORT}/webhook" \
  -H "Content-Type: application/json" -d '{"action":"LONG"}' 2>/dev/null || echo "000")
if [ "$WH_CODE" = "403" ] || [ "$WH_CODE" = "400" ]; then
  ok "Webhook 无 secret 请求被拒绝 (HTTP ${WH_CODE})"
else
  fail "Webhook 安全拒绝测试失败 (HTTP ${WH_CODE})"
fi

# OpenAPI 文档
if curl -sf --max-time 5 "http://127.0.0.1:${API_PORT}/docs" >/dev/null 2>&1; then
  ok "REST API /docs 可访问"
else
  fail "REST API /docs 不可访问"
fi

# --- E. VPS 账户接管审计 ---
echo ""
echo ">>> [E] VPS 账户接管 & 雷达就绪"
if [ -n "$HEALTH" ]; then
  echo "$HEALTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
audits = d.get('startup_audits', 0)
supervisors = d.get('active_supervisors', 0)
positions = d.get('users_with_position', 0)
failures = d.get('startup_failures', 0)
print(f'  supervisors={supervisors} audits={audits} positions={positions} failures={failures}')
if failures > 0:
    sys.exit(3)
" && ok "账户接管完成 · 无加载失败" || {
    code=$?
    if [ "$code" -eq 3 ]; then
      fail "部分用户 Supervisor 加载失败 (startup_failures>0)"
    else
      fail "health 接管数据解析失败"
    fi
  }
else
  fail "无法验证账户接管状态"
fi

if docker compose logs backend 2>/dev/null | grep -q "VPS STARTUP"; then
  ok "发现 [VPS STARTUP] 审计日志"
  docker compose logs backend 2>/dev/null | grep "VPS STARTUP" | tail -3
else
  warn "未发现 [VPS STARTUP]（无 API 用户时正常）"
fi

if docker compose logs backend 2>/dev/null | grep -q "SystemAlert.*SYSTEM_RESTART"; then
  ok "系统重启钉钉通知已触发"
else
  warn "未发现 SYSTEM_RESTART 日志（检查 DINGTALK_WEBHOOK 配置）"
fi

# --- 汇总 ---
echo ""
echo "========================================"
if [ "$FAILURES" -gt 0 ]; then
  echo "  自检失败 · FAIL=${FAILURES}"
  echo "  请修复上述 [FAIL] 项后重跑: bash production_check.sh"
  echo "========================================"
  exit 1
fi

PUBLIC_IP="$(curl -sf --max-time 5 ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP')"
echo "  自检全部通过"
echo "  网页:    http://${PUBLIC_IP}:${FRONT_PORT}"
echo "  Webhook: http://${PUBLIC_IP}:${WEBHOOK_PORT}/webhook"
echo "  健康:    http://${PUBLIC_IP}:${API_PORT}/api/health"
echo "========================================"
exit 0
