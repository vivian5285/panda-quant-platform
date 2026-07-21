# VPS 实盘最终行为规格（完整版 · 唯一权威）

> 同步：2026-07-22 · 实现以本文档为准；与「妈妈版」冲突处以本文为准。

## 硬性原则

1. 开仓永远先平后开（不问方向）
2. 单仓不加仓
3. 仓位每次独立计算：`min(风险/|价−initialStop|, 名义/价, TV.qty)`，`initialStop`=VPS ATR（非 TV stop_loss）
4. 止损单唯一写入方 = 呼吸止损引擎

## Webhook

仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`。

## 呼吸止损

- 阶段一：步进 0.75 / 跟进 0.4，基准 `initialStop`；TP1 底线 entry+0.5ATR；TP2 底线 entry+1.5ATR；+3.0ATR 进阶段二
- 阶段二：ADX 1.2–2.5 插值追踪
- TP1/TP2 成交：通知引擎撤旧止损→按 70%/40% 重挂（暂停 tick）
- **不挂 TP3**

## 行情

30m → 90m 合成；ATR(14)/ADX(14)；webhook 不读 atr/adx。

## 保留 / 删除

- 保留：`HARD_SL_FAIL_ABORT`、`FORCE_ALIGN`
- 删除：`CAP_ALIGN` 减仓、加仓、旧雷达 activated/2.0ATR、保护性全平

## 验收

```bash
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_close_alert_utils.py -q
```
