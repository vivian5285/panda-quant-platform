# 多交易所 TP 重复挂单排查结论（2026-07-22）

> 对应清单：Gemini 多交易所 TP 重复挂单 bug 同步排查。  
> 事故根因与币安实盘证据见 [TP_DUPLICATE_INCIDENT_20260722.md](TP_DUPLICATE_INCIDENT_20260722.md)。

## 一、三处修复分别落在哪一层

| # | 修复点 | 落点 | 谁受益 |
|---|--------|------|--------|
| 1 | TP 超时：现价未到只刷新 `_tp_placed_at`，不撤单 | **共享** `PositionSupervisor._process_radar_trailing` | Binance / OKX / Gate（同一类，无交易所 override） |
| 2 | `_sync_consumed_tp_levels`：满仓且盘口无对应 TP 时**保留** `consumed` | **共享** `PositionSupervisor._sync_consumed_tp_levels` | 同上 |
| 3 | `_rebuild_tp_limit_orders`：重挂前盘口匹配则跳过 + 先去重 | **共享 Mixin** `BinanceSmartDefenseMixin`（命名遗留；`PositionSupervisor` 混入） | 同上 |

**结论（第一部分）：三处均在 Binance/OKX/Gate 共享层，不在币安专属子类。**  
OKX/Gate **理论上自动同步受益**；仍需下列审查确认「盘口判断」在归一化订单结构上成立。

DeepCoin **不**继承 `PositionSupervisor` / `BinanceSmartDefenseMixin`，有独立副本：

| # | DeepCoin 对应 | 状态 |
|---|---------------|------|
| 1 | `DeepcoinPositionSupervisor._process_radar_trailing` | 已对齐（同逻辑） |
| 2 | `DeepcoinPositionSupervisor._sync_consumed_tp_levels` | 已对齐（同逻辑） |
| 3 | `DeepcoinPositionSupervisor._rebuild_defenses` | **本轮补齐**：此前仅 `_patch_missing_tp_levels` 有「盘口已有则跳过」；核武/`_rebuild_defenses` 缺此检查 → 已移植 + 单测 |

---

## 二、OKX / Gate.io 代码审查结论（书面）

### 继承关系

- `exchange_factory.create_supervisor`：非 DeepCoin → 一律 `PositionSupervisor(...)`  
- Mixins：`PositionCapGuardMixin` + `AdverseRadarMixin` + **`BinanceSmartDefenseMixin`** + `StartupReconcileMixin`  
- 仓库内 **无** OKX/Gate 对 `_process_radar_trailing` / `_sync_consumed_tp_levels` / `_rebuild_tp_limit_orders` 的 override

### 订单字段归一化（「挂单是否存在」能否成立）

共享层 `_collect_tp_limit_orders` / `_is_tp_limit_order` 期望形状：

`type==LIMIT`、`side∈{BUY,SELL}`、`price`、`origQty`、`reduceOnly`、`orderId`

| 交易所 | 归一化入口 | 结论 |
|--------|------------|------|
| OKX | `okx_client._normalize_order` → 上述字段；限价 `ordType=limit` → `type=LIMIT`；qty 已换算为 ETH | **兼容**；TP 识别：`reduceOnly` 或 close-side + `tv_tps` 价匹配 |
| Gate | `gate_client._normalize_order` → 同上；`is_reduce_only`/`reduce_only` → `reduceOnly` | **兼容**；条件单进 `STOP`/`price_orders`，不计入 TP LIMIT 集合（与币安 algo 分离一致） |

**风险备注（非阻塞）：** 未做 OKX/Gate 测试网实锤超时→重建流程；若某所 `reduceOnly` 缺失且 close-side 误标，可能漏计/误计 TP。当前路径与币安共用同一判断，且两所客户端已做 Binance 形归一化，**代码审查认定修复已覆盖 OKX/Gate**。

### 模拟盘建议（可选、非本轮阻塞）

开仓 → 挂 TP1/TP2 → 人为把 `_tp_placed_at` 拨到 >300s 且 mark 未到 TP → 断言：不撤单、不核武叠单。

---

## 三、DeepCoin（本轮强制项）

- [x] 审查三环节：超时 / consumed / 重建 — 1·2 已有；3 在 `_rebuild_defenses` 缺口已补  
- [x] 移植：重建前 `_has_duplicate_tp_orders` 去重 + 价位已存在则跳过（对齐 `_patch_missing` / 币安 rebuild）  
- [x] 单测：`backend/tests/test_deepcoin_tp_rebuild_no_duplicate.py`  
- [x] 对照表更新：见 `DEEPCOIN_BINANCE_PARITY.md` 行 **F**

---

## 四、验收对照本清单

| 项 | 状态 |
|----|------|
| 第一部分定位回答 | **完成**（上表） |
| OKX/Gate 书面审查 | **完成**（第二节） |
| DeepCoin 移植 + 单测 | **完成** |
| `DEEPCOIN_BINANCE_PARITY.md` 更新 | **完成** |
