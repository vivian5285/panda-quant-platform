# DeepCoin ↔ Binance 修复对照表（2026-07-22）

> 方式：代码审查 + 针对性单测（DeepCoin 当前无真实资金，不做同等级实盘复测）。  
> DeepCoin 继承 `AdverseRadarMixin` + `PositionCapGuardMixin`，**不**继承 `PositionSupervisor` 本体。

## 总表

| # | Binance 已验证项 | DeepCoin | 证据 / 动作 |
|---|------------------|----------|-------------|
| A | 止损抖动（tick 仅 `improved`；orchestrate 不对齐二次 `force_replace`） | **SYNCED** | 共享 mixin：`adverse_radar_guard.py`；DC sentinel 调同一 tick/orchestrate |
| B | 全平后 `_clear_position_local_state` | **SYNCED（本轮补齐）** | 原 PARTIAL：`_close_all`/manual/dust 已清；TV 对账 flat、重启空仓半清 → 本轮改为 `_clear_position_local_state` |
| C | TP1/TP2 止损 qty 收缩 | **SYNCED（本轮补齐）** | 原 PARTIAL：sentinel→`_orchestrate_qty_change` 已通；TV `_bump_sl_after_tp_reconcile` 曾 soft-stub → 本轮对齐 Binance，调用 `_boost_radar_after_tp_fill` |
| D | 撤旧挂新竞态 pause（`_breath_resize_pause_until`） | **SYNCED** | 继承 boost/tick/orchestrate，无 DC 覆盖 |
| E | CAP_ALIGN detect-only | **SYNCED** | 共享 `PositionCapGuardMixin`；`detect_only_no_trim` |

## 本轮代码改动

1. `position_supervisor_deepcoin.py` `_bump_sl_after_tp_reconcile` → 与 Binance 同逻辑（boost + resize）
2. DeepCoin TV 对账 `live_qty<=0` → `_clear_position_local_state`
3. DeepCoin `recover_state_on_startup` 空仓分支 → `_clear_position_local_state`
4. （顺带）Binance TV 对账 flat 同样改为全量 clear，避免半吊子残留

## 单测

- `backend/tests/test_deepcoin_binance_parity.py`
- 隔离（清单「一」）：`backend/tests/test_user_symbol_isolation.py`（双用户同 ETH + 同用户 ETH/XAU）

## 仍建议观察（非阻塞）

- DeepCoin 遗留 `_ensure_radar_sl` / `_place_radar_sl` API 仍存在，但 `_uses_dual_stop_track()=False`，主路径走 merged stop
- DeepCoin 真实小额验证：等有资金再做；逻辑对齐后风险已大幅下降
