# 智能再入场闭环 · 仓库结构解说（生产权威）

> 同步：2026-07-25 · commit 以 `main` HEAD 为准（部署后三方肉眼同 hash）  
> 适用：币安多用户 Gemini / 单账户同源执行栈 · ETHUSDT（90m）/ XAUUSDT（45m）

本文只解释**代码落点与调用顺序**，方便后期调参与排障。业务理念见根目录 `README.md`「智能再入场闭环」。

---

## 1. 灵魂（三条路径，无第四种）

在两次 TV 信号之间，VPS **不主动认输**：

| 路径 | 触发 | 行为 |
|------|------|------|
| ① 理想 | 价格走到 TP1/TP2/(场景二 TP3) | 止盈兑现 → flat → 等下一 TV |
| ② 核心 | 雷达在保本/微赚区扫出 | 清场 → 双保险限价再入 → 递进档位 → 再冲击 TP |
| ③ 认输 | 硬止损触发 / 亏损平仓 | **永不重入**，等新 TV |

新 TV（含反向 / CLOSE_*）→ 彻底清场 + 重置档位/标签。

---

## 2. 模块地图（改哪里找哪里）

```
TV webhook (:6010)
  → position_supervisor._close_all / OPEN protect
       │
       ├─ flat 成功
       │    ├─ _maybe_arm_smart_reentry(defer=True)   # 只 plan，不挂单
       │    ├─ purge 净场
       │    └─ _commit_deferred_reentry()             # 净场后再开 worker
       │
       └─ OPEN / 再入成交
            └─ _protect_and_monitor
                 ├─ 硬止损  compute_temp_tv_stop (fill + 缓冲 + 滑点)
                 ├─ TP1/TP2 _place_limit_with_retry (+ 本地 tp 标签)
                 └─ 雷达    _ensure_radar_sl (+ 本地 radar 标签)
```

| 文件 | 职责 |
|------|------|
| `backend/app/core/smart_reentry.py` | 纯策略：5 档表、arm 50/65/80/90/95、双保险价、再入区间、硬/亏拒绝 |
| `backend/app/core/smart_reentry_mixin.py` | 执行：plan/commit、清场预检、限价 worker、成交后 protect、钉钉 |
| `backend/app/core/order_place_guard.py` | **本地挂单标签**（防查不到单就风暴挂 50+） |
| `backend/app/core/breathing_stop.py` | `compute_temp_tv_stop` / `compute_hard_stop_distance`；档位 coef 透传 |
| `backend/app/core/breathing_profile.py` | ETH/XAU 基础 profile；`trail_distance_multiplier(..., coef_min/max)` |
| `backend/app/core/position_supervisor.py` | `_close_all` 延迟再入；`_place_limit_with_retry` TP 标签 |
| `backend/app/core/adverse_radar_guard.py` | 硬止损挂单 + hard 本地标签 |
| `backend/app/core/binance_smart_defense.py` | 雷达挂单 + radar 本地标签 |
| `backend/app/core/binance_client.py` | `place_limit_order(..., client_order_id=)` → `newClientOrderId` |
| `backend/app/config.py` | `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED` |

测试：`backend/tests/test_smart_reentry.py` · `test_order_place_guard.py`  
探针：`backend/data/_vps_verify_smart_reentry.py` · `_vps_sync_ready_ding.py`

---

## 3. 闭环时序（必须这个顺序）

```
仓位归零
  → 识别 stop_track（radar / hard / unknown）
  → plan：快照 qty / side / tv_px / tv_sl / atr（不启动线程）
  → clear 本地仓位态 + purge 全部挂单
  → commit：确认 pos=0 且 open_orders 可读且为空（≤3 轮）
  → 本地 reentry 标签 try_acquire（失败 → 拒挂 + 钉钉 REENTRY_DUP_BLOCK）
  → 双保险算价；不优于 TV → 终止
  → place_limit(clientOrderId) · TTL 5min
  → 成交 → release 标签 → 恢复 TV SL/ATR → _protect_and_monitor
  → 钉钉 SMART_REENTRY_PROTECTED（hard/radar/slip 核查）
```

**禁止**：在 purge 之前挂再入限价（会被 cancel_all 误杀或竞态叠单）。  
**禁止**：`get_open_orders` 异常 / `None` 后当作「没有单」继续挂。

---

## 4. 价格与硬止损（再入为什么要带滑点）

