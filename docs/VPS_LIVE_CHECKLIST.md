# 🛡️ 万亿战神 VPS 实盘检查清单（Cursor 开发自查专用）

> **用途**：Cursor / 开发者在改代码后逐项对照；每项映射到源码与自动化测试。  
> **交易所**：Binance · OKX · Gate.io · DeepCoin（统一交易工厂，逻辑相同；DeepCoin 数量单位为「张」）。  
> **TV 职责**：只发信号；VPS 自主开仓、硬止损、仓位计算、雷达保本。

---

## 核心原则（必须刻进代码）

| # | 原则 | 源码锚点 |
|---|------|----------|
| P0 | TV 只发信号，不执行实盘决策 | `webhook_server.py` → `dispatcher.py` → `position_supervisor*.py` |
| P0 | 硬止损严格按 TV `tv_sl` 挂单（多空·全所）；**禁止**开仓价×档位% 旧宽止损 | `vps_hard_sl.py` · `adverse_radar_guard.py` |
| P1 | 雷达移动保本 **距 TP1 剩 15%（路径≥85%）** 启动（四档统一；TP1 间距过窄时抬高有效比例 + 开仓保护期 + 双轮确认；TP 成交强制激活） | `evaluate_radar_arm_gate()` · `_radar_activation_reached()` |
| P0 | ETH / XAU **独立** supervisor 状态，互不串单 | `symbol_registry.py` · `dispatcher.UserSupervisorPool` |
| P0 | 所有 OPEN sizing 基于 **账户总本金（Total Equity）**，非可用余额 | `position_sizing.resolve_principal_sizing_base()` · `tv_entry_sizing.py` |

**Cursor 一键验收**（在 `backend/` 目录）：

```bash
py -m pytest tests/test_dual_symbol.py tests/test_vps_dev_checklist.py tests/test_tp_slice_guard.py tests/test_vps_hard_sl.py tests/test_signal_dispatch_chain.py -q
```

---

## 模块一：Webhook 解析与币种路由 🔴 P0

| # | 检查项 | 状态 | 源码 / 测试 |
|---|--------|------|-------------|
| 1.1 | 正确解析 JSON 中 `symbol` / `ticker` / `contract` 字段 | ✅ | `symbol_registry.extract_payload_symbol()` |
| 1.2 | ETH 信号 → 只操作 ETHUSDT 仓位 | ✅ | `dispatcher.py` 按 canonical 路由 |
| 1.3 | XAU 信号 → 只操作 XAUUSDT 仓位 | ✅ | 同上 |
| 1.4 | 未知 symbol → 拒绝并记录 `unknown_symbol` | ✅ | `normalize_canonical_symbol(..., default=None)` |
| 1.5 | 同 symbol + action + price 去重（120s TTL） | ✅ | `webhook_idempotency.py` |

### 支持的 TV 品种写法

| TV 发送 | 归一化结果 |
|---------|------------|
| `ETHUSDT.P` / `BINANCE:ETHUSDT` | `ETHUSDT` |
| `XAUUSDT.P` / `XAUUSD` / `GOLD` | `XAUUSDT` |
| 缺失 / 未知 | **拒绝**（不默认 ETH） |

### 实盘场景

| 场景 | VPS 预期 |
|------|----------|
| ETH 图表 `"symbol":"ETHUSDT.P"` | 走 ETH supervisor，计算 ETH 档位/仓位/止损 |
| XAU 图表 `"symbol":"XAUUSDT.P"` | 走 XAU supervisor，互不影响 |
| 无 symbol 的 OPEN | 拒绝，`unknown_symbol` 日志 + 钉钉（admin） |
| 同一 K 线重复 Webhook | 第二条被 fingerprint 去重拦截 |

---

## 模块二：开单计算（档位权重 + 25× 杠杆）🔴 P0

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 2.1 | 实时获取 total_equity | ✅ | 交易所账户接口 → `resolve_principal_sizing_base()` |
| 2.2 | 档位 1~4 保证金系数（占总本金 %） | ✅ | `REGIME_MARGIN_1~4` · `regime_margin_coeff()` |
| 2.3 | ETH / XAU 独立系数（共用表，独立 supervisor） | ✅ | per-symbol supervisor |
| 2.4 | 杠杆 25×（四所统一） | ✅ | `config.exchange_leverage()` |
| 2.5 | 名义头寸 = 保证金 × 杠杆 | ✅ | `compute_vps_open_qty()` |
| 2.6 | 下单数量 = 名义 ÷ 开仓价（含精度） | ✅ | `symbol_precision` ETH 0.001 / XAU 0.01 |
| 2.7 | 双品种总名义 ≤ 总本金 × 13 | ✅ | `combined_notional.check_combined_notional_cap()` |

