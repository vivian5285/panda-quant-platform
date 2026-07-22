# TP 重复挂单紧急排查报告（2026-07-22）

## 现象

ETHUSDT 出现两组相同价位的 TP1/TP2 限价卖单（约间隔 50 分钟）。止损单保持 1 笔正常。

## 根因（已用 VPS 日志证实）

**不是**止损 `force_replace` 那一类问题，而是 **TP 5 分钟超时撤单 + consumed 被误清 + 定期核武重挂** 的闭环：

1. 开仓挂 TP1/TP2，写入 `_tp_placed_at`
2. ~300s 后 `_process_radar_trailing` **超时撤掉**仍有效的限价 TP（现价未到）
3. 将档位写入 `consumed_tp_levels`，并曾错误地把 `remaining_qty_pct` 缩成 0.4（当成成交）
4. `_sync_consumed_tp_levels` 见 `live_qty == initial_qty` 且现价未过 TP → **清空 consumed**（误判「仓位回到开仓锚」）
5. 哨兵定期扫描发现 TP「缺失」→ `_smart_realign` → **核武清场重挂** 再挂 2 笔
6. 若撤单 API 滞后而重挂已成功 → 盘口叠出 **重复 TP**

日志特征（每 ~5 分钟）：
`cancel order …` → `定期扫描发现异常: TP1/TP2 缺失` → `核武级重挂` → `新挂 2 笔`

## 修复（已热更 VPS）

| 项 | 改动 |
|----|------|
| 超时逻辑 | 现价**未到** TP 时只刷新 stamp，**不撤单**；仅现价已过仍挂着才超时移交 |
| consumed 清除 | 仅当满仓且**盘口仍有对应 TP 限价**时才清误记账；盘口已空则保留（禁止重挂循环） |
| `_rebuild_tp_limit_orders` | 与 patch 对齐：盘口已有匹配单则跳过；先去重再挂 |
| 超时 | 不再把 `remaining_qty_pct` 当成交收缩 |

## 实盘处理

- 部署后重置 ETH state：`remaining_qty_pct=1.0`，`consumed=[]`，刷新 `tp_placed_at`
- 清理 XAU 空仓误写的 ETH `tv_tps`
- 当前交易所：目标保持 **TP1×1 + TP2×1 + STOP×1**

## 回归单测

- `tests/test_tp_timeout_no_thrash.py`
- `tests/test_tp_rebuild_no_duplicate.py`

## 与止损抖动的关系

同属「对账/修复路径误动作」家族，但机制相反：止损是误 `force_replace`；TP 是超时撤单 + 误清 consumed 导致误重挂。
