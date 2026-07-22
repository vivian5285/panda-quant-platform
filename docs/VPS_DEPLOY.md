# VPS 部署说明（权威备份对齐后）

## 前置

- 代码仓库：GitHub `panda-quant-platform`（以 `main` 最新提交为准）
- 生产路径：`/home/panda/panda-quant-platform`
- 运行：`docker compose`（服务名 `backend`，健康检查 `http://127.0.0.1:6010/health`）

## 标准部署步骤

```bash
cd /home/panda/panda-quant-platform
git fetch origin
git checkout main
git pull --ff-only origin main
docker compose build backend
docker compose up -d backend
# 等待健康
for i in $(seq 1 24); do
  curl -sf http://127.0.0.1:6010/health && break
  sleep 5
done
curl -sS http://127.0.0.1:6010/health
```

热更新单文件（紧急）：`pscp`/`scp` 覆盖 `backend/app/...` 后同样 `docker compose build backend && docker compose up -d backend`。

## 必须确认的环境变量 / 配置

| 项 | 说明 |
|----|------|
| `WEBHOOK_SECRET` | 与 TV `secret` 一致 |
| `DINGTALK_WEBHOOK` / `DINGTALK_SECRET` | 管理员告警 |
| `TV_STOP_ATR_MULT` | 默认 `1.0`（TV 止损反推，勿改回 1.5） |
| `ATR_FALLBACK_STREAK` / `ATR_FALLBACK_MISMATCH_PCT` | ATR 应急降级 |
| `FORCE_FLAT_RETRY_DELAYS_SEC` | 默认 `1,3,6` |
| 交易所 API Key | 用户库内加密字段，勿进 Git |

配置文件通常在 `backend/.env`（宿主机挂载进容器）。

## 部署后人工检查清单

1. `curl http://127.0.0.1:6010/health` → `status=ok`
2. `docker compose logs --since 5m backend` 无持续 Traceback
3. 若有持仓：`state.json` 的 `monitoring/current_side/watched_entry/current_sl` 与交易所仓位一致
4. 交易所条件单：应有 **1 笔** 呼吸止损 algo STOP（数量≈仓位），以及 TP1/TP2 限价（若未成交）
5. **不应**出现固定 ~5s 的 `cancel algo order` ↔ `algo stop` 成对日志
6. 发一条 `HARD_SL_MISSING` 或 `CLOSE` 测试告警，确认钉钉收到
7. 若 `trading_paused=true`，人工确认原因后再恢复

## 回滚

```bash
git log -5 --oneline
git checkout <known_good_sha>
docker compose build backend && docker compose up -d backend
```

## 注意

- 部署会重建 `backend` 容器；有仓时会走重启恢复（`recover_on_startup`），确认恢复后止损仍在。
- 不要用 `docker compose down -v`（会丢数据卷）。
