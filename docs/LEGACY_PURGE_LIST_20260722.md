# 已删除 / 已废止旧逻辑清单（2026-07-22 生产级最终执行）

交付物：对照「Gemini生产级最终执行指令」第二节，逐项确认。

## 本轮代码清理（本次提交）

| 项 | 处理 |
|---|---|
| 杠杆双数据源 | `_alert` 强制写入 `_resolve_entry_leverage()`；`EXCHANGE_THEMES` / 各交易所 client / `api_validation` / `main` health / cap fallback 一律 `FIXED_LEVERAGE`（5×），不再读独立 `settings.*_LEVERAGE` 作为执行/播报源 |
| 未登记仓位接管 | `prepare_manual_adopt`：VPS ATR → `initialStop`；缺 TP 时用 `compute_tp_ladder_from_atr`（1.35/2.5/4.0×ATR）；钉钉固定文案「未登记来源仓位·系统接管（来源待核实）」 |
| CAP 主动减仓 | `_place_cap_trim_order` / `_validate_cap_trim_plan` 改为禁用 stub；enforce 路径仍为 detect-only |
| 旧文案关联 TV | 启动接管日志去掉「TV=…」编造关联 |

## 此前已删除或主路径已废止（确认仍无 LIVE 调用）

| 项 | 状态 |
|---|---|
| 旧雷达 SL 数学 `compute_ladder_radar_sl` / `compute_vps_radar_sl` | 死代码；LIVE 止损 = `breathing_stop` |
| 加仓 PYRAMID / PROFIT_ADD / `_rebuild_defenses_after_tv_add` | 禁用或零调用；OPEN 一律先平后开 |
| TP3 限价挂单 | `PLACEABLE_TP_LEVELS={1,2}`，不挂 TP3 |
| CAP_ALIGN 主动市价减仓 | detect-only（本轮 stub 加固） |
| 「中势推升」等旧档位文案 | 仓库无匹配 |
| Webhook `CLOSE_TP`/`CLOSE_TRAIL`/`CLOSE_SL_*`/`leg` 驱动平仓 | ingress soft-ignore；硬平仅 `CLOSE_QUICK_EXIT`/`CLOSE_RSI_EXIT` |

## 仍保留但非 SL 主路径的残留（已知，非本轮阻塞）

| 残留 | 说明 |
|---|---|
| `radar_activated` / `radar_step_count` / 0.85 元数据 | 状态字段与部分告警元数据；不驱动挂单价格 |
| `merge_regime_radar` 旧 activation 常量 | 注入 regime_settings；呼吸引擎不使用 |
| DingTalk 类型名 `TRAIL`/`RADAR_ARM`/`CLOSE_TP` | 标签兼容；发射已切 BREATH_* / 证据归因 |
| `_handle_tv_reconcile_close` | webhook 不可达；保留防旧调用 |

## 验收要点

- 钉钉杠杆必须来自执行快照（5×），缺 `detail.leverage` 时 `_alert` 仍注入。
- 外部仓：呼吸止损 + TP1/TP2 可挂；后续任意 LONG/SHORT 仍先平后开（无同向续用特例）。
