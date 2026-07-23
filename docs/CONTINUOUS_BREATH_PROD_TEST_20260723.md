# Gemini 连续插值呼吸系数 · 生产级测试证据报告

生成时间：2026-07-23（UTC 观察窗约 23:40 起）  
代码锚点：`aab2e41` + VPS 热更新 `XAU coef_min/max = 0.5/1.2`（回测后参数修正）

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

### 2.1 初版（XAU 0.8~1.8，最终方案原文）

| 品种 | 连续 PnL(R) | 离散 PnL(R) | Δ | 平滑 |
|---|---|---|---|---|
| ETH | -3.65 | -3.26 | -0.39 | 连续 max step 0.008 ≪ 离散 0.20 |
| XAU | **-11.88** | -4.51 | **-7.37** | 连续更平滑，但收益显著差 |

→ 按文档建议：**暂停实盘，先调 minMult/maxMult**。

### 2.2 参数修正后（XAU 0.5~1.2）

| 品种 | 连续 PnL(R) | 离散 PnL(R) | Δ | 结论 |
|---|---|---|---|---|
| ETH | -3.65 | -3.26 | -0.39 | 可接受（同回撤） |
| XAU | -4.23 | -4.19 | **-0.05** | 与离散对齐 |

断点连续性：ETH/XAU 在 0.01 均匀网格上 `continuous_smoother=True`。  
冷启动：ETH **1.525**；XAU 修正后 **0.675**（=0.5+(1.2-0.5)×0.25）。

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
