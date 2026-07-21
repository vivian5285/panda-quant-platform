# VPS 实盘最终行为规格（完整版 · 唯一权威）

> 同步：2026-07-22 · 实现以本文档为准；与「妈妈版」冲突处以本文为准。  
> 实现入口：`tv_entry_sizing.py`（算仓）· `breathing_stop.py`（止损纯函数）· `adverse_radar_guard.py`（挂/改/触发）· `market_engine.py`（90m ATR/ADX）

## 硬性原则

1. 开仓永远先平后开（不问方向）
2. 单仓不加仓
3. 仓位每次独立计算（见第三节）；`initialStop`=VPS ATR；TV `stop_loss` **只**用于 qty 调整系数
4. 止损单唯一写入方 = 呼吸止损引擎（与 TV 止损价无关）

## Webhook action

仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`。

---

## 一、TV 开仓消息里每个字段分别用在哪

开仓消息（`LONG` / `SHORT`）示例：

```json
{
  "action": "LONG",
  "symbol": "ETHUSDT",
  "price": 1900.0,
  "qty": 12,
  "qty1": 3,
  "qty2": 3,
  "qty3": 6,
  "stop_loss": 1860.0,
  "tp1": 1954.0,
  "tp2": 2000.0,
  "tp3": 2044.0
}
```

| 字段 | VPS 怎么用 | 是否参与实际止损价计算 |
|------|------------|------------------------|
| `price` | 开仓参考价；用于算「TV 隐含止损距离」 | **否**，只做换算 |
| `qty` | 三选一算仓的一个候选（须先按第三节换算） | **否**，只影响仓位大小 |
| `qty1` / `qty2` | TP1/TP2 限价止盈挂单数量 | **否** |
| `qty3` | **不使用**（不挂 TP3；余仓交阶段二） | 不适用 |
| `stop_loss` | **只**反推「TV 隐含止损距离」，修正仓位数量；**不是**交易所止损挂单价 | **否**（最易误解，反复强调） |
| `tp1` / `tp2` | TP1/TP2 限价止盈挂单价格 | **否** |
| `tp3` | **不使用** | 不适用 |

**一句话：** 消息里只有 `price` 与 `stop_loss` 做一次减法得到「TV 隐含止损距离」；该距离**唯一**用途是修正仓位数量，**绝不能**当作 VPS 挂在交易所上的止损单价格。

`price` / `stop_loss` 开仓用完即可丢弃（可留日志追溯，但不参与后续任何 tick 级计算）。

---

## 二、VPS 真正用来算止损价的输入（与 TV 无关）

开仓瞬间 VPS **独立**完成（不依赖 TV 的任何数值作止损价）：

1. 拉交易所 **30m** K 线 → 合成 **90m**
2. 算 `initialAtr` = ATR(14)（**开仓这一刻的值，此后全程固定，不再因新 ATR 重算**）
3. 算初始止损：
   - 多：`initialStop = entryPrice − 1.5 × initialAtr`
   - 空：`initialStop = entryPrice + 1.5 × initialAtr`
4. 用 `initialStop` 挂首张止损单，并作为呼吸引擎后续阶梯的**唯一基准**

与 TV `stop_loss` **两条平行路径，零交集**。

---

## 三、仓位数量计算（开仓算一次，之后不变）

实现：`backend/app/core/tv_entry_sizing.py`

```
VPS实际止损距离 = |entryPrice − initialStop| = 1.5 × initialAtr
TV隐含止损距离 = |price − stop_loss|
调整系数 = TV隐含止损距离 / VPS实际止损距离
调整后的TV数量上限 = qty × 调整系数

风险资金 = 账户本金(合约余额) × 20%
名义上限 = 账户本金(合约余额) × 5

