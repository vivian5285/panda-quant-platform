#!/bin/bash
# 双子星AI量化 · GEMINI AI · 推送前本地自检 + GitHub 推送
# 用法: bash _push_github.sh
# 自检通过后才推送到 GitHub main 分支

set -euo pipefail

# 自动检测 repo root（兼容 Windows Git Bash / Linux / macOS）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"
BACKEND_DIR="$REPO_ROOT/backend"

TV_WEBHOOK_URL="https://twinstar.pro/gemini/webhook"
TV_WEBHOOK_HOST="twinstar.pro"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

fail()   { echo -e "${RED}[FAIL]${NC} $1"; }
pass()   { echo -e "${GREEN}[OK]${NC}   $1"; }
info()   { echo -e "${YELLOW}[INFO]${NC} $1"; }
ask()    { echo -ne "${YELLOW}[ASK]${NC} $1 "; }

FAILURES=0

echo "========================================"
echo "  双子星AI量化 · 推送前本地自检"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# ============================================================
# 0. 前置检查：git 状态
# ============================================================
echo ""
echo ">>> [0] Git 仓库状态"

cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  fail "当前目录不是 git 仓库: $REPO_ROOT"
  exit 1
fi
pass "Git 仓库正常 ($(git rev-parse --abbrev-ref HEAD))"

# 检查是否有未提交的变更
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
  CHANGES=$(git diff-index --name-only HEAD -- 2>/dev/null | wc -l | tr -d ' ')
  STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
  UNSTAGED=$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')

  echo ""
  echo "⚠️  检测到 $CHANGES 个文件有变更（未提交）:"
  git diff-index --name-only HEAD -- 2>/dev/null | head -20 | while read -r f; do
    echo "   - $f"
  done
  if [ "$CHANGES" -gt 20 ]; then
    echo "   ... 共 $CHANGES 个文件"
  fi

  if [ "$STAGED" -gt 0 ]; then
    echo "   已暂存: $STAGED 个文件"
  fi
  if [ "$UNSTAGED" -gt 0 ]; then
    echo "   未暂存: $UNSTAGED 个文件"
  fi

  echo ""
  ask "有未提交变更，继续推送（仅推已提交内容）？[y/N]: "
  read -r response
  if [[ ! "$response" =~ ^[Yy]$ ]]; then
    echo "已取消推送。"
    exit 1
  fi
else
  pass "工作区干净（无未提交变更）"
fi

# ============================================================
# 1. Python 语法检查（核心模块）
# ============================================================
echo ""
echo ">>> [1] Python 语法检查（核心模块）"

PYTHON_CMD=""
for cmd in python3 python py; do
  if command -v "$cmd" >/dev/null 2>&1; then
    PYTHON_CMD="$cmd"
    break
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  info "未找到 Python，跳过语法检查（请确保代码编辑器已完成检查）"
else
  PYTHON_VERSION=$("$PYTHON_CMD" --version 2>&1 | tr -d '\n')
  info "使用 $PYTHON_VERSION"

  CORE_MODULES=(
    "$BACKEND_DIR/app/core/position_supervisor.py"
    "$BACKEND_DIR/app/core/breathing_stop.py"
    "$BACKEND_DIR/app/core/adverse_radar_guard.py"
    "$BACKEND_DIR/app/core/trend_tier_params.py"
    "$BACKEND_DIR/app/core/startup_reconcile.py"
    "$BACKEND_DIR/app/core/trade_ledger.py"
    "$BACKEND_DIR/app/core/rest_throttle_valve.py"
    "$BACKEND_DIR/app/core/smart_reentry.py"
    "$BACKEND_DIR/app/core/order_place_guard.py"
    "$BACKEND_DIR/app/services/dispatcher.py"
    "$BACKEND_DIR/app/services/webhook_guard.py"
  )

  SYNTAX_OK=0
  for mod in "${CORE_MODULES[@]}"; do
    if [ -f "$mod" ]; then
      MOD_NAME="${mod#$BACKEND_DIR/}"
      # -m py_compile 会静默失败（有语法错误返回非0）
      if "$PYTHON_CMD" -m py_compile "$mod" 2>/dev/null; then
        # 静默，只统计
        SYNTAX_OK=$((SYNTAX_OK + 1))
      else
        fail "$MOD_NAME 语法错误"
        # 重新显示错误
        "$PYTHON_CMD" -m py_compile "$mod" 2>&1 | head -5 | sed 's/^/       /' || true
        FAILURES=$((FAILURES + 1))
      fi
    fi
  done

  if [ "$SYNTAX_OK" -gt 0 ]; then
    pass "已检查 ${SYNTAX_OK} 个核心模块，语法全部通过"
  fi
fi

# ============================================================
# 2. TV Webhook 连通性检查（外网可达性）
# ============================================================
echo ""
echo ">>> [2] TV Webhook 外网连通性检查"
echo "    目标: $TV_WEBHOOK_URL"

TV_CHECK_CMD=""
for cmd in curl wget; do
  if command -v "$cmd" >/dev/null 2>&1; then
    TV_CHECK_CMD="$cmd"
    break
  fi
done

if [ -z "$TV_CHECK_CMD" ]; then
  info "未找到 curl/wget，跳过 TV webhook 检查"
