# Gemini 事件收尾确认 + 全域复盘（2026-07-22）

**暂停状态：部署后仍保持 `trading_paused`，恢复须你本人明确确认。**

---

## 一、本次事件收尾

### 1.1 部署

| 项 | 状态 |
|----|------|
| commit/push | 见本次提交（含 tv_sl 拆分 / haircut / absurd qty / OPEN_FAILED 原文） |
| VPS 部署 | `git pull` + `docker compose build/up backend`；**保持暂停** |
| health | `status=ok`；HEAD 对齐本次提交 |

### 1.2 `tv_sl` 污染：代码位置与修复方式

**事故写入点（已改）：**

| 文件 | 原行为 | 现行为 |
|------|--------|--------|
| `adverse_radar_guard.py` `_recompute_vps_hard_sl` | `self.tv_sl = VPS 1.5×ATR stop` | 只写 `initial_stop`/`current_sl`/`_tv_hard_sl_price`；**仅**把 payload `stop_loss` 写入 `tv_sl` + `_tv_stop_loss_ref` |
| 同文件 breathing init / tick / recover | 把 `current_sl` 镜像进 `tv_sl` | **禁止**；挂单价只更新 `current_sl`/`_tv_hard_sl_price` |
| `position_supervisor.py` `_resolve_entry_qty` | ATR/sizing 回退 `_tv_hard_sl_price`/`tv_sl`（已被 VPS 污染） | **只读** `_tv_stop_loss_ref` / `_pending_open_tv_sl`（`_pine_stop_loss_ref()`） |
| 开仓失败文案 | 「下单后未检测到持仓」 | `OPEN_FAILED` 钉钉带交易所原文（如 `-2019`） |

**判定：** 修复目标是「**禁止非 TV 来源写入 `tv_sl`**」+「挂单价走独立字段」；不是仅对 ATR 一条路径打补丁。  
遗留：少数日志/详情仍**读取** `tv_sl` 作展示；挂单执行路径已优先 `current_sl`/`_exchange_stop_px()`。DeepCoin 旁路仍有历史镜像逻辑，需同样标准后续对齐（本轮 Binance 主路径已收紧）。

### 1.3 其他 `tv_*` / 易混淆字段全局排查

| 字段 | 写入来源 | 纯净性 | 说明 |
|------|----------|--------|------|
| `tv_sl` | **应仅** webhook `stop_loss` | ✅ 本轮强制 | 曾被 VPS 止损污染（事故根因） |
| `_tv_stop_loss_ref` / `_pending_open_tv_sl` | webhook `stop_loss` | ✅ | ATR/sizing 专用 |
| `_tv_hard_sl_price` | VPS hang（命名历史包袱） | ⚠️ 名不副实 | 实为交易所挂单价镜像；读挂单请用 `_exchange_stop_px()` |
| `tv_price` | webhook `price` / 恢复日志 | ✅ | 未发现 VPS 行情覆写 |
| `tv_tps` | webhook tp1/2/3 / 恢复 | ✅ | 价格来自 TV；数量另算 |
| `_tv_entry_fields.tv_qty*` | webhook qty/qty1/2/3 | ✅ | 只作上限输入；最终 qty 走公式 |
| `current_atr` / `initial_atr` | VPS 90m 引擎（或应急降级） | ✅ 来源明确 | 非 tv_ 前缀；降级会改值并告警 |
| `current_sl` / `initial_stop` | 呼吸引擎 | ✅ | 非 TV |

**跨用户/symbol：** 每 supervisor 实例绑定 `user_id+symbol`，`tv_*` 为实例字段，**不会跨用户共享内存**。

### 1.4 名义 0.85 haircut

- 位置：`tv_entry_sizing.py` → `NOTIONAL_MARGIN_HAIRCUT = 0.85`  
  `notional_cap = equity × 5 × 0.85`，经 `compute_tv_entry_qty` → `resolve_vps_entry_qty_eth` / `_deepcoin`  
- 生效路径：Binance / DeepCoin 开仓 sizing、`position_cap_guard` 检测用同一公式  
- **不**改变风险腿 `equity×20%/止损距`