再入成交价往往偏离 TV 指导价。硬止损**永远以交易所 fill 为原点**：

```
base = max(|TV.entry − TV.SL| × 1.2, 1.5 × ATR × 1.05)
slip = |fill − TV.entry| × 2
hang = fill ± (base + slip)
```

实现：`breathing_stop.compute_hard_stop_distance` / `compute_temp_tv_stop`。  
再入前 mixin 把 `reentry_tv_sl_ref` / `reentry_atr_ref` / `reentry_tv_px` 写回，避免 flat 清态后硬止损算不出来。

双保险限价：

- LONG：`min(5m_low+tick, TV×0.997)`（无 5m 用 3m；都无则仅 TV%）
- SHORT：`max(5m_high−tick, TV×1.003)`
- 结果必须严格优于 TV，否则本轮终止

---

## 5. 档位表（调参只改 smart_reentry.py）

| 档 | arm×TP1 | ETH early/trig/adv · coef | XAU early/trig/adv · coef |
|----|---------|---------------------------|---------------------------|
| 1.0 | 50% | 0.50 / 0.75 / 0.40 · 1.2~2.5 | 0.65 / 0.70 / 0.45 · 1.2~2.5 |
| 2.0 | 65% | 0.65 / 0.90 / 0.46 · 1.4~2.8 | 0.85 / 0.85 / 0.52 · 1.4~2.8 |
| 3.0 | 80% | 0.85 / 1.10 / 0.52 · 1.6~3.0 | 1.10 / 1.00 / 0.58 · 1.6~3.0 |
| 4.0 | 90% | 1.05 / 1.25 / 0.58 · 1.8~3.2 | 1.30 / 1.15 / 0.64 · 1.8~3.2 |
| 5.0 | 95% | 1.30 / 1.40 / 0.64 · 2.0~3.5 | 1.55 / 1.30 / 0.70 · 2.0~3.5 |

- 再入区间：ETH `0.5×ATR` / XAU `0.3×ATR`（`REENTRY_ZONE_ATR`）
- 最多再入 4 次（满 5.0 再扫出 → 终止）
- ETH / XAU 状态完全隔离（每 supervisor 一份 mixin 状态）

---

## 6. 本地标签（击穿级事故防线）

历史：查不到 TP/止损 → 当「没挂」→ 同价连挂几十笔。

规则（`PendingOrderRegistry`）：

1. 挂单前 `try_acquire(tag)`；已占用 → **绝对拒挂**
2. 交易所查询失败 / 空视图 → 不得覆盖本地标签结论
3. 成功或确认在簿 → `release`；超时/None → 可短期 hold tag 防风暴
4. flat / 新 TV → `clear_all`

种类：`reentry` / `tp` / `hard` / `radar`（同品种同 kind 互斥）。

---

## 7. 钉钉事件（实盘复盘口令）

| 事件 | 含义 |
|------|------|
| `SMART_REENTRY_ARM` | 计划再入，即将/已挂限价 |
| `REENTRY_LIMIT`（日志） | 限价已挂（含 cid/src） |
| `SMART_REENTRY_PROTECTED` | 成交后硬+TP+雷达核查 |
| `REENTRY_DUP_BLOCK` | 本地标签拦截重复挂 |
| `REENTRY_PREFLIGHT_FAIL` | 清场未通过，拒挂 |
| `REENTRY_ABORT` / `REENTRY_SKIP` | 终止/跳过（含原因） |

---

## 8. 部署与三方对齐检查

```bash
# 本地 / GitHub / VPS 三数字必须一致
git rev-parse --short HEAD

# VPS
cd /home/panda/panda-quant-platform
git pull --ff-only origin main
docker compose build backend && docker compose up -d backend
curl -sf http://127.0.0.1:6010/health
docker compose exec -T -e PYTHONPATH=/app backend python /app/data/_vps_verify_smart_reentry.py
docker compose exec -T -e PYTHONPATH=/app -e GIT_HEAD=$(git rev-parse --short HEAD) \
  backend python /app/data/_vps_sync_ready_ding.py
```

生产必须：`E2E_FORCE_NOTIONAL_USD=0`；日亏损熔断关闭（`DAILY_LOSS_CIRCUIT_ENABLED=False`）。  
开关：`.env` 可设 `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED`（默认 True）。

**等真实 TV**：不要主动打 E2E 名义；空仓零挂单 + supervisors_ready + 钉钉 READY 即可。
