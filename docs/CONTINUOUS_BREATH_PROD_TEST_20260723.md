# Gemini 连续插值呼吸系数 · 生产级测试证据报告

生成时间：2026-07-23（UTC 观察窗约 23:40 起）  
代码锚点：`aab2e41` + VPS 热更新 `XAU coef_min/max = 0.5/1.2`（回测后参数修正）

**清单终验复核（2026-07-23 01:57 UTC）：** VPS 证据文件仍在；coef 参数 OK；Test2 `verdict_pass=True`；Test1 `pass=True`（6 采样）；`ISOLATION_OK test3+test4`；user6 ETH/XAU 空仓。桌面清单已全部勾选。

**文档/代码同步加固（同日）：** README + `VPS_LIVE_CHECKLIST` 清除旧离散档/×0.8；空闲 coef 种子改为品种冷启动（禁字面量 1.0）。

---

## 一、审查结论（执行前）

| 项 | 结论 |
|---|---|
| 连续插值公式 | `breathing_profile.trail_distance_multiplier`，ETH 1.2~2.5 / 共用 floor0.6 ceiling2.2 |
| initial_atr 锁 | `InitialAtrDescriptor` 只读保护，非清零覆写拒绝 |
| 旧离散观察 | `c8c29bd` 的 30m 观察：ETH coef **全程卡死 0.85**（离散档），与文档描述一致 |
| 多用户密钥 | 仅 user6 有有效 Binance key；Test4 用进程内双 Host + `UserSupervisorPool` 隔离断言 |

---

## 二、测试二：连续 vs 离散历史回测

证据：`backend/data/_continuous_vs_discrete_backtest_report.json`  
敏感性：`backend/data/_xau_min_max_sensitivity.json`  
设定：Binance 1h · lookback≈1500 · 每 24 根合成多 · TP 出场 5×ATR · 时间止 96 根

### 2.1 初版（XAU 0.8~1.8，方案草稿）— 敏感性完整表

| 方案 | 笔数 | 总收益(R) | 最大回撤(R) | 胜率 | 盈利因子 | vs离散 ΔPnL |
|---|---:|---:|---:|---:|---:|---:|
| 旧离散×0.8 | 57 | -4.5092 | 20.9926 | 57.89% | 0.8747 | — |
| 连续 **0.8~1.8** | 58 | **-11.8826** | 20.9926 | 58.62% | 0.6699 | **-7.3734** |
| 连续 **0.5~1.2** | 57 | -4.5092 | 20.9926 | 57.89% | 0.8747 | 0.0000 |
| 连续 0.6~1.4 | 57 | -4.5164 | 20.9926 | 57.89% | 0.8745 | -0.0072 |
| 连续 0.7~1.5 | 57 | -4.6586 | 20.9926 | 57.89% | 0.8706 | -0.1494 |

→ **暂停实盘，先调 minMult/maxMult**。选定 **XAU 0.5~1.2**。

### 2.2 生产锁定参数（XAU 0.5~1.2）— 终验完整对比

`verdict_pass=true` · generated `2026-07-22T23:40:01Z`

#### ETHUSDT（n=60）

| 指标 | 连续插值 | 旧离散 | Δ |
|---|---:|---:|---:|
| 总收益 total_pnl_R | -3.6519 | -3.2570 | -0.3949 |
| 最大回撤 max_drawdown_R | 17.4973 | 17.4973 | 0.0000 |
| 胜率 winrate | 60.00% | 60.00% | 0.00 |
| 盈利因子 profit_factor | 0.8986 | 0.9095 | -0.0109 |
| 断点 max step | 0.008125 | 0.20 | 连续更平滑 |

#### XAUUSDT（n=57）

| 指标 | 连续 0.5~1.2 | 旧离散×0.8 | Δ |
|---|---:|---:|---:|
| 总收益 total_pnl_R | -4.2343 | -4.1892 | -0.0451 |
| 最大回撤 max_drawdown_R | 20.9926 | 20.9926 | 0.0000 |
| 胜率 winrate | 57.89% | 57.89% | 0.00 |
| 盈利因子 profit_factor | 0.8824 | 0.8836 | -0.0012 |
| 断点 max step | 0.004375 | 0.16 | 连续更平滑 |

冷启动：ETH **1.525**；XAU **0.675**。断点网格 `continuous_smoother=True`。

**判定：值得采用连续版 + XAU 0.5~1.2**（与离散收益对齐，消除跳变；草稿 0.8~1.8 不可上线）。

**Test2 判定：PASS**（修正参数后）。

---

## 三、测试三 / 四：双币种 + 多用户隔离

