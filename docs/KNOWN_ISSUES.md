# 已知问题清单（最终全面复检）

更新时间：2026-07-22

## P0 — 已修复（本轮）

| 问题 | 状态 |
|------|------|
| 止损 ~5s 撤挂抖动（orchestrate 误把 aligned 当 moved → force_replace） | 已修并部署；≥30min 实盘观察见验收报告 |
| CLOSE/先平后开后 `watched_entry`/`side` 半清理 | 已修 `_clear_position_local_state` |
| `HARD_SL_MISSING` / DeepCoin `report_supervisor_close` 钉钉丢失 | 已修白名单 + 类型映射 + `_call_dingtalk` 兼容 |
| DeepCoin `_calculate_tp_quantities` 空 ratios → IndexError | 已加守卫 |

## P1 — 本轮发现、建议尽快处理

| 问题 | 严重程度 | 说明 | 建议 |
|------|----------|------|------|
| 告警类型白名单缺口 | 中 | `TP1_FILL`/`TP2_FILL`/`TP3_FILL`/`SIGNAL_RECV`/`ADVERSE_SL_DISARM` 曾不在白名单（info 会被丢）；本地已补进 `ADMIN_DINGTALK_KEY_TYPES`，**需再部署一次** `trading_alerts.py` 才进生产 | 观察窗口结束后热更并重测钉钉 |
| 遗留 `RADAR_ARM` / `RADAR_REVOKE` | 低 | 旧雷达命名仍在 tags，呼吸引擎时代基本不用；info 仍可能被丢 | 废弃代码路径或并入白名单后删除调用 |
| `_call_dingtalk` 仍靠 inspect 剥离 | 低 | 能挡旧签名，但契约不清晰 | 后续改为单一 `push_trading_alert(...)` 入口，DeepCoin bridge 只调该入口 |
| TP1/TP2 成交后止损 qty 收缩 | 中 | 代码路径存在（`_orchestrate` TP fill → `_sync_binance_merged_stop(force_replace=True)`），**本轮未等到真实 TP 成交**验证 | 下次小仓浮盈触 TP1 时盯日志 `TP后止损数量收缩` |

## P2 — 次要 / 技术债

| 问题 | 说明 |
|------|------|
| Webhook `token` 兼容 | 已标注移除条件（≥14 天无 token-only 鉴权失败） |
| `add_count` 字段仍持久化 | 加仓已禁用，字段仅残留兼容；可后续从 state schema 删除 |
| 部署方式曾用 pscp 热更 | 应以 Git push + `git pull` 为权威路径（见 `docs/VPS_DEPLOY.md`） |
| 钉钉截图 | 机器人推送成功（`push_trading_alert` 已调用且白名单放行）；请在钉钉群人工确认两条验收测试消息 |

## 不在本轮范围

- VPS root 密码 / SSH 密钥回收：指令明确留到验证完成后再议
- 放大仓位：须本轮验收通过后再议