### 1.5 荒谬 qty 阈值

- `ABSURD_TV_QTY_VS_CAPS = 50`  
- 判定：`adjusted_tv_qty > max(qty_by_risk, qty_by_notional) × 50`  
- 依据：正常 TV.qty 调整后应与 risk/notional 同量级；`8.6e8` 相对 ~0.1–4 ETH 差 **>1e8 倍**，50× 已远超任何合理策略权益膨胀，同时避免误伤「略大于名义上限」的合法 TV.qty

### 1.6 失败返回交易所原文

- `binance_client.place_market_order` 记录 `_last_market_order_error` + params  
- `_open_position` 失败 → `_alert(OPEN_FAILED, message=市价开仓失败: …)`  
- 钉钉可见 `-2019 Margin is insufficient` 一类原文（不再只剩 DISPATCH 笼统句）

---

## 二、全域功能复盘

| # | 项 | 判定 |
|---|-----|------|
| 2.1 先平后开 | **仍然符合** | `_force_flat_before_open` 未改语义 |
| 2.1 独立算仓不采信 TV.qty 终值 | **仍然符合**（加强） | 唯一公式 `compute_tv_entry_qty`；荒谬 qty 忽略 TV 上限；无第二套直接下单 TV.qty 路径（Binance） |
| 2.1 单仓不加仓 | **仍然符合** | ENTRY_TYPES_ADD 空 |
| 2.1 止损唯一写入 / 价格未被污染连带 | **仍然符合** | 挂单价用 `current_sl`/`initial_stop`；事故污染的是 ATR **比对引用**，非挂单价公式改回 entry |
| 2.2 sizing/显示/字段同源 | **部分加强** | 预览/执行共用公式；`tv_sl` 拆分后 ATR 不再吃 VPS 价；钉钉失败带原文 |
| 2.2 无状态 sizing | **仍然符合** | `compute_tv_entry_qty` 纯函数 |
| 2.3 webhook 4 action / secret / seq / 60s | **仍然符合** | 未改 webhook_guard |
| 2.4 先平后开+重试 | **仍然符合** | |
| 2.4 haircut∩三选一 | **仍然符合** | haircut 只缩 notional 腿 |
| 2.5 呼吸抖动/重启/TP收缩/防重复 | **仍然符合** | 回归：`test_breathing_stop` + TP 相关单测 |
| 2.5 阶梯基准 initialStop | **仍然符合** | `breathing_stop.py` 仍用 `initial_stop`，非 entry |
| 2.6 全平清零 / get_position fail-closed | **仍然符合** | |
| 2.7 钉钉 5× / 归因 / 旧文案 | **仍然符合** | + OPEN_FAILED 原文 |
| 2.8 SHORT / 多用户隔离 | **仍然符合** | sizing 对称；字段 per-supervisor |

---

## 三、极端输入健壮性

### 已补测试

- `tests/test_absurd_tv_qty_sizing.py` — 8.6e8、final≡order  
- `tests/test_extreme_webhook_inputs.py` — qty≤0、price=0、止损距为 0、字段解析、SHORT 距  

### 架构性防污染（常态化）

1. **命名契约：** `tv_*` = webhook 快照；`current_*`/`initial_*` = 引擎状态；禁止交叉赋值（本轮对 `tv_sl` 落地）  
2. **读写 API：** `_pine_stop_loss_ref()` / `_exchange_stop_px()` — 新代码禁止直接混读  
3. **后续：** DeepCoin 镜像路径对齐；对 `_tv_hard_sl_price` 考虑重命名为 `exchange_stop_px`（破坏性，可另 PR）  
4. **待补边界（非阻塞）：** webhook schema 校验单测、tp 方向颠倒拒单、body 非 JSON  

---

## 四、恢复交易门禁

- [x] 第一部分确认（含 tv_ 排查）  
- [x] 第二部分逐条判断  
- [x] 第三部分用例 + 架构方案  
- [ ] **解除暂停：须你本人明确确认后执行**
