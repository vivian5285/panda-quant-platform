# 最终全面复检报告（2026-07-22）

## 任务一：止损抖动硬性验收 — 通过

### 部署
- VPS `/home/panda/panda-quant-platform` 已热更并 `docker compose build/up backend`
- 健康检查：`{"status":"ok"}`
- 运行时确认：`return bool(improved)`、`_clear_position_local_state`、`HARD_SL_MISSING ∈ ADMIN_DINGTALK_KEY_TYPES`

### ≥30 分钟真实观察（持仓中）
| 项 | 结果 |
|----|------|
| 窗口 | UTC `06:12:25` → `06:43+`（≥1860s） |
| 仓位 | LONG **0.033 ETH** @ 1918.0（User 6） |
| 止损 | algo STOP_MARKET **@1895.79** qty=0.033，`algoId=1000002467282874` 全程不变 |
| TP | LIMIT @1925.97 / @1940.78 保持 |
| `cancel algo order` | **0** |
| `algo stop` 日志 | **1**（仅开仓挂单一次） |
| `HARD_SL_MISSING` / `IndexError` | **0** |
| `current_sl` | 全程 `1895.79`（无无意义改价） |

分钟级采样（节选）：全程 `chunk_cancel=0`，仅首分钟 `chunk_place=1`。

### 钉钉测试告警
- `HARD_SL_MISSING` critical：`should_push=True`，`push_trading_alert` 已调用
- `CLOSE` info：同上
- **请在钉钉群确认**标题含「验收测试·HARD_SL_MISSING白名单」「验收测试·CLOSE类型」的两条（无法在此贴截图，需人工确认）

---

## 任务二：原则对照自查

### A. 四条硬性原则

| # | 判定 | 证据 |
|---|------|------|
| A1 永远先平后开 | **符合** | `position_supervisor.py` `_force_flat_before_open`；OPEN 路径 `handle`/`SAME_DIR_REOPEN` 均先调用 |
| A2 单仓不加仓 | **符合** | `_handle_add` →「妈妈版 pyramiding=1 — 加仓禁用」；无真实加仓路径（`add_count` 仅为残留字段） |
| A3 数量纯函数 | **符合** | sizing 走 RISK/TV qty + ATR，不读历史仓位做加仓；先平后开后再算 |
| A4 止损唯一写入呼吸引擎 | **符合（修复后）** | 哨兵不再二次 `force_replace`；tick 仅 `improved` 或缺失才 sync；`_ensure_radar_sl` 默认 `force_replace=False`。仍允许：开仓/TP 缩量/真正价格改进时 `force_replace=True`（合理） |

### B. Webhook

| # | 判定 | 证据 |
|---|------|------|
| B1 仅 4 action | **符合** | `webhook_guard.py` `ALLOWED_ACTIONS` = LONG/SHORT/CLOSE_QUICK_EXIT/CLOSE_RSI_EXIT |
| B2 secret + token 兼容 | **符合** | `webhook_server.py` secret 优先；已标注 ≥14 天无 token-only 失败后可移除 |
| B3 60s 去重 | **符合** | `webhook_idempotency.py` `IDEMPOTENCY_TTL_SEC = 60` |

### C. 呼吸止损

| # | 判定 | 证据 |
|---|------|------|
| C1 状态持久化 | **符合** | `state.json` 含 entry/sl/initial_atr/initial_stop/best_price/breakeven_phase/remaining_qty_pct；实盘观察中恢复后一致 |
| C2 阶梯基准 initialStop | **符合** | `breathing_stop.py` `step_stop = initial_stop ± step_count * STEP * atr` |
| C3 TP1/TP2 底线 | **符合** | `TP1_FLOOR_ATR=0.5` `TP2_FLOOR_ATR=1.5` |
| C4 ADX 追踪 1.2~2.5 | **符合** | `TRAIL_DIST_WEAK/STRONG` + `trail_distance_by_adx` |
| C5 TP 后止损 qty 收缩 | **部分符合** | 代码有（TP fill → sync force_replace）；**本轮未真实触 TP**，见已知问题 |

### D. 状态清理

| # | 判定 | 证据 |
|---|------|------|
| D1 全路径清零 | **符合** | `_close_all` / dust / startup flat / force_flat → `_clear_position_local_state`（Binance+DeepCoin） |
| D2 无半清理残留 | **符合** | 清零含 entry/side/best/sl/atr/breakeven；FORCE_FLAT 不再 side=None 时乱报 HARD_SL_MISSING |

### E. ATR 应急兜底

| # | 判定 | 证据 |
|---|------|------|
| E1 触发条件 | **符合** | `atr_emergency_fallback.py` + config streak/mismatch |
| E2 降级后暂停 | **符合** | `_pause_trading` after fallback open |
| E3 未被抖动污染 | **符合** | 兜底与止损 sync 解耦 |

### F. 重启恢复

| # | 判定 | 证据 |
|---|------|------|
| F1 FORCE_ALIGN / 干净恢复 | **符合（代码）** | `startup_reconcile.py`；本轮重启后开仓观察状态干净。建议下次专门做一次「有仓重启」抽检 |

### G. 防螺旋

| # | 判定 | 证据 |
|---|------|------|
| G1 仓位对账 | **符合** | `_reconcile_live_vs_book` |
| G2 TP 超时移交 | **符合** | `TP_LIMIT_TIMEOUT_SEC` + `TP_SKIP_REHANG` |
| G3 改单失败中止 | **符合** | `HARD_SL_FAIL_ABORT` |
| G4 API 退避 | **符合** | 钉钉 `_send_with_retry` 指数退避；客户端重连逻辑保留 |

### H. 钉钉完整性

| # | 判定 | 证据 |
|---|------|------|
| H1 白名单 | **部分符合→已补** | 曾缺 TP1/2/3_FILL、SIGNAL_RECV、ADVERSE_SL_DISARM；本地已加入。`RADAR_ARM/REVOKE` 仍缺（旧路径，低优） |
| H2 `_call_dingtalk` | **符合（过渡）** | inspect + 位置参数降级；长期应统一 `push_trading_alert` |

---

## 任务三交付物

1. 本报告 + `docs/VPS_DEPLOY.md` + `docs/KNOWN_ISSUES.md`
2. Git 提交并推送（见后续 commit）
3. **当前仓位**：0.033 ETH LONG，止损 1895.79 — **保持观察，未强平**

## 仍需你人工确认的一项

钉钉群是否收到两条「验收测试」消息（本环境无法贴截图）。
