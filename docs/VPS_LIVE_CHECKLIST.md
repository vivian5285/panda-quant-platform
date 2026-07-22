# VPS 实盘最终行为规格（完整版 · 唯一权威）

> 同步：2026-07-23 · 实现以本文档为准；与「妈妈版」冲突处以本文为准。  
> 实现入口：`tv_entry_sizing.py`（算仓）· `breathing_stop.py`（止损纯函数）· `adverse_radar_guard.py`（挂/改/触发）· `market_engine.py`（90m ATR/ADX）· `webhook_symbol_coalesce.py`（1s 缓存）

## 硬性原则

1. 开仓永远先平后开（不问方向；须查询确认仓位归零后再算仓/开仓）
2. 单仓不加仓
3. 仓位每次独立计算（见第三节）：本金×20%×5=名义×1；`initialStop`=VPS ATR 仅挂止损
4. 止损单唯一写入方 = 呼吸止损引擎（与 TV 止损价无关）
5. **算仓铁律（永远）**：合约本金余额 × 20% 作保证金 × 5 杠杆 = **名义 = 本金×1**（`qty = 本金/价`）

## Webhook action

仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`。

同 symbol：**1 秒缓存窗口**，CLOSE_* 优先于 LONG/SHORT；窗口内同时到达时一律先平（确认归零）再开；超时不无限等待。

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
| `qty` | **仅校验存在**；下单数量由 VPS 本金×20%×5 独立计算 | **否** |
| `qty1` / `qty2` | TP1/TP2 限价止盈挂单数量 | **否** |
| `qty3` | **不使用**（不挂 TP3；余仓交阶段二） | 不适用 |
| `stop_loss` | ATR 应急降级参考；**不算仓、不挂止损** | **否** |
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
保证金 = 账户本金(合约余额) × 20%
名义价值 = 保证金 × 5 = 账户本金 × 1
最终下单数量 = floor(名义价值 / entryPrice) 至交易所精度
```

`initialStop` / TV `stop_loss` / TV `qty` **不算仓**（止损挂单价仍用 VPS `initialStop`；`qty` 仅校验信号存在）。

### 约束

| 规则 | 说明 |
|------|------|
| 时机 | **仅开仓一次**；后续价格/ADX 变化不重算仓位 |
| 本金 | **合约本金余额** = U 本位合约总权益（`read_contract_equity`）；非可用保证金 |
| 缺 `qty` | **拒开仓**（字段存在性；不读其数值算仓） |
| ATR=0 无法挂止损 | 拒开仓 / ATR 应急降级流程 |
| 杠杆 | 统一 **5×** |
| 日志 | `notional_target`、`binding=margin20_lev5`、最终 qty |

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
- **90m 锚点（已实现）**：`bucket = (open_time_ms // 5_400_000) * 5_400_000`（UTC Unix epoch 地板，非进程启动时刻）。因 `1440÷90=16`，UTC 日界自然对齐。上线前须与 TV 90m 图逐根核对 `open_time`（见附件）。  
- 保留：`HARD_SL_FAIL_ABORT`、`FORCE_ALIGN`  
- 删除：`CAP_ALIGN` 减仓、加仓、旧雷达 activated/2.0ATR、保护性全平、挂 TP3  

```bash
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_close_alert_utils.py \
  tests/test_webhook_bar_time.py -q
```

---

## 附件 · 实现细节严谨性检查（三项）

> 非架构变更；策略参数与止损引擎逻辑不变。开发/模拟盘逐项确认。

### ATR 应急降级（临时 · 非静默）

| 触发（任一） | 行为 |
|--------------|------|
| VPS ATR 无效/缺失 | 若有 TV `stop_loss` → 本笔用 TV隐含ATR，钉钉 `ATR_FALLBACK`，开仓后暂停 |
| VPS ATR < 中位数×0.3 | 同上 |
| 连续 `ATR_FALLBACK_STREAK`(默认3) 次开仓信号 Δ≥`ATR_FALLBACK_MISMATCH_PCT`(默认20%) | 同上 |
| 无 TV stop 可反推 | **仍拒开仓**（不静默换源） |

