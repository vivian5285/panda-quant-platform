# VPS 实盘增强执行自查清单

> **用途**：Cursor / 运维改代码或上线前逐项对照。  
> **交易所**：Binance · OKX · Gate.io · DeepCoin（统一铁律；DeepCoin 数量单位为「张」）。  
> **一句话**：TV 到达 → **先平后开** → **LIMIT@`price` 开仓** → 挂 **TP123 + 硬止损（各一次）** → **雷达候命** → **钉钉确认**。旧 REGIME_MARGIN / 宽止损 / 雷达解除逻辑已删除。  
> **同步日期**：2026-07-21 · 主文档见仓库根 [`README.md`](../README.md)

---

## 一、核心执行铁律（最重要）

```
TV信号到达 → 先平仓（全部平干净）→ 再开仓 → 挂TP123 + 硬止损 → 雷达候命监控 → 钉钉确认
```

同时到达平仓+开仓：永远**先平后开**。最终必须有 TV 方向仓位，且已挂 TP123 + 硬止损，雷达候命。

| # | 原则 | 源码锚点 |
|---|------|----------|
| P0 | TV 指挥价/风险；VPS 只执行 | `webhook_server` → `dispatcher` → `position_supervisor*` |
| P0 | 先平后开（含同 bar CLOSE→OPEN） | `_force_flat_before_open` · `webhook_seq_gate` |
| P0 | 仓位 = TV `risk_pct`/`qty_ratio`/`leverage` | `tv_entry_sizing.py` |
| P0 | 硬止损 = 严格 `tv_sl`；挂失败撤仓 | `vps_hard_sl.py` · `_protect_and_monitor` |
| P0 | TP123 / 硬止损各挂一次，互不抢份额 | `binance_smart_defense` · `adverse_radar_guard` |
| P1 | 雷达 R1–4 = 50/60/70/80%；只前进不撤 | `radar_trail.REGIME_RADAR` · `_clear_premature_radar_arm`=no-op |
| P1 | 开仓 LIMIT@TV `price`（不足市价补） | `_place_tv_entry_order` |

**一键验收**（`backend/`，Windows 用 `py`）：

```bash
py -m pytest tests/test_vps_entry_routing.py tests/test_webhook_seq.py tests/test_vps_hard_sl.py \
  tests/test_radar_trail.py tests/test_trading_alerts.py tests/test_position_cap_guard.py -q
```

---

## 二、执行顺序（严格）

| 顺序 | 动作 | 说明 |
|------|------|------|
| 1 | 接收 TV | 解析 action、price、tv_sl、tv_tp1/2/3、risk_pct、qty_ratio、regime、leverage |
| 2 | 检查反向/同向刷新 | 有仓则先平；同 bar 有 CLOSE 则先 CLOSE |
| 3 | 平仓干净 | 持仓=0 + 撤尽挂单；**保留本笔 `tv_sl`** |
| 4 | 计算下单量 | 仅用 TV risk 公式 |
| 5 | 开仓 | **LIMIT**，价格=`price`；未足额市价补 |
| 6 | 挂硬止损 | STOP/条件单，触发价=`tv_sl`（只挂一次） |
| 7–9 | 挂 TP1/2/3 | LIMIT reduceOnly（各挂一次） |
| 10 | 启动雷达候命 | 按 regime 路径比例监控（未达则不激活） |
| 11 | 推钉钉 | 含挂载确认三行 |

---

## 三、仓位对照（1000U · ETH≈1892 · qty_ratio=1）

| Regime | risk_pct | 止损距离例 | 下单量约 | 名义约 | 等效杠杆约 |
|--------|----------|------------|----------|--------|------------|
| 1 | 0.81% | 12.08 | 0.67 ETH | 1,268 U | 1.27× |
| 2 | 1.35% | 14.09 | 0.96 ETH | 1,817 U | 1.82× |
| 3 | 2.03% | 14.02 | 1.45 ETH | 2,744 U | 2.74× |
| 4 | 2.70~3.38% | 15.94 | 1.69~2.12 ETH | 3.2k~4.0k U | 3.2~4.0× |

加仓 `qty_ratio=0.3~0.7` 按比例缩小。不同本金按比例换算。  
**禁止** VPS 用 `REGIME_MARGIN` / config 25× 重算仓位。交易所杠杆设为 **TV `leverage`**。