else
  # DNS 解析
  echo -n "    DNS 解析 $TV_WEBHOOK_HOST ... "
  if command -v nslookup >/dev/null 2>&1; then
    DNS_RESULT=$(nslookup "$TV_WEBHOOK_HOST" 2>&1 | grep -E 'Name:|Address:' | tail -2 | tr '\n' ' ' | sed 's/  */ /g')
  elif command -v dig >/dev/null 2>&1; then
    DNS_RESULT=$(dig +short "$TV_WEBHOOK_HOST" 2>/dev/null | head -1)
  else
    DNS_RESULT="(未检测)"
  fi

  if [ -n "$DNS_RESULT" ]; then
    if echo "$DNS_RESULT" | grep -qvE '(no|serv|can''t|not found|timeout|error)' 2>/dev/null; then
      pass "DNS OK: $DNS_RESULT"
    else
      fail "DNS 失败: $DNS_RESULT"
      FAILURES=$((FAILURES + 1))
    fi
  else
    info "DNS: $DNS_RESULT"
  fi

  # HTTP 连通性
  echo -n "    HTTP GET /health ... "
  if [ "$TV_CHECK_CMD" = "curl" ]; then
    HTTP_CODE=$(curl -sf --max-time 8 -o /dev/null -w "%{http_code}" \
      "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "000")
    HTTP_TIME=$(curl -sf --max-time 8 -o /dev/null -w "%{time_total}" \
      "${TV_WEBHOOK_URL/health}" 2>/dev/null || echo "-1")
  else
    HTTP_CODE=$(wget -q --timeout=8 -O /dev/null \
      "${TV_WEBHOOK_URL/health}" 2>&1 | grep -oE '[0-9]+' | head -1 || echo "000")
    HTTP_TIME="-1"
  fi

  if [ "$HTTP_CODE" = "200" ]; then
    pass "TV Webhook 可达 HTTP $HTTP_CODE (${HTTP_TIME}s)"
  elif [ "$HTTP_CODE" = "000" ]; then
    fail "TV Webhook 不可达（网络/DNS/防火墙问题）"
    info "请检查: 1) VPS 外网可达  2) twinstar.pro 可解析  3) 防火墙开放 443"
    FAILURES=$((FAILURES + 1))
  else
    info "TV Webhook HTTP $HTTP_CODE（可能仅 /health 路径不同，请确认路由配置）"
  fi

  # 端口 443 握手
  echo -n "    TCP :443 握手 ... "
  if command -v nc >/dev/null 2>&1; then
    if nc -z -w 5 "$TV_WEBHOOK_HOST" 443 2>/dev/null; then
      pass ":443 端口开放"
    else
      fail ":443 端口无法连接"
      FAILURES=$((FAILURES + 1))
    fi
  elif command -v timeout >/dev/null 2>&1; then
    if (timeout 5 bash -c "echo >/dev/tcp/$TV_WEBHOOK_HOST/443" 2>/dev/null); then
      pass ":443 端口开放"
    else
      fail ":443 端口无法连接"
      FAILURES=$((FAILURES + 1))
    fi
  else
    info ":443 端口检查跳过（nc/timeout 不可用）"
  fi
fi

# ============================================================
# 3. 内部可达性检查
# ============================================================
echo ""
echo ">>> [3] 内网连通性检查"

# GitHub 连通性
echo -n "    GitHub.com 连通性 ... "
if curl -sf --max-time 6 https://api.github.com >/dev/null 2>&1; then
  pass "GitHub 可达"
else
  fail "GitHub 不可达（无法推送）"
  FAILURES=$((FAILURES + 1))
fi

# Docker 检查
echo -n "    Docker 可用性 ... "
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    pass "Docker 可用"
  else
    info "Docker 不可用（本地测试环境可忽略此警告）"
  fi
else
  info "Docker 未安装（本地开发可忽略）"
fi

# ============================================================
# 4. 待推送 commit 信息
# ============================================================
echo ""
echo ">>> [4] 待推送 commit"
echo ""
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline -5
echo ""

UPSTREAM_HEAD=$(git rev-parse --short origin/main 2>/dev/null || echo "unknown")
LOCAL_HEAD=$(git rev-parse --short HEAD)
if [ "$UPSTREAM_HEAD" = "$LOCAL_HEAD" ]; then
  info "本地与 origin/main 版本相同，无需推送"
  echo "========================================"
  exit 0
fi

# ============================================================
# 5. 汇总 & 推送
# ============================================================
echo ""
echo "========================================"
if [ "$FAILURES" -gt 0 ]; then
  echo -e "  ${RED}自检失败 · FAIL=${FAILURES}${NC}"
  echo "  请修复上述 [FAIL] 项后重跑"
  echo "========================================"
  exit 1
fi

echo "  自检全部通过"
echo "  本地 HEAD:  $(git rev-parse --short HEAD)"
echo "  origin/main: $(git rev-parse --short origin/main 2>/dev/null || echo '?')"
echo ""
ask "确认推送到 GitHub origin/main？[y/N]: "
read -r response
if [[ ! "$response" =~ ^[Yy]$ ]]; then
  echo "已取消。"
  exit 1
fi

echo ""
echo ">>> [5] 推送到 GitHub"
git push origin main

if [ $? -eq 0 ]; then
  echo ""
  echo "========================================"
  pass "推送成功！"
  echo "  现在可以在 VPS 上执行部署:"
  echo "  cd ~/panda-quant-platform && bash deploy.sh"
  echo "========================================"
else
  echo ""
  fail "推送失败，请检查:"
  echo "  1. GitHub Personal Access Token 是否有效"
  echo "  2. 或使用 SSH Key 认证"
  echo "  3. 当前分支是否有保护规则"
  echo ""
  echo "  手动推送命令:"
  echo "  git push origin main"
  exit 1
fi
