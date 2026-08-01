#!/bin/bash
# 双子星AI量化 · GEMINI AI · VPS 快速巡检
# 用法:
#   bash scripts/selfcheck.sh              # 标准巡检
#   bash scripts/selfcheck.sh --strict     # 有任何问题则 exit 1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=scripts/deploy_lib.sh
source "$SCRIPT_DIR/deploy_lib.sh" 2>/dev/null || true

TV_WEBHOOK_URL="https://twinstar.pro/gemini/webhook"
TV_WEBHOOK_HOST="twinstar.pro"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
fi

FAILURES=0

fail()   { echo -e "${RED}[FAIL]${NC} $1"; FAILURES=$((FAILURES + 1)); }
pass()   { echo -e "${GREEN}[OK]${NC}   $1"; }
info()   { echo -e "${YELLOW}[INFO]${NC} $1"; }
header() { echo ""; echo -e "${CYAN}=== $1 ===${NC}"; }

echo "========================================"
echo "  双子星AI量化 · VPS 快速巡检"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  STRICT=${STRICT}"
echo "========================================"

# ============================================================
# A. TV Webhook 外部连通性（最重要！）
# ============================================================
header "A. TV Webhook 外部连通性"
echo "    目标: $TV_WEBHOOK_URL"

# DNS 解析
echo -n "    DNS 解析 $TV_WEBHOOK_HOST ... "
DNS_IP=$(getent hosts "$TV_WEBHOOK_HOST" 2>/dev/null | awk '{print $1}' | head -1)
if [ -n "$DNS_IP" ]; then
  pass "OK ($DNS_IP)"
else
  fail "DNS 解析失败"
fi

# HTTPS /health 探测
echo -n "    HTTPS :443 握手 ... "
if timeout 8 bash -c "echo > /dev/tcp/$TV_WEBHOOK_HOST/443" 2>/dev/null; then
  pass ":443 开放"
else
  fail ":443 无法连接（防火墙/路由问题）"
fi

# HTTP 响应码
echo -n "    GET /health HTTP 响应 ... "
HTTP_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "000")
HTTP_TIME=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{time_total}" \
  "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "-1")
if [ "$HTTP_CODE" = "200" ]; then
  pass "HTTP $HTTP_CODE (${HTTP_TIME}s)"
elif [ "$HTTP_CODE" = "000" ]; then
  fail "无法连接（网络/DNS/防火墙）"
else
  info "HTTP $HTTP_CODE（可能 /health 路径不同）"
fi