公式：

```
止损距离 = |price − tv_sl|
风险金额 = equity × (risk_pct / 100)
理论仓位 = 风险金额 / 止损距离
杠杆限制 = equity × leverage / price
最终量   = min(理论, 杠杆限制) × qty_ratio
```

（已删除 `maxNotionalUSDT`/`50000` 单笔硬顶；双品种合计仍受 `13×` 权益名义闸。）

---

## 四、组件职责（互不抢份额）

| 组件 | 职责 | 触发 | 互不干扰 |
|------|------|------|----------|
| TP123 | 决定盈利 | 触及 tp1/2/3 平对应仓 | 各档独立限价 |
| 硬止损 | 决定最多亏多少 | 触及 `tv_sl` 全平 | 独立条件单 |
| 雷达 | 守住利润 | 路径达档位%后动态移动 | 只改条件槽；不撤 TP/硬止损挂单逻辑抢权 |

---

## 五、雷达激活（按档位）

| Regime | 激活（entry→TP1） | 动作 |
|--------|-------------------|------|
| 1 | **50%** | 保本监控 |
| 2 | **60%** | 保本监控 |
| 3 | **70%** | 保本 + 移动止损 |
| 4 | **80%** | 保本 + 移动 + 追踪 |

- 价格源：markPrice WebSocket（~0.45s）+ 哨兵兜底  
- 开仓 25s 保护期 + 双轮确认；紧 TP1 抬高有效激活比  
- **挂上后只前进、禁止解除**（`_clear_premature_radar_arm` = no-op）  
- 唯一源码表：`backend/app/core/radar_trail.py` → `REGIME_RADAR`

---

## 六、钉钉推送（OPEN 确认）

每次实盘开仓核实后应含：

```
📊 ETHUSDT 实盘执行确认
方向：LONG/SHORT
Regime：3
开仓价 / 下单量
硬止损价 = tv_sl
TP1/TP2/TP3（含分批%）
TV杠杆：N×（非 config 25×）
等效杠杆：…
硬止损已挂载：✅
TP1/TP2/TP3已挂载：✅
雷达候命：✅
```

实现：`trading_alerts.format_vps_entry_detail_cn` · detail.`mount_confirm`

---

## 七、Cursor 自查清单（必须逐项）

### 7.1 删除旧逻辑
- [ ] VPS 无独立四档 REGIME_MARGIN 算仓
- [ ] VPS 不自算 `risk_pct` / `qty_ratio` / `tv_sl` / tp123
- [ ] 新旧两套逻辑无打架

### 7.2 执行顺序
- [ ] 先平后开；同 bar CLOSE→OPEN
- [ ] 平仓干净后再开；最终有仓
- [ ] 清场不抹掉本笔 `tv_sl`

### 7.3 订单挂载
- [ ] 硬止损 / TP1 / TP2 / TP3 **各挂一次**
- [ ] 互不抢份额；挂在交易所服务器
- [ ] 开仓优先 LIMIT@`price`

### 7.4 雷达
- [ ] 逻辑完整（勿重复造轮）
- [ ] R1–4 = 50/60/70/80%
- [ ] 只做移动止损；不干预 TP123/硬止损挂单权
- [ ] 只前进不撤

### 7.5 各交易所统一
- [ ] 币安 / OKX / Gate / 深币同一铁律

### 7.6 防漏挂
- [ ] 硬止损失败 → 开仓撤掉（禁裸奔）
- [ ] TP 失败记日志，不影响已挂止损
- [ ] 订单有确认 / 钉钉挂载字段

### 7.7 推送确认
- [ ] 钉钉含 TV 杠杆 + 硬止损/TP123/雷达候命确认

### 7.8 链路
- [ ] TV → Webhook → VPS → 交易所通畅
- [ ] `bar_index`+`seq` 去重 / 防重入

---

## 八、相关文件

```
backend/app/core/tv_entry_sizing.py
backend/app/core/vps_hard_sl.py
backend/app/core/radar_trail.py
backend/app/core/adverse_radar_guard.py
backend/app/core/position_supervisor.py
backend/app/core/position_supervisor_deepcoin.py
backend/app/core/position_cap_guard.py
backend/app/services/webhook_seq_gate.py
backend/app/services/trading_alerts.py
```