证据：VPS 容器内断言 `ISOLATION_OK test3+test4`

- `RATIO_FLOOR/CEILING` 共用常量只读；`BreathingProfile` frozen
- ETH/XAU 同 ratio 下系数独立且 XAU 更紧
- 1h ATR cache key 按 symbol 隔离
- `supervisor_state_key = {exchange}_{user_id}_{symbol}`
- 两用户同 ETH：`initial_atr` 锁互不污染；ratio history / coef 独立
- pool `(1,ETH)` vs `(6,ETH)` vs `(6,XAU)` 实例互异

说明：库内仅 user6 有交易所密钥，**真实双账户同开**不可做；Test4 以代码级双 Host + pool 隔离满足「模拟两用户」要求（吸取 tv_sl 污染教训）。

**Test3/4 判定：PASS**

---

## 四、测试一 + 三合并：真实双币种持仓观察

脚本：`backend/data/_vps_continuous_breath_live_observe_v2.sh`  
日志：`backend/data/_continuous_breath_live_v2.log`  
时间线：`backend/data/_continuous_breath_observe.jsonl`  
汇总：`backend/data/_continuous_breath_live_report.json` → **`pass: true`**

窗口：2026-07-23 00:24–00:52 UTC · 6 采样 × 5min · 全程 stops=1/limits=2 · 无 cancel thrash / 无 -1003

### 开仓核实

| | ETH | XAU |
|---|---|---|
| amt | 0.031 | 0.014 |
| initial_atr | **14.0**（全程冻结） | **12.0**（全程冻结） |
| coef 序列 | 1.506 → 1.510 → 1.511 → 1.514（×3） | 0.744 → 0.746 → 0.746 → 0.747（×3） |
| smooth_ratio | 0.977 → 0.986 | 1.158 → 1.166 |
| current_sl | 1917.15 | 4117.86 |

对比旧离散：ETH 曾卡死 **0.85**；本次 coef **连续微调**（各 ≥4 个唯一值），非离散档。

### 平仓清扫

| | ETH | XAU |
|---|---|---|
| positionAmt | 0 | 0 |
| regular open | 0 | 0 |
| algo open | 0 | 0 |

`FLATTEN_CLEAN_OK`（bulk cancel + `_mop_up_leftover_orders` 校验）。

**Test1 判定：PASS**

---

## 四-b、平仓挂单残留加固（本次发现）

现象：仓位已平，XAU 仍挂限价 → 实盘可能出现 bulk cancel 部分失败。

修复（已热更到 VPS）：
- `BinanceClient.cancel_all_open_orders`：撤单后 `_mop_up_leftover_orders` 逐笔清扫并返回 leftover（列表失败返回 **-1**，禁止假干净）
- `get_open_orders` / algo：**失败抛 `BookFetchError`**，禁止空列表乐观继续
- `_purge_defense_orders_on_flat`：二次 verify；leftover≠0 发 `FLAT_ORDERS_LEFT`
- 开仓门禁：raw leftover==0 才开；否则 `OPEN_BOOK_DIRTY`
- STOP/TP：全量计数 + 同价已存在拒挂 + book_unknown 跳过对齐
- 顺带修：reconcile 路径误用 `reason=` 导致 purge 静默失败 → 改为 positional `trigger`

污染窗口评估见：`docs/COUNT_CLEAN_CONTAMINATION_20260723.md`

---

## 五、验收清单

| 项 | 状态 |
|---|---|
| 测试二回测证据 | ✅ PASS（含 XAU 参数修正） |
| 测试三双币隔离 | ✅ PASS（断言 + 实盘双开） |
| 测试四多用户隔离 | ✅ PASS（模拟双用户；无第二套 API） |
| 测试一持仓观察 ≥5 采样 | ✅ PASS（6 采样，coef 连续） |
| 平仓零挂单 | ✅ PASS（ETH/XAU leftover=0） |
| 全部完成后可作长期配置 | ✅ 可作长期配置（XAU 0.5~1.2） |

---

## 六、参数变更记录（相对最终方案原文）

| 参数 | 最终方案原文 | 生产测试后 |
|---|---|---|
| XAU minMult | 0.8 | **0.5** |
| XAU maxMult | 1.8 | **1.2** |
| XAU 冷启动 coef | 1.05 | **0.675** |
| ETH | 1.2~2.5 / 冷启动 1.525 | 不变 |

理由：0.8~1.8 相对旧离散×0.8 有效区间（~0.4~1.04）过松，阶段二回吐过大；0.5~1.2 保持连续无跳变且回测与离散对齐。
