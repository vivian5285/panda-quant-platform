#!/bin/bash
# 双子星AI量化 · GEMINI AI · 部署公共函数（端口清理 / Git 同步）
# v6.5.6: sync_github_code 保留 .env / data / state / logs；全交易所同一交易逻辑
# shellcheck disable=SC2034

deploy_fail() { echo "[FAIL] $1"; exit 1; }
deploy_ok()   { echo "[OK]   $1"; }
deploy_info() { echo "[INFO] $1"; }

# 获取占用 TCP 端口的 PID 列表
pids_on_port() {
  local port=$1
  local pids=""
  if command -v ss >/dev/null 2>&1; then
    pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ')
  fi
  if [ -z "$pids" ] && command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti :"$port" 2>/dev/null | tr '\n' ' ')
  fi
  if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
    pids=$(fuser "${port}/tcp" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' | tr '\n' ' ')
  fi
  echo "$pids"
}

# 强制释放端口（SIGTERM → SIGKILL）
kill_port() {
  local port=$1
  local name=${2:-":${port}"}
  local pids
  pids=$(pids_on_port "$port")
  if [ -z "$pids" ]; then
    deploy_ok "端口 ${name} 无残留进程"
    return 0
  fi
  deploy_info "端口 ${name} 占用 PID: ${pids} — 正在终止"
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 2
  pids=$(pids_on_port "$port")
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null || true
    done
    sleep 1
  fi
  pids=$(pids_on_port "$port")
  if [ -n "$pids" ]; then
    deploy_fail "端口 ${name} 仍被占用 (PID ${pids})，请手动处理"
  fi
  deploy_ok "端口 ${name} 已清理干净"
}

# 停止本平台 Docker 并清理三端口
clean_platform_ports() {
  local front_port=${1:-6080}
  local api_port=${2:-8000}
  local webhook_port=${3:-6010}

  deploy_info "停止 Docker 容器..."
  docker compose down --remove-orphans 2>/dev/null || true
  sleep 2

  kill_port "$front_port" "前端 ${front_port}"
  kill_port "$api_port" "REST API ${api_port}"
  kill_port "$webhook_port" "Webhook ${webhook_port}"
}

# 从 GitHub 拉取最新代码（保留 backend/.env）
sync_github_code() {
  local root=$1
  local branch=${GIT_BRANCH:-main}
  local remote=${GIT_REMOTE:-origin}

  cd "$root"
  command -v git >/dev/null 2>&1 || deploy_fail "未安装 git"

  if [ ! -d .git ]; then
    deploy_fail "当前目录不是 git 仓库，请先 git clone"
  fi

  deploy_info "同步远程 ${remote}/${branch} ..."
  git fetch "$remote" "$branch" || deploy_fail "git fetch 失败"

  local env_backup=""
  if [ -f backend/.env ]; then
    env_backup=$(mktemp)
    cp backend/.env "$env_backup"
    deploy_info "已备份 backend/.env"
  fi

  git reset --hard "${remote}/${branch}" || deploy_fail "git reset 失败"
  git clean -fd -e backend/.env -e backend/data -e backend/state -e backend/logs || true

  if [ -n "$env_backup" ] && [ -f "$env_backup" ]; then
    cp "$env_backup" backend/.env
    rm -f "$env_backup"
    deploy_ok "已恢复 backend/.env"
  fi

  deploy_ok "代码已对齐 ${remote}/${branch} ($(git rev-parse --short HEAD))"
}

# 等待 compose 服务 Up / healthy（避免 frontend 刚启动时被误判未运行）
wait_compose_service() {
  local svc=$1
  local max_wait=${2:-60}
  local elapsed=0
  while [ "$elapsed" -lt "$max_wait" ]; do
    if docker compose ps "$svc" 2>/dev/null | grep -qE 'Up|\(healthy\)'; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}