### 开仓金额系数（45m ETH / 50m XAU 短周期权重）

| 档位 | 保证金系数 | 1000U 本金示例（25×） |
|------|-----------|----------------------|
| R1 | 8% | 80U 保证金 → 2000U 名义 |
| R2 | 14% | 140U → 3500U |
| R3 | 20% | 200U → 5000U |
| R4 | 26% | 260U → 6500U |

**公式**：`margin = equity × coeff` · `notional = margin × 25` · `qty = notional / price`

### 实盘场景

| 场景 | VPS 预期 |
|------|----------|
| ETH R4 @1800，本金 1000U | qty ≈ 3.61 ETH，名义 6500U |
| ETH R2 + XAU R4，本金 1000U | 3500 + 6500 = 10000U（10×，允许） |
| ETH R4 + XAU R4 | 13000U = 13×（踩线允许） |
| 已有 13×，再开新仓 | 拒绝，`combined_notional_exceeded` + 钉钉 |
| 浮盈后本金 1200U | 下次按 1200U × 系数自动放大 |

**测试**：`test_dual_symbol.py::test_margin_coeff_and_open_qty_matches_spec`

---

## 模块三：硬止损（严格按 TV `tv_sl` · 禁止 VPS 宽止损）🔴 P0

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 3.1 | 硬止损 = TV `tv_sl`（权威价） | ✅ | `vps_hard_sl.compute_vps_hard_sl(tv_sl_reference=…)` |
| 3.2 | 缺 `tv_sl` → 不挂、告警 `HARD_SL_MISSING`（无开仓价%兜底） | ✅ | `error=no_tv_sl` |
| 3.3 | 多空 · ETH/XAU · 四所同一套 | ✅ | `AdverseRadarMixin._sync_tv_hard_stop` |
| 3.4 | OPEN / UPDATE_SL 均按 TV 价挂/改挂 | ✅ | `_apply_tv_sl_from_payload` / `_handle_update_sl` |
| 3.5 | 开仓成交后立即挂 **Stop-Limit / 条件槽**（禁止普通限价硬止损） | ✅ | `adverse_radar_guard._place_adverse_stop_slice` |
| 3.6 | 雷达合并槽：LONG max(tv,radar) / SHORT min | ✅ | `_merged_stop_price` |
| 3.7 | ~~`tv_sl` 仅日志~~ **已废止** — `tv_sl` 即挂单价 | ✅ | 删除 VPS entry% 挂单路径 |
| 3.8 | 雷达启动前币安条件委托 = 1（TV硬止损） | ✅ | 合并单槽 |

### 实盘场景

| 场景 | VPS 预期 |
|------|----------|
| TV `tv_sl=1787` LONG | 条件单触发价 **1787**（不是开仓价×%） |
| 开仓后币安盘口 | 基础单 **3**（TP123）+ 条件委托 **1**（TV硬止损）；勿挂普通限价硬止损 |
| 缺 `tv_sl` | `HARD_SL_MISSING`；**不**用旧宽止损兜底 |
| `UPDATE_SL` | 按新 `tv_sl` **改挂** |
| `CLOSE_STOPLOSS` | **第一优先级**立即市价全平 |

**测试**：`test_vps_hard_sl.py` · `test_dual_symbol.py::test_hard_sl_uses_tv_sl` · `test_startup_hard_sl_recompute.py`

---

## 模块四：雷达移动保本（路径比例启动 · TP2/TP3 锁利）🟡 P1

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 4.1 | 雷达按 **TP1 路径进度 ≥ 档位激活比例** 启动 | ✅ | `radar_may_arm()` · `_radar_activation_reached()` |
| 4.2 | 四档统一 **85%**（距 TP1 剩 15%） | ✅ | `REGIME_RADAR` |
| 4.3 | **不再**要求 qty+book+price 三重验证才启动 | ✅ | 三重门仅用于 TP 切片记账 |
| 4.4 | 启动后止损上移至成本 + 微利 | ✅ | Stage 1 · `BREAKEVEN_BUFFER_PCT=0.1%` |
| 4.5 | 价格到 TP1 前保持 Stage 1；之后 TP2/TP3 逐步锁利 | ✅ | Stage 2~5 ATR 追踪 |

### 激活逻辑

