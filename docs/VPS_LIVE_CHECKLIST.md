# 🛡️ 万亿战神 VPS 实盘检查清单（Cursor 开发自查专用）

> **用途**：Cursor / 开发者在改代码后逐项对照；每项映射到源码与自动化测试。  
> **交易所**：Binance · OKX · Gate.io · DeepCoin（统一交易工厂，逻辑相同；DeepCoin 数量单位为「张」）。  
> **TV 职责**：只发信号；VPS 自主开仓、硬止损、仓位计算、雷达保本。

---

## 核心原则（必须刻进代码）

| # | 原则 | 源码锚点 |
|---|------|----------|
| P0 | TV 只发信号，不执行实盘决策 | `webhook_server.py` → `dispatcher.py` → `position_supervisor*.py` |
| P0 | `tv_sl` **仅供日志参考**，绝不作为实盘硬止损挂单依据 | `vps_hard_sl.py` · `adverse_radar_guard.py`（`UPDATE_SL` 忽略） |
| P1 | 雷达移动保本 **必须在 TP1 三重验证确认后** 才启动 | `tp_slice_guard.confirm_tp_tier_fill()` · `vps_radar_stages.tp1_filled_from_consumed()` |
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
| 2.7 | 双品种总名义 ≤ 总本金 × 9 | ✅ | `combined_notional.check_combined_notional_cap()` |

### 开仓金额系数

| 档位 | 保证金系数 | 1000U 本金示例（25×） |
|------|-----------|----------------------|
| R1 | 5% | 50U 保证金 → 1250U 名义 |
| R2 | 10% | 100U → 2500U |
| R3 | 15% | 150U → 3750U |
| R4 | 18% | 180U → 4500U |

**公式**：`margin = equity × coeff` · `notional = margin × 25` · `qty = notional / price`

### 实盘场景

| 场景 | VPS 预期 |
|------|----------|
| ETH R4 @1800，本金 1000U | qty ≈ 2.5 ETH，名义 4500U |
| ETH R2 + XAU R4，本金 1000U | 2500 + 4500 = 7000U（7×，允许） |
| ETH R4 + XAU R4 | 9000U = 9×（踩线允许） |
| 已有 9×，再开新仓 | 拒绝，`combined_notional_exceeded` + 钉钉 |
| 浮盈后本金 1200U | 下次按 1200U × 系数自动放大 |

**测试**：`test_dual_symbol.py::test_margin_coeff_and_open_qty_matches_spec`

---

## 模块三：硬止损（VPS 自主，忽略 TV 紧止损）🔴 P0

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 3.1 | 硬止损 = 开仓价 × 档位百分比 | ✅ | `vps_hard_sl.REGIME_HARD_SL_PCT` |
| 3.2 | 宽止损比例（呼吸空间） | ✅ | 见下表 |
| 3.3 | 多：止损 = entry × (1 − pct) | ✅ | `compute_vps_hard_sl()` |
| 3.4 | 空：止损 = entry × (1 + pct) | ✅ | 同上 |
| 3.5 | 开仓成交后立即挂 Stop-Limit | ✅ | `adverse_radar_guard.py` |
| 3.6 | 止损只收紧不放松 | ✅ | `max(vps_sl, radar)` 合并逻辑 |
| 3.7 | `tv_sl` 仅日志，不用于挂单 | ✅ | `tv_sl_ignored` 元数据 |

### 硬止损比例（占开仓价 %）

| 档位 | 比例 | ETH@1800 示例 |
|------|------|---------------|
| R1 | 2.78% | 1700.0 |
| R2 | 3.89% | 1730.0 |
| R3 | 5.56% | 1700.0 |
| R4 | 8.33% | 1650.1 |

执行：**Stop-Limit**，限价缓冲 0.15%（`HARD_SL_LIMIT_PCT`）。

### 实盘场景

| 场景 | VPS 预期 |
|------|----------|
| XAU R4 @2500 | 止损 ≈ 2291.75（2500 × 8.33%） |
| TV 发来紧 `tv_sl` | 日志 `tv_sl_ignored`，挂单用 VPS 计算价 |
| `UPDATE_SL` | 记录并跳过（`vps_self_managed`） |
| `CLOSE_STOPLOSS` | **第一优先级**立即市价全平 |

**测试**：`test_vps_hard_sl.py` · `test_dual_symbol.py::test_hard_sl_pct_table`

---

## 模块四：雷达移动保本（三重对账 · TP1 后启动）🟡 P1

| # | 检查项 | 状态 | 源码 |
|---|--------|------|------|
| 4.1 | 雷达 **仅 TP1 确认后** 启动 | ✅ | `tp1_filled_from_consumed()` |
| 4.2 | 验证一（主）：WebSocket/REST 价格达到 TP1 | ✅ | `price_reached_tp()` · `get_current_price(prefer_ws=True)` |
| 4.3 | 验证二（辅）：TP1 限价单从订单簿消失 | ✅ | `tp_limit_still_on_book()` 取反 |
| 4.4 | 验证三（参）：仓位数量明显减少 | ✅ | `confirm_tp_tier_fill()` qty 门 |
| 4.5 | 头寸微小变化 **不** 单独触发雷达 | ✅ | `TP_FILL_SLICE_FRAC=0.35` · 半片 TP1 门槛 |
| 4.6 | 启动后止损上移至成本 + 微利 | ✅ | Stage 1 · `BREAKEVEN_BUFFER_PCT=0.1%` |
| 4.7 | TP2/TP3 逐步收紧，保留呼吸空间 | ✅ | Stage 2~5 ATR 追踪 |

