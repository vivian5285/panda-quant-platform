#!/bin/bash
# 双子星AI量化 · GEMINI AI · 生产级全域自检
# PRODUCTION_STRICT=1 时：WARN / production_ready=false 也视为失败（正式上线前跑）
# 默认 PRODUCTION_STRICT=0：仅 FAIL 硬错误，配置类 WARN 不阻断 deploy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/deploy_lib.sh
source "$ROOT/scripts/deploy_lib.sh"

FRONT_PORT="${FRONT_PORT:-6080}"
API_PORT="${API_PORT:-8000}"
WEBHOOK_PORT="${WEBHOOK_PORT:-6010}"
PRODUCTION_STRICT="${PRODUCTION_STRICT:-0}"

FAILURES=0
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }
ok()   { echo "[OK]   $1"; }
warn() { echo "[WARN] $1"; }

echo "========================================"
echo "  双子星AI量化 · GEMINI AI · 生产级全域自检"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  PRODUCTION_STRICT=${PRODUCTION_STRICT}"
echo "========================================"

# --- A. Docker ---
echo ""
echo ">>> [A] Docker 容器状态"
command -v docker >/dev/null 2>&1 || { fail "docker 未安装"; echo "FAIL=$FAILURES"; exit 1; }

docker compose ps || true

deploy_info "等待 frontend 就绪 (最多 60s)..."
wait_compose_service frontend 60 || deploy_info "frontend 仍在启动，继续检查..."

for svc in backend frontend; do
  if docker compose ps "$svc" 2>/dev/null | grep -qE 'Up|\(healthy\)'; then
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

# --- B1. 宿主机端口 ---
echo ""
echo ">>> [B1] 宿主机端口监听"
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

# --- B2. TV Webhook 连通性 + 内网/外网可达性 ---
echo ""
echo ">>> [B2] TV Webhook 外网连通性"

TV_WEBHOOK_URL="https://twinstar.pro/gemini/webhook"
TV_WEBHOOK_HOST="twinstar.pro"

# DNS 解析
echo -n "    DNS 解析 $TV_WEBHOOK_HOST ... "
DNS_RESULT=$(getent hosts "$TV_WEBHOOK_HOST" 2>/dev/null | awk '{print $1" "$2}' | head -1)
if [ -n "$DNS_RESULT" ]; then
  ok "DNS OK (${DNS_RESULT})"
else
  fail "DNS 解析失败"
fi

# TCP :443 握手
echo -n "    TCP :443 握手 ... "
if timeout 8 bash -c "echo > /dev/tcp/${TV_WEBHOOK_HOST}/443" 2>/dev/null; then
  ok ":443 端口开放"
else
  fail ":443 端口无法连接"
fi

# HTTPS /health HTTP 响应
echo -n "    HTTPS GET /health ... "
TV_HEALTH_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "000")
TV_HEALTH_TIME=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{time_total}" \
  "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "-1")
if [ "$TV_HEALTH_CODE" = "200" ]; then
  ok "TV Webhook HTTP $TV_HEALTH_CODE (${TV_HEALTH_TIME}s)"
elif [ "$TV_HEALTH_CODE" = "000" ]; then
  fail "TV Webhook 无法连接（网络/DNS/防火墙）"
else
  warn "TV Webhook HTTP $TV_HEALTH_CODE"
fi

# POST 无 secret 安全检查
echo -n "    POST 无 secret 安全检查 ... "
TV_WH_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  -X POST "${TV_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d '{"action":"LONG"}' 2>/dev/null || echo "000")
if [ "$TV_WH_CODE" = "403" ] || [ "$TV_WH_CODE" = "400" ]; then
  ok "TV Webhook 无 secret 被拒绝 (HTTP $TV_WH_CODE)"
else
  fail "TV Webhook 安全检查失败 (HTTP $TV_WH_CODE)"
fi

# --- B3. 内网/外网可达性 ---
echo ""
echo ">>> [B3] 内网/外网可达性"

check_connectivity() {
  local host=$1 port=$2 label=$3
  echo -n "    $label ($host) ... "
  if timeout 5 bash -c "echo > /dev/tcp/${host}/${port}" 2>/dev/null; then
    ok "可达"
  else
    fail "不可达"
  fi
}

check_connectivity "api.binance.com"   443 "Binance API"
check_connectivity "www.okx.com"       443 "OKX"
check_connectivity "api.gateio.ws"     443 "Gate.io"
check_connectivity "api.github.com"    443 "GitHub"
check_connectivity "ntp.aliyun.com"    123 "阿里云 NTP"
check_connectivity "8.8.8.8"           53  "Google DNS（外网测试）"
check_connectivity "114.114.114.114"   53  "国内 DNS"

# --- C. 后端 Python 全域自检 ---
echo ""
if [ "$PRODUCTION_STRICT" = "1" ]; then
  echo ">>> [C] 后端模块自检 (check_system.py --strict --network)"
  CHECK_ARGS="--strict --network"
else
  echo ">>> [C] 后端模块自检 (check_system.py，WARN 不阻断；--network 查 TV webhook)"
  CHECK_ARGS="--network"
fi
if docker compose ps backend 2>/dev/null | grep -qE 'Up|\(healthy\)'; then
  if docker compose exec -T backend python scripts/check_system.py $CHECK_ARGS; then
    ok "check_system.py 通过"
  else
    fail "check_system.py 未通过"
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
" && ok "/api/health production_ready=true" || {
    if [ "$PRODUCTION_STRICT" = "1" ]; then
      fail "/api/health production_ready=false（正式上线前请修复 security_warnings）"
    else
      warn "/api/health production_ready=false（内测可忽略，上线前设 PRODUCTION_STRICT=1 复检）"
    fi
  }
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

