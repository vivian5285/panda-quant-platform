# 已知问题清单（滚动）

更新时间：2026-07-27

> 事故叙事与修复对照优先读 **`docs/SYSTEM_ISSUE_FIX_LOG.md`**。本文件只记「仍观察 / 非阻塞 / 技术债」。

## 实盘候命结论（2026-07-27）

| 项 | 状态 |
|----|------|
| 逻辑对齐币安（先平后开 / TP12 / 硬止损 / 雷达 / 10s 铁律 / cool 禁 REST） | **OK** · 全所共享路径；DeepCoin 平行监督器已同修 |
| 币安 ETH + XAU | **可实盘**（XAU 仅币安 API 用户） |
| OKX / Gate / DeepCoin ETH | **逻辑可候命**（权重/杠杆/10s 开平/雷达缩量与币安同）；是否开闸由管理员决策 |
| OPEN 后 10s 内迟到平仓 | **忽略**（`OPEN_FORCE_CLOSE_GRACE_SEC=10` + coalesce discard） |
| 深币双向/单向 | **全侧净场**（list 两侧 + batch-close + 开仓前拒脏盘） |
| 非币安 XAU | **禁止**（`trading_symbols_for_exchange` + 分发门禁） |
| 三端同步 | 以 `git rev-parse --short HEAD` 为准 |

## 观察中（不阻塞候命 TV）

| 问题 | 说明 |
|------|------|
| 真实 TP 部分成交缩雷达 | 代码路径已测；实盘盯日志 `TP后止损数量收缩` / `flush deferred stop-qty` |
| WS 断线后 trail 追赶 | 交易所止损单仍独立生效；重连后应重算 `current_sl` |
| 多用户同 IP 限流余量 | 已有 180s cool + 预算阀；加用户时盯 `-1003` / `50011` |

## 技术债（低优）

| 问题 | 说明 |
|------|------|
| DeepCoin 与 Binance 双文件监督器 | 长期可再收敛公共基类；当前 mixin 已对齐关键行为 |
| 钉钉旧类型名白名单 | `RADAR_ARM` 等遗留；呼吸引擎时代基本不用 |
| Webhook `token` 兼容 | 标注移除条件见历史条目 |

## 历史已闭环（摘要）

详见 `SYSTEM_ISSUE_FIX_LOG.md` §1–§10：`open_orders_gt_5`、`-1003` 螺旋、`initial_qty` 压扁、假 TP3、TP2 吃雷达、pipeline-ledger、XAU 仅币安、TP 缩量+10s coalesce 等。
