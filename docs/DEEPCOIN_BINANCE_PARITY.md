# DeepCoin ↔ Binance 修复对照表（2026-07-22）

> 方式：代码审查 + 针对性单测（DeepCoin 当前无真实资金，不做同等级实盘复测）。  
> DeepCoin 继承 `AdverseRadarMixin` + `PositionCapGuardMixin`，**不**继承 `PositionSupervisor` 本体 / `BinanceSmartDefenseMixin`。  
> 多所定位全文：[TP_MULTI_EXCHANGE_AUDIT.md](TP_MULTI_EXCHANGE_AUDIT.md)

## 总表

| # | Binance 已验证项 | DeepCoin | 证据 / 动作 |
|---|------------------|----------|-------------|
| A | 止损抖动（tick 仅 `improved`；orchestrate 不对齐二次 `force_replace`） | **SYNCED** | 共享 mixin：`adverse_radar_guard.py`；DC sentinel 调同一 tick/orchestrate |
| B | 全平后 `_clear_position_local_state` | **SYNCED** | `_close_all`/manual/dust/TV flat/重启空仓 → `_clear_position_local_state` |
| C | TP1/TP2 止损 qty 收缩 | **SYNCED** | sentinel→`_orchestrate_qty_change`；TV `_bump_sl_after_tp_reconcile` → `_boost_radar_after_tp_fill` |
| D | 撤旧挂新竞态 pause（`_breath_resize_pause_until`） | **SYNCED** | 继承 boost/tick/orchestrate，无 DC 覆盖 |
| E | CAP_ALIGN detect-only | **SYNCED** | 共享 `PositionCapGuardMixin`；`detect_only_no_trim` |
| F | **TP 重复挂单防护**（超时不误撤、满仓保留 consumed、重建前盘口存在则跳过） | **SYNCED（本轮补齐 #3）** | ①② DC 独立实现已对齐；③ `_rebuild_defenses` 本轮补「去重 + 已存在跳过」（此前仅 `_patch_missing` 有）。单测见下 |

## 本轮代码改动（TP 重复 · DeepCoin #3）

1. `position_supervisor_deepcoin.py` `_rebuild_defenses`：重建前 `_purge_duplicate_tp_orders`；价位已有匹配限价则跳过（对齐币安 `_rebuild_tp_limit_orders`）
2. 单测 `backend/tests/test_deepcoin_tp_rebuild_no_duplicate.py`
3. 多所审查文档 `docs/TP_MULTI_EXCHANGE_AUDIT.md`

## 单测

- `backend/tests/test_deepcoin_binance_parity.py`
- `backend/tests/test_deepcoin_tp_rebuild_no_duplicate.py`
- `backend/tests/test_tp_rebuild_no_duplicate.py` / `test_tp_timeout_no_thrash.py`（币安共享层）
- 隔离：`backend/tests/test_user_symbol_isolation.py`

## 仍建议观察（非阻塞）

- DeepCoin 遗留 `_ensure_radar_sl` / `_place_radar_sl` API 仍存在，但 `_uses_dual_stop_track()=False`，主路径走 merged stop
- DeepCoin / OKX / Gate 真实小额或测试网：超时→哨兵→确认无叠 TP（可选）
