# VPS 实盘最终行为规格（完整版 · 唯一权威）

> 同步：2026-07-23 · **Gemini 终极最终方案（两场景 ATR）** + 连续插值呼吸（ETH 1.2~2.5 / XAU 0.5~1.2）  
> 实现入口：`open_atr_scenario.py`（两场景）· `tv_entry_sizing.py`（算仓）· `breathing_profile.py` · `breathing_stop.py` · `atr_1h_breathing.py` · `adverse_radar_guard.py` · `tp_regime_targets.py`  
> 对照桌面：《Gemini终极最终方案.md》

## 硬性原则

1. 开仓永远先平后开（不问方向；须查询确认仓位归零后再算仓/开仓）
2. 单仓不加仓
3. 仓位每次独立计算（见第三节）：本金×20%×5=名义×1
4. 止损单唯一写入方 = 呼吸止损引擎（开仓瞬间先挂 TV 临时止损，再切精确止损）
5. **算仓铁律（永远）**：合约本金余额 × 20% 作保证金 × 5 杠杆 = **名义 = 本金×1**（`qty = 本金/价`）
6. **initial_atr 两场景**：优先 VPS 原生 1h ATR（场景一）；拉取失败则用 TV `atr` 并挂 TP3（场景二）；tick 可持续升级回场景一并撤 TP3
7. 交易连续性优先：场景二**不暂停**开仓、不拖延告警（仅记录钉钉）

## Webhook action

仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`。

同 symbol：**≤2.5 秒缓存窗口**，CLOSE_* 优先于 LONG/SHORT；窗口内同时到达时一律先平（确认归零）再开。

开仓成功后 **5 秒**内忽略迟到的 `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`（防「开仓先到、平仓后到」误杀新仓）；裸 `CLOSE` 仍有 60s 保护窗。

---

## 一、TV 开仓消息里每个字段分别用在哪

开仓消息（`LONG` / `SHORT`）示例：

```json
{
  "action": "LONG",
  "symbol": "ETHUSDT",
  "price": 1930.49,
  "atr": 14.5,
  "stop_loss": 1916.75,
  "tp1": 1953.51,
  "tp2": 1971.50,
  "tp3": 1988.71
}
```

| 字段 | VPS 怎么用 | 是否参与实际止损价计算 |
|------|------------|------------------------|
| `price` | 开仓参考价 | **否**（算仓用） |
| `atr` | 开仓硬门（须>0）；场景一仅日志参考；**场景二**作为 `initial_atr` | 场景二：**是** |
| `qty` / `qty1` / `qty2` / `qty3` | **完全忽略**（可缺省） | **否** |
| `stop_loss` | 开仓后**临时硬止损**：距离=`|entry−SL|×1.2` | **是**（仅临时阶段） |
| `tp1` / `tp2` | 始终挂限价，数量固定 30%/30% | **否** |
| `tp3` | **仅场景二**挂限价 40%；场景一不挂（雷达追踪） | 场景二挂单价 |

**开仓硬门**：TV `atr` 缺失/≤0/中位数异常 → **拒开仓**（算仓仍需 atr 门禁）。场景一成功后 `initial_atr` 改为 VPS 真实 1h ATR。

---

## 二、开仓两场景（定稿）

### 共同第一步（成交后立即）

1. 用 TV `stop_loss` 放宽 20% 挂**临时硬止损**（禁止裸奔）
2. 挂 TP1/TP2（TV 价 · 30%/30%）；**此时不挂 TP3**
3. 立即拉交易所原生 **1h** K 线算真实 ATR(14)

### 场景一（首选）：VPS 真实 ATR 成功

1. `initial_atr` / `initialStop` = 真实 ATR 重算（`entry ± 1.5×ATR`）
2. 撤临时止损 → 挂精确止损（再 ±0.3/0.5 USDT 挂单缓冲）
3. **不挂 TP3**；阶段二由呼吸引擎动态追踪收网

### 场景二（降级）：VPS 拉取失败

1. **不暂停**该 symbol 开仓；钉钉仅记录（非处理告警）
2. `initial_atr` = TV `atr`；呼吸引擎照常
3. 挂 TP3 限价（TV 价 · 40%）作兜底
4. 每个呼吸 tick 持续重试 VPS 真实 ATR → 成功则切回场景一并**撤销 TP3**

---

## 三、仓位数量计算（开仓算一次，之后不变）

实现：`backend/app/core/tv_entry_sizing.py`

```
保证金 = 账户本金(合约余额) × 20%
名义价值 = 保证金 × 5 = 账户本金 × 1
最终下单数量 = floor(名义价值 / entryPrice) 至交易所精度
```

---

## 四、呼吸止损引擎

实现：`breathing_profile.py`（ETH/XAU 连续插值）+ `breathing_stop.py` + `atr_1h_breathing.py` + `adverse_radar_guard.py` + `open_atr_scenario.py`。

**双雷达：** ETH 与 XAU 共用同一执行引擎；状态 / WebSocket / 1h ATR 拉取 / 呼吸系数按 `canonical_symbol`（及 user）隔离。钉钉与日志带 `[ETH]` / `[XAU]` 标签。

| 参数 | ETH | XAU |
|------|-----|-----|
| 挂单缓冲 | 0.3 | 0.5 |
| 早保本 | 0.5×ATR | 0.3×ATR |
| 阶梯步长/跟进（阶段一，**无 coef**） | 0.75 / 0.4 ×ATR | 0.4 / 0.35 ×ATR |
| 阶段二触发 | 3.0×ATR | 3.0×ATR |
| 呼吸系数区间 (minMult~maxMult) | **1.2 ~ 2.5** | **0.5 ~ 1.2** |
| 冷启动（ratio=1.0） | **1.525** | **0.675** |
| ratioFloor / ratioCeiling | 0.6 / 2.2（共用只读） | 同左 |
| 阶段二追踪 | `initialAtr × coef` | `initialAtr × coef`（**无**额外 ×0.8） |
| 仓位名义 | 余额×20%×5 = 1×余额 | 同左（并存合计 ≈ 2×） |

### 呼吸系数：连续插值（取代旧离散档）

```
smooth_ratio = sma(atr_1h / initial_atr, 3)   # 空历史 → 冷启动 ratio=1.0
trailDistanceMultiplier =
  coef_min                                      if ratio ≤ 0.6
  coef_max                                      if ratio ≥ 2.2
  coef_min + (coef_max−coef_min)×(ratio−0.6)/1.6   otherwise