理论数量 = min(
    风险资金 / VPS实际止损距离,
    名义上限 / entryPrice,
    调整后的TV数量上限
)
最终下单数量 = 理论数量，向下取整至交易所精度
```

### 为什么需要调整系数

TV.qty 按策略内部止损距（如 `atrMultiplierSL=1.0×ATR`）算出；实盘初始止损是 **1.5×ATR**。若直接 `min(..., TV.qty)`，在 VPS 止损触发时实际亏损会放大约 50%（20% 预算变成约 30%）。调整后，不论 `min()` 取哪项，只要在 VPS 止损价平仓，亏损落在风险资金预算内。

### 约束

| 规则 | 说明 |
|------|------|
| 时机 | **仅开仓一次**；后续价格/ADX 变化不重算仓位 |
| ATR=0 / 止损距=0 | 拒开仓 + 告警暂停该 symbol（防除零） |
| 缺 `qty` / `stop_loss` / `initialStop` | **拒开仓** |
| 杠杆 | 统一 **5×** |
| 日志 | `adjust_coef`、三候选、`binding`、最终 qty |

---

## 四、呼吸止损引擎（开仓后逐 tick；与第三节仓位计算独立）

数量算完即定；**止损价**则持续跟随行情。实现：`breathing_stop.py` + `adverse_radar_guard.py`。

### 4.0 每个 tick

订阅 markPrice / aggTrade；每条新价：

1. 更新极值：`highestPrice`（多）/ `lowestPrice`（空）
2. `breakevenPhase == false` → 阶段一；否则阶段二
3. 仅当新止损「更优」（多更高 / 空更低）才改单；否则本 tick 无操作

ADX 由行情引擎在 **90m K 线闭合**时更新；tick 之间复用上次闭合值。**只有止损价计算每个 tick 跑。**

### 4.1 阶段一（保本前阶梯）

```
step_count = floor((price − entry) / (0.75 × initialAtr))，≥0   # 空单对称
step_stop  = initialStop ± step_count × 0.4 × initialAtr
候选止损   = max/min(当前止损, step_stop)   # 只朝盈利

若 price 越过 entry ± 1.35×initialAtr（约 TP1）：
    候选 ≥/≤ entry ± 0.5×initialAtr     ← TP1 强制底线
若 price 越过 entry ± 2.5×initialAtr（约 TP2）：
    候选 ≥/≤ entry ± 1.5×initialAtr     ← TP2 强制底线

若 price 越过 entry ± 3.0×initialAtr：
    breakevenPhase = true               ← 只升不降，进入阶段二
```

### 4.2 阶段二（ADX 追踪）

```
trail_distance = ADX 在 1.2×ATR ~ 2.5×ATR 插值（ADX 15→1.2，35→2.5）
候选 = highestPrice − trail_distance   # 空：lowest + trail
新止损 = max/min(当前止损, 候选)        # 只朝盈利，不倒退
```

### 4.3 触发平仓

价格触及当前止损 → 市价全平剩余仓位 → 重置该 symbol 呼吸状态 → 钉钉。

另：TP1/TP2 **成交**时订单监控只**通知**引擎：暂停 tick → 撤旧止损 → 按剩余量（约 70%/40%）重挂当前 `currentStop` → 恢复 tick（改的是挂单 **数量**，不是用 TV 价重算止损价）。

### 4.4 必须持久化（重启可恢复）

| 必须持久化 | 开仓后固定 | 可仅日志、不参与 tick |
|------------|------------|------------------------|
| `currentStop`、`highest/lowest`、`breakevenPhase` | `initialAtr`、`initialStop`、`entryPrice` | TV `price`、`stop_loss`、原始 `qty` |

旧雷达 schema（无 `initialAtr` 等）→ 告警并**暂停**该 symbol，不强行转换。

---

## 五、完整时间线

1. **收到 LONG/SHORT：** 解析字段 → 独立算 `initialAtr`/`initialStop` → 调整系数修正 qty → 三选一下单量 → 开仓 → 挂 TP1/TP2 → 呼吸引擎挂首张止损  
2. **开仓后每个 tick：** 第四节计算，止损平滑移动；**不再需要 TV 新数据**  
3. **直到仓位归零：** 止损触发，或 TV `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT` 市价全平  

---

## 六、行情 / 保留删除 / 验收

- 行情：30m → 90m；ATR(14)/ADX(14)；webhook **不读** atr/adx  
- 保留：`HARD_SL_FAIL_ABORT`、`FORCE_ALIGN`  
- 删除：`CAP_ALIGN` 减仓、加仓、旧雷达 activated/2.0ATR、保护性全平、挂 TP3  

```bash
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_close_alert_utils.py -q
```
