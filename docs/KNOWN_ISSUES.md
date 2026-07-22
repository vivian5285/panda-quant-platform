# 已知问题清单（最终全面复检）

更新时间：2026-07-22

## P0 — 已修复（本轮）

| 问题 | 状态 |
|------|------|
| 止损 ~5s 撤挂抖动（orchestrate 误把 aligned 当 moved → force_replace） | 已修并部署；≥30min 实盘观察见验收报告 |
| CLOSE/先平后开后 `watched_entry`/`side` 半清理 | 已修 `_clear_position_local_state` |
| `HARD_SL_MISSING` / DeepCoin `report_supervisor_close` 钉钉丢失 | 已修白名单 + 类型映射 + `_call_dingtalk` 兼容 |
| DeepCoin `_calculate_tp_quantities` 空 ratios → IndexError | 已加守卫 |
| DeepCoin `_handle_manual_flat_detected` 半清理 | 已改为 `_clear_position_local_state`（审计后续补丁，待再 push） |

## P1 — 本轮发现、建议尽快处理

| 问题 | 严重程度 | 说明 | 建议 |
|------|----------|------|------|
| 告警类型白名单缺口 | 中 | `TP1_FILL`/`TP2_FILL`/`TP3_FILL`/`SIGNAL_RECV`/`ADVERSE_SL_DISARM` 曾不在白名单（info 会被丢）；本地已补进 `ADMIN_DINGTALK_KEY_TYPES`，**需再部署一次** `trading_alerts.py` 才进生产 | 观察窗口结束后热更并重测钉钉 |
| 遗留 `RADAR_ARM` / `RADAR_REVOKE` | 低 | 旧雷达命名仍在 tags，呼吸引擎时代基本不用；info 仍可能被丢 | 废弃代码路径或并入白名单后删除调用 |
| `_call_dingtalk` 仍靠 inspect 剥离 | 低 | 能挡旧签名，但契约不清晰 | 后续改为单一 `push_trading_alert(...)` 入口，DeepCoin bridge 只调该入口 |
| （已关闭）TP1/TP2 成交后止损 qty 收缩 | — | 已用与 sentinel 同路径的受控模拟验证通过（见验收报告 C5 / `_tp_resize_verify_report.json`）；下次真实 TP 成交仍建议盯日志 `TP后止损数量收缩` 做双确认 | 观察即可 |
| TP1/TP2 重复挂单（5min 超时撤单↔核武重挂） | 高→已修 | 见 `docs/TP_DUPLICATE_INCIDENT_20260722.md`；VPS 已热更；当前盘口 2LIMIT+1STOP | 观察 ≥10min 无 `核武级重挂` / 无成对 cancel TP |

## P2 — 次要 / 技术债

| 问题 | 说明 |
|------|------|
| Webhook `token` 兼容 | 已标注移除条件（≥14 天无 token-only 鉴权失败） |
| `add_count` 字段仍持久化 | 加仓已禁用，字段仅残留兼容；可后续从 state schema 删除 |
| 部署方式曾用 pscp 热更 | 应以 Git push + `git pull` 为权威路径（见 `docs/VPS_DEPLOY.md`） |
| 钉钉截图 | 机器人推送成功（`push_trading_alert` 已调用且白名单放行）；请在钉钉群人工确认两条验收测试消息 |

## 后续加固（不阻塞下次 TV 信号）

性质从「功能对不对」转为「极端场景会不会失控」。优先级低于已闭环的 A–H / C5 / 阶段二清零。

| # | 场景 | 状态 | 建议时机 |
|---|------|------|----------|
| 2 | 多 symbol 状态隔离 | 未测（当前只跑 ETHUSDT） | 真正扩展交易对前专项测 |
| 3 | WS 断线重连：trail 是否追赶 + 钉钉 | 未专项测；交易所止损单仍独立生效 | 持续观察；重连后应强制重算一次 `current_sl` |
| 4 | 交易所 API 限频 vs 断线退避 | 防螺旋已有断线退避；限频是否同等覆盖待确认 | 逐步加固，与断线错误分类分开处理 |
| 5 | 剧烈跳空/大滑点成交后清零与归因 | 状态清零路径已覆盖；滑点归因边界待观察 | 实盘异常成交后抽检日志/钉钉 |

## 币安执行层验收跟踪

权威清单与状态：`docs/BINANCE_EXECUTION_ACCEPTANCE.md`

- **阻塞**：TP 修复后 30–60min 观察；真实 TP 成交缩量；真实全平清零 — 靠当前仓位自然走完，不主动干预
- **非阻塞**：乱序 webhook 实测、ADX 人工核对、平静先平后开范例、实操重启、WS 追赶、REST 429 重试

## 不在本轮范围

- VPS root 密码 / SSH 密钥回收：指令明确留到验证完成后再议
- 放大仓位：须本轮验收通过后再议