```

旧离散表（ETH 0.7/0.85/1.0/…、XAU×0.8）**已废除**，不得再作运维依据。

### 阶段一（开仓即呼吸）

```
早保本: 浮盈 ≥ early_be×ATR → 止损锁到 entry±1 tick
step_trigger / step_advance = profile 值 × initialAtr   # 不含 coef
TP1 路径底线 entry±0.5×ATR；TP2 路径底线 entry±1.5×ATR
浮盈 ≥ 3.0×initialAtr → 进入阶段二
```

### 阶段二（自适应追踪）

```
trail_distance = initialAtr × trailDistanceMultiplier(smoothedRatio)
候选 = peak ∓ trail_distance   # 只朝盈利，不倒退
```

### 必须持久化

`entry_price` · `initial_atr` · `initial_stop` · `current_sl` · `best_price` · `breakeven_phase` · `breathing_coefficient` · `step_count` · `remaining_qty_pct` · `breath_ratio_history` · **`atr_scenario`** · **`tp3_limit_active`**

---

## 五、验收命令

```bash
cd backend
py -m pytest tests/test_open_atr_scenario.py tests/test_breathing_stop.py \
   tests/test_continuous_breath_and_atr_lock.py tests/test_continuous_prod_isolation.py \
   tests/test_atr_1h_breathing.py tests/test_pine_tp_regime_ratios.py \
   tests/test_tv_v6985_sizing.py tests/test_vps_entry_routing.py -q
```