- TV隐含ATR = `|price−stop_loss| / TV_STOP_ATR_MULT`（默认 1.0）
- `initialStop` / 呼吸倍数仍按 **1.5× / 0.75×…** 计算，**只换 ATR 数值来源**
- 恢复：人工确认 VPS ATR 正常后手动解除 `trading_paused`
- 实现：`atr_emergency_fallback.py` + `PositionSupervisor._resolve_entry_qty`

### 一、90 分钟合成 K 线边界对齐（阻塞上线）

| 项 | 状态 |
|----|------|
| 实现 | UTC epoch 90m 地板桶（见上）；`utc_90m_bucket_ms` + 单测覆盖非零日界 |
| 上线前人工验证 | 取历史段：TV 90m vs VPS `bar_open_ms` 逐根对齐；抽样 ATR/ADX 误差 **≤5%** |
| ATR 双边告警 | `ATR_MISMATCH` 用 `TV_STOP_ATR_MULT`（默认 **1.0**）反推 TV 隐含 ATR；**勿**用 VPS 挂单 1.5×。2026-07-22 钉钉 Δ≈33% 为误用 1.5 反推的假阳性（\|1−1/1.5\|） |
| 未通过 | **禁止凑合上线**；先改锚点再复验 |

### 先平后开失败（与 `HARD_SL_FAIL_ABORT` 对等）

| 项 | 行为 |
|----|------|
| 重试 | 平仓未归零 → 间隔 `FORCE_FLAT_RETRY_DELAYS_SEC`（默认 1,3,6）共 3 次 |
| 仍失败 / 挂单残留 | **中止本次开仓** + 钉钉 `FLIP_CLEAN_ABORT`（需人工介入）+ `_pause_trading` |
| 禁止 | 仓位/挂单状态不明时继续开新仓 |

### 二、Webhook `bar_time` 乱序兜底（非阻塞）

| 项 | 状态 |
|----|------|
| 字段 | 可选 `"bar_time": <ms>`（或 Pine `time`）；缺省不拦截 |
| 行为 | OPEN：若 `bar_time` < 该 symbol 已接受水位 → `ignored/stale_bar_time`，不交易 |
| CLOSE | **永不**因过期丢弃（反转保护优先）；仅向前推进水位 |
| 实现 | `webhook_bar_time.py` + `webhook_server` |

### 三、ATR 异常值兜底（阻塞上线 · 已实现）

| 项 | 状态 |
|----|------|
| ATR≤0 / 缺失 / < 中位数×0.3 | **优先**走「ATR 应急降级」：有 TV stop → 本笔用 TV 隐含 ATR 开仓 + `ATR_FALLBACK` + 随后暂停该 symbol；**无** TV stop 可反推 → 拒开仓 + `ATR_INVALID`/`ATR_ANOMALY`（不永久暂停全局） |
| 与 README「VPS 行情引擎 · ATR 容错」 | 已对齐为上述两级策略（勿再写「一律拒开仓」） |
| 实现 | `atr_emergency_fallback.py` → 失败则 `open_atr_guard.check_open_atr_or_reject` |
| 配置 | `ATR_MEDIAN_LOOKBACK=50`、`ATR_MEDIAN_FLOOR_RATIO=0.30`；K 线拉取 ≥250 根 30m |
| 实现 | `evaluate_atr_sanity` + `open_atr_guard`（全交易所共用） |

| 项目 | 优先级 | 阻塞上线 |
|------|--------|----------|
| 90m 边界对齐验证 | 高 | 是（人工核对仍待做） |
| `bar_time` 序号 | 中 | 否 |
| ATR 异常兜底 | 高 | 是（代码已落地） |