```
progress = |mark − entry| / |TP1 − entry|
if progress ≥ REGIME_RADAR[regime].activation  →  arm Stage 1（保本）
# 不再等待：qty 减仓匹配 / TP1 限价撤单 / 三重同时满足

到达 TP1 后：Stage 2~5 随 TP2/TP3 路径继续锁利（与 webhook 雷达保本配合）
```

| 档位 | 激活路径（占 entry→TP1） |
|------|--------------------------|
| R1 | **50%** |
| R2 | **60%** |
| R3 | **70%** |
| R4 | **80%** |

> 源码唯一表：`radar_trail.REGIME_RADAR`。雷达挂上后**只前进、禁止解除**。

### TP 切片（min_qty · 尽量保留 TP123）

| 条件 | 行为 |
|------|------|
| `qty ≥ N × min_qty`（N=活跃档位数） | 每档至少 `min_qty`，余量按档位比例分配 → **保留全部 N 档** |
| `qty < N × min_qty` | 欠量档 fold 到后续档，至少挂出可成交的一档 |

例：XAU `min_qty=0.01`，仓位 `0.04`，R2 三档 → 挂 3 个 TP（不再因 20%×0.04=0.008 丢掉 TP1）。  
**测试**：`test_xau_symbol_routing.py::test_xau_tp_slices_keep_three_when_qty_allows`

### 雷达阶段（6 阶段 0~5）

| Stage | 标签 |
|-------|------|
| 0 | 硬止损防守（TP1 前） |
| 1 | TP1 成交 · 保本激活 |
| 2 | TP1→TP2 50% · 追踪 |
| 3 | 到达 TP2 · 锁利 |
| 4 | TP2→TP3 50% · 加深 |
| 5 | 到达 TP3 · 极限保护 |

### 实盘场景

| 场景 | 雷达 |
|------|------|
| 价格插针到 TP1，限价单未成交 | ❌ 不启动 |
| 价格到 TP1 + 限价单成交/部分成交 | ✅ 启动 |
| 价格到 TP1，仓位仅减 0.001（误差） | ❌ 不启动 |
| 价格到 TP1，仓位明显减少 + 订单消失 | ✅ 启动 |
| 浮盈 +10%，数量不变 | ❌ 不启动 |

**测试**：`test_tp_slice_guard.py::test_confirm_tp_tier_fill_triple_gate`

---

## 模块五：全局风控（13× 名义硬顶）🔴 P0

| # | 检查项 | 状态 | 配置 |
|---|--------|------|------|
| 5.1 | ETH + XAU 名义 ≤ equity × 13 | ✅ | `MAX_COMBINED_NOTIONAL_MULT=13.0` |
| 5.2 | 超标拒绝新开仓，不强平已有仓 | ✅ | `combined_notional_exceeded` |
| 5.3 | 每日最大亏损熔断 | ⚙️ | TV `maxDailyLossPercent` 参考；VPS 可独立配置 |
| 5.4 | 双品种盈亏叠加 vs 总权益 | ✅ | 绩效结算层 |

---

## 模块六：头寸监控与误判防范 🟡 P1

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 6.1 | 区分数量变化 vs 价值变化 | ✅ | sentinel 读 `position.size` 非 notional |
| 6.2 | 雷达基于数量减少，非价值 | ✅ | `tp_slice_guard` qty 门 |
| 6.3 | 开仓快照 entry / qty / TP order ids | ✅ | `open_journal.jsonl` · supervisor state |
| 6.4 | WebSocket 实时仓位 + 价格 | ✅ | 四所 client `_public_price_ws_loop` |
| 6.5 | 微小数量变化忽略 | ✅ | `qty_drift_tolerance` · slice 35% 带 |

---

## 模块七：钉钉通知 🟢 P2

| # | 事件 | 推送 | 类型 |
|---|------|------|------|
| 7.1 | 开单成功 | ✅ | `OPEN` |
| 7.2 | 硬止损触发 | ✅ | `CLOSE` / `STOP` |
| 7.3 | 雷达启动 | ✅ | `RADAR_ARM` |
| 7.4 | TP2/TP3 触发 | ✅ | `CLOSE` + TP 详情 |
| 7.5 | TV 紧止损忽略 | 仅日志 | 不推送 |
| 7.6 | 名义超标拒绝 | ✅ | admin + `combined_notional_exceeded` |
| 7.7 | ETH / XAU 标题与正文区分 | ✅ | `resolve_exchange_theme(symbol)` · tag `#币安25x·XAU` |

