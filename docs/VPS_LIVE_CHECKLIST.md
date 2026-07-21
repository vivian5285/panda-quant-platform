# VPS 实盘清单（架构对齐 · RISK20 · 90m · TP12）

> **同步日期**：2026-07-22  
> TV 只发 3 种消息：LONG/SHORT、CLOSE_QUICK_EXIT、CLOSE_RSI_EXIT。  
> VPS：单仓 · 先平后开 · RISK20 sizing · 呼吸止损 · 90m ATR/ADX · 仅挂 TP1+TP2。

---

## 核心行为

```
LONG/SHORT → 查实盘 → 非空则全平撤单等确认 → qty=min(风险/|价-stop|, 名义/价, TV.qty)
         → 市价开仓 → 挂 TP1/TP2 (30/30) → 呼吸初始止损(带qty) → 启动引擎

TP1/TP2成交 → 暂停tick → 撤旧止损 → 按剩余70%/40%重挂(同currentStop) → 恢复tick

CLOSE_QUICK_EXIT / CLOSE_RSI_EXIT → 市价全平 → 撤单 → 重置状态
```

| 项 | 值 |
|----|-----|
| 仓位 | `min(equity×0.20/\|p−sl\|, equity×5/p, TV.qty)` |
| K 线 | 30m→**90m** 合成 · ATR(14)/ADX(14) |
| 初始止损 | entry ± 1.5×ATR（开仓后 VPS 算） |
| 阶段一 | 步进 0.75 / 跟进 0.4 ATR |
| 阶段二 | 浮盈 3.0×ATR → ADX 追踪 1.2–2.5×ATR |
| TP | 限价 **仅 TP1+TP2**（30/30；余 40% 交阶段二） |
| 加仓 | **禁用** |
| CAP_ALIGN | **仅检测告警，不下单减仓** |

---

## 钉钉

- 先平后开：`先平后开：检测到已有持仓，已市价全平并撤单，准备执行新开仓`
- 阶段切换：`阶段切换：止损已进入阶段二（趋势追踪），当前ADX=…，追踪距离=…×ATR`
- 已移除：雷达激活、保护性全平、风控拦截、加仓、TP3止盈成交

---

## 验收

```bash
py -m pytest tests/test_breathing_stop.py tests/test_market_indicators.py \
  tests/test_market_engine_wire.py tests/test_pine_tp_regime_ratios.py \
  tests/test_vps_dev_checklist.py tests/test_tv_v6985_sizing.py \
  tests/test_trading_alerts_tp_ratio.py tests/test_close_alert_utils.py -q
```
