# VPS 实盘最终行为规格（完整版 · 唯一权威）

> 同步：2026-07-23 · 雷达呼吸升级（TV atr + 1h 呼吸系数）  
> 实现入口：`tv_entry_sizing.py`（算仓）· `breathing_stop.py`（止损纯函数）· `atr_1h_breathing.py`（1h ATR）· `adverse_radar_guard.py`（挂/改/触发）· `webhook_symbol_coalesce.py`（≤2.5s 缓存）

## 硬性原则

1. 开仓永远先平后开（不问方向；须查询确认仓位归零后再算仓/开仓）
2. 单仓不加仓
3. 仓位每次独立计算（见第三节）：本金×20%×5=名义×1
4. 止损单唯一写入方 = 呼吸止损引擎（与 TV 止损价无关）
5. **算仓铁律（永远）**：合约本金余额 × 20% 作保证金 × 5 杠杆 = **名义 = 本金×1**（`qty = 本金/价`）
6. **initial_atr** = TV webhook `atr`（开仓冻结）；阶段二用币安原生 **1h ATR** 驱动呼吸系数

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
  "price": 1900.0,
  "atr": 20.0,
  "qty": 12,
  "qty1": 3,
  "qty2": 3,
  "qty3": 6,
  "stop_loss": 1880.0,
  "tp1": 1930.0,
  "tp2": 1960.0,
  "tp3": 2000.0
}
```

| 字段 | VPS 怎么用 | 是否参与实际止损价计算 |
|------|------------|------------------------|
| `price` | 开仓参考价 | **否**（算仓用） |
| `atr` | **冻结为 `initial_atr`**（呼吸止损基准） | **是**（倍数基准，非直接挂单价） |
| `qty` | **仅校验存在**；下单数量由 VPS 本金×20%×5 独立计算 | **否** |
| `qty1` / `qty2` | TP1/TP2 限价止盈挂单数量 | **否** |
| `qty3` | **不使用**（不挂 TP3；余仓交阶段二） | 不适用 |
| `stop_loss` | ATR 应急降级参考（TV 无 atr 时）；**不挂止损** | **否** |
| `tp1` / `tp2` | TP1/TP2 限价止盈挂单价格 | **否** |
| `tp3` | **不使用** | 不适用 |

---

## 二、VPS 真正用来算止损价的输入

开仓瞬间：

1. 读 TV webhook **`atr`** → `initialAtr`（冻结，全程不变）
2. 初始逻辑止损：多 `entry − 1.5×initialAtr` / 空对称
3. **挂单缓冲**：多再 −0.3 USDT / 空再 +0.3 USDT（仅交易所挂单价）
4. 拉币安原生 **1h** K 线算 ATR(14)，每 5 分钟刷新；`ratio = atr_1h / initialAtr` 取最近 3 次 SMA → 呼吸系数

TV `stop_loss` **不参与**挂单价。

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

实现：`breathing_stop.py` + `atr_1h_breathing.py` + `adverse_radar_guard.py`。

### 呼吸系数档位（`smooth_ratio = sma(atr_1h / initial_atr, 3)`）

| smooth_ratio | 呼吸系数 |
|--------------|----------|
| < 0.7 | 0.7 |
| 0.7 ~ 1.0 | 0.85 |
| 1.0 ~ 1.4 | 1.0 |
| 1.4 ~ 2.0 | 1.2 ~ 1.4（线性） |
| ≥ 2.0 | 1.5 |

### 阶段一（保本前）

```
step_trigger = 0.75 × initialAtr × coef
step_advance = 0.4 × initialAtr × coef
TP1 路径底线 entry±0.5×ATR；TP2 路径底线 entry±1.5×ATR
浮盈 ≥ 3.0×initialAtr → 进入阶段二
```

### 阶段二（自适应追踪）

```
trail_distance = initialAtr × coef
候选 = peak ∓ trail_distance   # 只朝盈利，不倒退
```

### 必须持久化

`entry_price` · `initial_atr` · `initial_stop` · `current_sl` · `best_price` · `breakeven_phase` · `breathing_coefficient` · `step_count` · `remaining_qty_pct` · `breath_ratio_history`

---

## 五、验收命令

```bash
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_atr_1h_breathing.py \
   tests/test_open_close_grace.py tests/test_webhook_coalesce.py \
   tests/test_tv_v6985_sizing.py tests/test_vps_entry_routing.py -q
```