配置：`platform_runtime.json` dingtalk.* > `.env DINGTALK_*`  
过滤：`trading_alerts.should_push_trading_dingtalk()`  
主题：每条 alert 的 `detail.symbol` / `canonical_symbol` 必须注入（supervisor `_alert`），禁止默认写成 ETH。

---

## 完整实盘模拟（Cursor 测试用例）

### 场景 1：正常 TP1 → 雷达 → TP2/TP3

```
1. ETH 1800，R3（20% 保证金，1000U 本金）
2. VPS：margin 200U，名义 5000U，qty ≈ 2.78 ETH
3. 硬止损：1800 × (1 − 5.56%) ≈ 1700
4. 挂 TP1/2/3 限价（R3 比例 18/32/50%）
5. 价格达 TP1 路径 **85%**（距 TP1 剩 15%）→ 雷达 Stage 1 保本；继续追踪锁 TP2/TP3
6. 价格到 TP2/TP3，Stage 3~5 逐步锁利
```

### 场景 2：插针未达激活比例 → 雷达不启动

```
1. ETH 1800，TP1 = 1980，统一激活 85%
2. 价格瞬间 1900（约 55% 路径）后回落
3. progress < 0.85 → 雷达不启动，仅硬止损防守
4. 若最终触及硬止损 → 正常风控离场
```

### 场景 3：双品种 R4 踩线

```
1. 本金 1000U，ETH R4 6500U + XAU R4 6500U = 13000U = 13× → 允许
2. ETH 浮盈后名义 7000U，XAU 新开 6500U → 13500U > 13× → 拒绝
```

### 场景 4：TV 紧止损被忽略

```
1. TV tv_sl=1910
2. 盘口条件单触发价 = 1910（严格按 TV）
3. 不再使用 entry × regime_pct 宽止损
```

---

## 四所适配对照

| 能力 | Binance | OKX | Gate | DeepCoin |
|------|---------|-----|------|----------|
| OPEN sizing | ✅ | ✅ | ✅ | ✅（张） |
| TV 硬止损 | ✅ | ✅ | ✅ | ✅ 双轨 |
| 路径雷达激活 | ✅ | ✅ | ✅ | ✅ |
| 6 阶段雷达 | ✅ | ✅ | ✅ | ✅ |
| ETH + XAU | ✅ | ✅ | ✅ | ✅ |
| 13× 名义 cap | ✅ | ✅ | ✅ | ✅ |
| 价格 WebSocket | ✅ | ✅ | ✅ | ✅ |

工厂入口：`exchange_factory.create_supervisor()`  
DeepCoin 差异：合约张、`face_value=0.1`、双轨 STOP（TV SL + 雷达条件单并行）。

---

## 优先级与 Cursor 开发指引

| 模块 | 优先级 | 改代码后必跑测试 |
|------|--------|------------------|
| Webhook + 品种路由 | 🔴 P0 | `test_dual_symbol` · `test_webhook_payload` |
| OPEN sizing + 13× cap | 🔴 P0 | `test_dual_symbol` · `test_tv_v6985_sizing` |
| TV 硬止损 | 🔴 P0 | `test_vps_hard_sl` · `test_tv_sl_shield` |
| 路径雷达 + Stage 锁利 | 🟡 P1 | `test_radar_trail` · `test_vps_radar_stages` |
| 钉钉 | 🟢 P2 | `test_vps_dev_checklist` |

**禁止事项**：

- 不要用开仓价×档位% 挂实盘硬止损（旧 VPS 宽止损已删除）
- 不要在缺 `tv_sl` 时用假宽止损兜底（应告警 `HARD_SL_MISSING`）
- 不要仅凭头寸细微变化（R4 TP1≈5%）启动雷达
- 不要让 ETH 信号路由到 XAU supervisor
- 不要用可用余额代替 total equity 做 OPEN sizing

---

## 相关文件索引

```
backend/app/core/symbol_registry.py      # 品种归一化 + 四所符号表
backend/app/core/tv_entry_sizing.py      # OPEN/ADD  sizing
backend/app/core/vps_hard_sl.py          # TV tv_sl 硬止损（权威挂单价）
backend/app/core/tp_slice_guard.py       # 三重 TP 验证
backend/app/core/vps_radar_stages.py     # 雷达 6 阶段
backend/app/core/combined_notional.py    # 13× 名义 cap
backend/app/services/dispatcher.py       # 按用户×品种分发
backend/app/services/webhook_idempotency.py
backend/app/services/trading_alerts.py   # 钉钉
backend/app/core/exchange_factory.py     # 四所工厂
```