# POST 无 secret 应被拒绝
echo -n "    POST 无 secret 安全检查 ... "
WH_CODE=$(curl -sf --max-time 10 \
  -o /dev/null -w "%{http_code}" \
  -X POST "${TV_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d '{"action":"LONG"}' 2>/dev/null || echo "000")
if [ "$WH_CODE" = "403" ] || [ "$WH_CODE" = "400" ]; then
  pass "无 secret 被正确拒绝 (HTTP $WH_CODE)"
else
  fail "安全检查失败 (HTTP $WH_CODE)，无 secret 请求应被拒绝"
fi

# 端到端延迟
if [ "$HTTP_CODE" = "200" ]; then
  LATENCY_MS=$(echo "$HTTP_TIME * 1000" | bc 2>/dev/null || echo "未知")
  if (( $(echo "$HTTP_TIME < 0.5" | bc -l 2>/dev/null || echo 0) )); then
    pass "延迟 ${LATENCY_MS}ms（正常）"
  else
    info "延迟 ${LATENCY_MS}ms（偏慢，请关注网络质量）"
  fi
fi

# ============================================================
# B. 内部网络连通性
# ============================================================
header "B. 内部网络连通性"

check_ping() {
  local host=$1 label=$2
  echo -n "    ping $label ... "
  if command -v ping >/dev/null 2>&1; then
    if ping -c 2 -W 3 "$host" >/dev/null 2>&1; then
      pass "$host 可达"
    else
      fail "$host 不可达"
    fi
  else
    # 无 ping 命令，尝试 nc
    if nc -z -w 3 "$host" 443 >/dev/null 2>&1; then
      pass "$host :443 可达"
    else
      fail "$host 不可达"
    fi
  fi
}

# 交易所连通性（生产关键）
check_ping "api.binance.com"    "Binance API"
check_ping "www.okx.com"        "OKX"
check_ping "api.gateio.ws"      "Gate.io"
check_ping "api-testnet.bybit.com" "Bybit"

# 国内连通性（VPS 在国内时）
check_ping "www.baidu.com"      "百度（国内连通性）"
check_ping "ntp.aliyun.com"     "阿里云 NTP"

# ============================================================
# C. 核心服务可用性
# ============================================================
header "C. 核心服务可用性"

API_PORT="${API_PORT:-8000}"
WEBHOOK_PORT="${WEBHOOK_PORT:-6010}"
FRONT_PORT="${FRONT_PORT:-6080}"

# Docker 容器状态
echo -n "    Docker 容器状态 ... "
if docker ps --format '{{.Names}}:{{.Status}}' 2>/dev/null | grep -q 'Up'; then
  CONTAINER_COUNT=$(docker ps --format '{{.Names}}' 2>/dev/null | wc -l)
  pass "运行中（${CONTAINER_COUNT} 个容器）"
  docker ps --format '  {{.Names}} · {{.Status}}' 2>/dev/null
else
  fail "Docker 容器未运行"
fi

# Backend 健康检查
echo -n "    backend 健康检查 ... "
BACKEND_HEALTH=$(curl -sf --max-time 5 \
  "http://127.0.0.1:${API_PORT}/api/health" 2>/dev/null || echo "")
if [ -n "$BACKEND_HEALTH" ]; then
  SUPERVISORS=$(echo "$BACKEND_HEALTH" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('active_supervisors',0))" 2>/dev/null || echo "?")
  pass "正常（supervisors=${SUPERVISORS}）"
else
  fail "backend /api/health 不可达"
fi

# Webhook 健康检查
echo -n "    Webhook 健康检查 ... "
WH_HEALTH=$(curl -sf --max-time 5 \
  "http://127.0.0.1:${WEBHOOK_PORT}/health" 2>/dev/null || echo "")
if [ -n "$WH_HEALTH" ]; then
  pass "正常"
else
  fail "Webhook /health 不可达"
fi

# Frontend
echo -n "    Frontend 前端 ... "
FRONT_CODE=$(curl -sf --max-time 5 \
  -o /dev/null -w "%{http_code}" \
  "http://127.0.0.1:${FRONT_PORT}/" 2>/dev/null || echo "000")
if [ "$FRONT_CODE" = "200" ]; then
  pass "正常"
else
  info "HTTP $FRONT_CODE"
fi

# ============================================================
# D. 版本对齐（三方 commit 一致）
# ============================================================
header "D. 版本对齐检查"

LOCAL_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
REMOTE_HEAD=$(git rev-parse --short origin/main 2>/dev/null || echo "?")

echo "    本地 HEAD:     $LOCAL_HEAD"
echo "    origin/main:    $REMOTE_HEAD"

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
  pass "本地与 GitHub 版本一致"
else
  info "本地与 GitHub 版本不一致（VPS 可能需要 git pull）"
  info "执行: cd ~/panda-quant-platform && git pull origin main"
fi

# ============================================================
# E. 运行时关键配置
# ============================================================
header "E. 运行时关键配置"

# 检查 trading_paused
echo -n "    全局交易暂停状态 ... "
PAUSED=$(curl -sf --max-time 5 \
  "http://127.0.0.1:${API_PORT}/api/health" 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trading_paused','unknown'))" 2>/dev/null || echo "unknown")
if [ "$PAUSED" = "false" ] || [ "$PAUSED" = "False" ]; then
  pass "交易正常运行"
elif [ "$PAUSED" = "true" ] || [ "$PAUSED" = "True" ]; then
  fail "交易已全局暂停（trading_paused=true）"
else
  info "trading_paused=$PAUSED"
fi

# Docker 健康检查状态
echo -n "    Docker healthcheck ... "
if docker ps --filter "name=backend" --format '{{.Status}}' 2>/dev/null | grep -q 'healthy'; then
  pass "healthy"
else
  STATUS=$(docker ps --filter "name=backend" --format '{{.Status}}' 2>/dev/null | head -1)
  if [ -n "$STATUS" ]; then
    info "backend status: $STATUS"
  else
    fail "backend 容器未找到"
  fi
fi

# 最近错误日志
echo "    最近 5 分钟日志错误摘要:"
if docker logs --since 5m backend 2>&1 | grep -iE \
  '(error|exception|traceback|fail|critical)' | \
  grep -vE '(\s200\s|\s304\s|GET /health|POST /webhook.*200)' | \
  tail -10 | sed 's/^/      /' || true

# ============================================================
# 汇总
# ============================================================
echo ""
echo "========================================"
if [ "$FAILURES" -gt 0 ]; then
  echo -e "  ${RED}巡检失败 · FAIL=${FAILURES}${NC}"
  echo "  请优先检查 TV Webhook 连通性（A 节）"
  echo "  然后: docker compose logs -f backend --tail=50"
  echo "========================================"
  if [ "$STRICT" -eq 1 ]; then
    exit 1
  fi
else
  echo -e "  ${GREEN}巡检全部通过${NC}"
  echo "  TV Webhook: $TV_WEBHOOK_URL"
  echo "  API:        http://127.0.0.1:${API_PORT}/api/health"
  echo "  Webhook:    http://127.0.0.1:${WEBHOOK_PORT}/health"
  echo "  Frontend:   http://127.0.0.1:${FRONT_PORT}/"
  echo "========================================"
fi
exit 0
