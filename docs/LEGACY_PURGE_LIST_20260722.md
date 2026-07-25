# 已删除 / 已废止旧逻辑清单

对照规格 §14（Gemini 多用户版）。最近清扫：`LEGACY_PURGED` 硬闸（2026-07-26）。

## §14.1 三项物理清扫（本轮）

| 项 | 处理 |
|---|---|
| 1 旧雷达 `activated` 阶梯权 | `compute_ladder_radar_sl` / `compute_vps_radar_sl` / `compute_stage_radar_sl` / `compute_radar_sl` **raise RuntimeError**；LIVE 仅 `breathing_stop.apply_breathing_tick` |
| 2 旧阶梯 0.5 / 0.3 ATR | `RADAR_STEP_ATR` / `RADAR_LOCK_ATR` = NaN；`steps_from_move` / `ladder_raise_from` / `regime_radar_move_step` purged |
| 6 硬编码 1.5×ATR | `RADAR_TP2_FLOOR_ATR` = NaN；`tp1_distance` fallback 改用 profile `tp1_atr`（1.35），禁止 ×1.5 |

额外防抢权：

- 动态 arm `radar_start_ratio` 0.50~0.85 → **固定 0.85**
- `breathing_stop.radar_arm_reached` → whitepaper `fill±tp1_distance×ratio`
- stagnant tighten 不再用动态 arm 抢激活
- mixin 重入 `tp1_filled` 改用 `tp1_filled_from_consumed`

## 主路径权威

| 职责 | 模块 |
|---|---|
| 硬止损 | `compute_temp_tv_stop` buffer **1.15** |
| 雷达跟踪 | `apply_breathing_tick` + ADX `trend_tier_params` |
| 重入 | `smart_reentry` MAX=1；TP1已成交/非强趋势拦截 |
| TP | 固定 10/20/70，TP3 必挂 |

## 仍保留（元数据 / 兼容，不驱动挂单价）

| 残留 | 说明 |
|---|---|
| `radar_activated` / `radar_step_count` | 状态落盘 + 告警；由 breathing tick 写入 |
| `detect_radar_stage` | 钉钉/日志阶段标签 |
| DingTalk 类型名 `TRAIL`/`RADAR_ARM` | 标签兼容 |
| `_handle_tv_reconcile_close` | webhook 不可达；防旧调用 |

## 验收探针

```
MAX_REENTRY == 1
RADAR_ARM_TP1_PCT == 0.85 / REENTRY == 1.00
HARD_STOP_BUFFER_FIXED == 1.15
compute_ladder_radar_sl(...) → RuntimeError LEGACY_PURGED
radar_start_ratio(any) == 0.85
```
