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
| C5 TP 后止损 qty 收缩 | **符合** | 受控模拟：真实调用链 `_orchestrate_qty_change`（与 sentinel qty_changed 同路径）；TP1→qty=剩余仓、ID 撤旧挂新；pause 8s 内 tick 零 cancel/place。证据：`backend/tests/test_tp_fill_stop_qty_resize.py` + `backend/data/_tp_resize_verify_report.json`。**未碰**实盘 0.033 ETH |

### D. 状态清理

| # | 判定 | 证据 |
|---|------|------|
| D1 全路径清零 | **符合** | `_close_all` / dust / startup flat / force_flat → `_clear_position_local_state`；另见 **阶段二全平补验** |
| D2 无半清理残留 | **符合** | 清零含 entry/side/best/sl/atr/breakeven；阶段二 trail hit 模拟确认无 `side=None`+残留 entry |

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

## C5 补验：TP 成交后止损 qty 收缩（2026-07-22）

- **方式**：代码层调用与 sentinel 完全相同的 `_orchestrate_qty_change`（RecordingClient 仅替换交易所 I/O）；**未**对实盘 0.033 ETH 下单
- **路径**：`_sentinel_loop` qty_changed → `_orchestrate_qty_change` → `_boost_radar_after_tp_fill` → `_sync_binance_merged_stop(force_replace=True)`（同一次 orchestrate 内还有一次 TP 分支二次 sync，属生产行为）
- **TP1**：止损 `9001/0.033@1895.79` → 撤旧挂新终态 `1002/0.017@1895.79`；`remaining_qty_pct=0.7`；价=当前 `current_sl`
- **TP2**：`9100/0.017` → 终态 `1002/0.013@1895.79`；`remaining_qty_pct=0.4`
- **竞态**：resize 后立刻打 breathing tick + defense orchestrate；pause≈8s 内 **0** 次 cancel/place
- **证据文件**：`backend/tests/test_tp_fill_stop_qty_resize.py`（2 passed）、`backend/data/_tp_resize_verify_report.json`

---

## 阶段二 / TP3 收网全平 + 状态清零补验（2026-07-22）

- **产品语义**：TP3 **不挂限价**；TP1+TP2 后剩余约 40% 由呼吸引擎阶段二（ADX 追踪）接管；全平发生在 **追踪止损触达**，不是 TP3 限价成交
- **方式**：调用与生产相同的 `PositionSupervisor._process_breathing_stop_tick` → `stop_hit` → `_close_all(CLOSE_BREATH_STOP)` → `_clear_position_local_state`；**未碰**实盘 0.033 ETH
- **触发前（脏状态）**：`entry=1918` `side=LONG` `breakeven_phase=True` `sl=1975.5` `qty=0.013` `consumed=[1,2]` `radar_latched=True`
- **触发**：价 `1973.5` 跌破追踪止损 → reason=`止损平仓(阶段二/趋势追踪)`
- **触发后**：`entry=0` `side=None` `best/sl/atr/tv_sl=0` `breakeven=False` `qty=0` `consumed=[]` `trade_id=None` `radar_latched=False` `monitoring=False`
- **半吊子断言**：禁止 `side=None` 且 `watched_entry>0` — **通过**
- **附带**：交易所已先平仓时，`_close_all` 仍执行清零（2nd case）
- **证据**：`backend/tests/test_tp3_phase2_flat_clear.py`（2 passed）、`backend/data/_tp3_phase2_flat_clear_report.json`

---

## 任务三交付物

1. 本报告 + `docs/VPS_DEPLOY.md` + `docs/KNOWN_ISSUES.md`
2. Git 提交并推送（见后续 commit）
3. **当前仓位**：0.033 ETH LONG，止损 1895.79 — **保持观察，未强平**

## 仍需你人工确认的一项

钉钉群是否收到两条「验收测试」消息（本环境无法贴截图）。

---

## 清单 v2 补验（多用户隔离 + DeepCoin 对照）

### 一、多用户 / 多 symbol 隔离 — PASS
- 池键 `(user_id, canonical)`；同用户 ETH+XAU 呼吸状态互不污染；双用户同 ETH 并发 seed 不串读；API key 绑定在各自 client；sizing 权益并发不串
- 证据：`backend/tests/test_user_symbol_isolation.py`

### 二、DeepCoin 对照 — A/D/E 原已 SYNCED；B/C 本轮补齐 → 全 SYNCED
- 对照表：`docs/DEEPCOIN_BINANCE_PARITY.md`
- 单测：`backend/tests/test_deepcoin_binance_parity.py`
- 代码：DC `_bump_sl_after_tp_reconcile` 对齐 boost；DC/BN TV 对账 flat + DC 重启空仓 → `_clear_position_local_state`