# OpenAPI 文档（PRODUCTION_STRICT=1 时 /docs 已关闭，属预期）
DOCS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${API_PORT}/docs" 2>/dev/null || echo "000")
if [ "$DOCS_CODE" = "200" ]; then
  ok "REST API /docs 可访问"
elif [ "$DOCS_CODE" = "404" ] || [ "$DOCS_CODE" = "000" ]; then
  if [ "$PRODUCTION_STRICT" = "1" ]; then
    ok "REST API /docs 已关闭（PRODUCTION_STRICT 生产模式）"
  else
    warn "REST API /docs 不可访问 (HTTP ${DOCS_CODE})"
  fi
else
  fail "REST API /docs 异常 (HTTP ${DOCS_CODE})"
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

# --- F. 前端 & 官网静态路由 ---
echo ""
echo ">>> [F] 前端 SPA & 官网路由"
for path in "/" "/login" "/register" "/help" "/privacy" "/terms"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${FRONT_PORT}${path}" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ]; then
    ok "前端 ${path} HTTP 200"
  else
    fail "前端 ${path} 不可访问 (HTTP ${CODE})"
  fi
done

LANDING=$(curl -sf --max-time 5 "http://127.0.0.1:${FRONT_PORT}/" 2>/dev/null || echo "")
if echo "$LANDING" | grep -qiE 'GEMINI|双子星|root'; then
  ok "官网首页 HTML 正常"
else
  warn "官网首页内容未检测到 GEMINI/双子星 标识"
fi

# --- G. TV Webhook 端到端连通性（生产关键）---
echo ""
echo ">>> [G] TV Webhook 端到端连通性"
echo "    生产地址: https://twinstar.pro/gemini/webhook"

# DNS 解析
echo -n "    DNS 解析 twinstar.pro ... "
DNS_RESULT=$(getent hosts "twinstar.pro" 2>/dev/null | awk '{print $1" "$2}' | head -1)
if [ -n "$DNS_RESULT" ]; then
  ok "DNS OK (${DNS_RESULT})"
else
  fail "DNS 解析失败"
fi

# TCP :443 握手
echo -n "    TCP :443 握手 ... "
if timeout 8 bash -c "echo > /dev/tcp/twinstar.pro/443" 2>/dev/null; then
  ok ":443 开放"
else
  fail ":443 无法连接（检查防火墙/路由）"
fi

# HTTPS GET /health
echo -n "    HTTPS GET /health ... "
TV_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  "https://twinstar.pro/gemini/webhook/health" 2>/dev/null || echo "000")
TV_TIME=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{time_total}" \
  "https://twinstar.pro/gemini/webhook/health" 2>/dev/null || echo "-1")
if [ "$TV_CODE" = "200" ]; then
  ok "HTTP $TV_CODE (${TV_TIME}s)"
elif [ "$TV_CODE" = "000" ]; then
  fail "无法连接 twinstar.pro（VPS 外网/防火墙问题）"
else
  warn "HTTP $TV_CODE"
fi

# POST 无 secret 应拒绝
echo -n "    POST 无 secret 安全检查 ... "
TV_WH_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  -X POST "https://twinstar.pro/gemini/webhook" \
  -H "Content-Type: application/json" \
  -d '{"action":"LONG"}' 2>/dev/null || echo "000")
if [ "$TV_WH_CODE" = "403" ] || [ "$TV_WH_CODE" = "400" ]; then
  ok "安全检查通过 (HTTP $TV_WH_CODE)"
else
  fail "安全检查失败 (HTTP $TV_WH_CODE)"
fi

# 交易所连通性
echo ""
echo ">>> [H] 交易所网络连通性"
for host in "api.binance.com:443:Binance" "www.okx.com:443:OKX" "api.gateio.ws:443:Gate.io"; do
  IFS=':' read -r h p label <<< "$host"
  echo -n "    $label ($h) ... "
  if timeout 5 bash -c "echo > /dev/tcp/${h}/${p}" 2>/dev/null; then
    ok "可达"
  else
    fail "不可达"
  fi
done

# --- 汇总 ---
echo ""
echo "========================================"
if [ "$FAILURES" -gt 0 ]; then
  echo "  自检失败 · FAIL=${FAILURES}"
  echo "  请修复上述 [FAIL] 项后重跑: bash production_check.sh"
  echo "  正式上线前: PRODUCTION_STRICT=1 bash production_check.sh"
  echo "========================================"
  exit 1
fi

PUBLIC_IP="$(curl -sf --max-time 5 ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP')"
echo "  自检全部通过 (strict=${PRODUCTION_STRICT})"
echo "  TV Webhook:  https://twinstar.pro/gemini/webhook"
echo "  网页:        http://${PUBLIC_IP}:${FRONT_PORT}"
echo "  Webhook:     http://${PUBLIC_IP}:${WEBHOOK_PORT}/webhook"
echo "  健康:        http://${PUBLIC_IP}:${API_PORT}/api/health"
if [ "$PRODUCTION_STRICT" != "1" ]; then
  echo "  提示: 正式上线前执行 PRODUCTION_STRICT=1 bash production_check.sh"
fi
echo "  快速巡检:   bash scripts/selfcheck.sh"
echo "========================================"
exit 0