### 三重验证逻辑（代码实现）

```
confirm_tp_tier_fill 要求同时满足：
  ① qty_ok   — 减仓量匹配 TP 切片（紧容差，非全仓 8% 漂移带）
  ② book_cleared — 该 TP 限价不在 open orders
  ③ price_ok — mark 价已触及 TP（新推断 tier 时 require_price=True）

任一缺失 → 不标记 TP1 成交 → 雷达 Stage 0（仅硬止损）
```

> **注意**：R4 的 TP1 仅占 5%，仓位变化极微。浮盈/浮亏导致保证金变化 **≠** 数量变化，不可单凭头寸价值变化启动雷达。

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

## 模块五：全局风控（9× 名义硬顶）🔴 P0

| # | 检查项 | 状态 | 配置 |
|---|--------|------|------|
| 5.1 | ETH + XAU 名义 ≤ equity × 9 | ✅ | `MAX_COMBINED_NOTIONAL_MULT=9.0` |
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

配置：`platform_runtime.json` dingtalk.* > `.env DINGTALK_*`  
过滤：`trading_alerts.should_push_trading_dingtalk()`

---

## 完整实盘模拟（Cursor 测试用例）

### 场景 1：正常 TP1 → 雷达 → TP2/TP3

```
1. ETH 1800，R3（15% 保证金，1000U 本金）
2. VPS：margin 150U，名义 3750U，qty ≈ 2.08 ETH
3. 硬止损：1800 × (1 − 5.56%) ≈ 1700
4. 挂 TP1/2/3 限价（R3 比例 18/32/50%）
5. 价格到 TP1，三重验证通过
6. 雷达 Stage 1：止损 → 1800 + 0.1%
7. 价格到 TP2/TP3，Stage 3~5 逐步锁利
```

### 场景 2：插针未成交 → 雷达不启动

```
1. ETH 1800，TP1 = 1980
2. 价格瞬间 1985 后回落 1900
3. price_ok 可能 true，但 book_cleared=false 且 qty 未减
4. 三重验证失败 → 雷达不启动
5. 若最终触及硬止损 1700 → 正常风控离场
```

### 场景 3：双品种 R4 踩线

```
1. 本金 1000U，ETH R4 4500U + XAU R4 4500U = 9000U = 9× → 允许
2. ETH 浮盈后名义 5000U，XAU 新开 4500U → 9500U > 9× → 拒绝
```

### 场景 4：TV 紧止损被忽略

```
1. TV tv_sl=1910（ATR 紧止损）
2. VPS 日志 tv_sl_ignored
3. 实际挂单：entry × (1 − regime_pct)
```

---

## 四所适配对照

| 能力 | Binance | OKX | Gate | DeepCoin |
|------|---------|-----|------|----------|
| OPEN sizing | ✅ | ✅ | ✅ | ✅（张） |
| VPS 硬止损 | ✅ | ✅ | ✅ | ✅ 双轨 |
| 三重 TP1 验证 | ✅ | ✅ | ✅ | ✅ |
| 6 阶段雷达 | ✅ | ✅ | ✅ | ✅ |
| ETH + XAU | ✅ | ✅ | ✅ | ✅ |
| 9× 名义 cap | ✅ | ✅ | ✅ | ✅ |
| 价格 WebSocket | ✅ | ✅ | ✅ | ✅ |

工厂入口：`exchange_factory.create_supervisor()`  
DeepCoin 差异：合约张、`face_value=0.1`、双轨 STOP（TV SL + 雷达条件单并行）。

---

## 优先级与 Cursor 开发指引

| 模块 | 优先级 | 改代码后必跑测试 |
|------|--------|------------------|
| Webhook + 品种路由 | 🔴 P0 | `test_dual_symbol` · `test_webhook_payload` |
| OPEN sizing + 9× cap | 🔴 P0 | `test_dual_symbol` · `test_tv_v6985_sizing` |
| VPS 硬止损 | 🔴 P0 | `test_vps_hard_sl` |
| 三重 TP1 + 雷达 | 🟡 P1 | `test_tp_slice_guard` · `test_radar_trail` |
| 钉钉 | 🟢 P2 | `test_vps_dev_checklist` |

**禁止事项**：

- 不要用 TV `tv_sl` 挂实盘 STOP
- 不要仅凭头寸细微变化（R4 TP1≈5%）启动雷达
- 不要让 ETH 信号路由到 XAU supervisor
- 不要用可用余额代替 total equity 做 OPEN sizing

---

## 相关文件索引

```
backend/app/core/symbol_registry.py      # 品种归一化 + 四所符号表
backend/app/core/tv_entry_sizing.py      # OPEN/ADD  sizing
backend/app/core/vps_hard_sl.py          # 硬止损公式
backend/app/core/tp_slice_guard.py       # 三重 TP 验证
backend/app/core/vps_radar_stages.py     # 雷达 6 阶段
backend/app/core/combined_notional.py    # 9× 名义 cap
backend/app/services/dispatcher.py       # 按用户×品种分发
backend/app/services/webhook_idempotency.py
backend/app/services/trading_alerts.py   # 钉钉
backend/app/core/exchange_factory.py     # 四所工厂
```
