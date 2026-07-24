# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS**。TV → VPS webhook → 多交易所 U 永续独立执行。

> **文档同步（2026-07-25）** · 权威长文：根 `README.md` · 再入场结构：`docs/SMART_REENTRY_CLOSED_LOOP.md` · 部署：`docs/VPS_DEPLOY.md`

### 当前实盘一句话

**三层防线 + 智能再入场波段滚动 + 本地挂单标签幂等 + ETH/XAU 隔离。**  
TV 窗口三条路：止盈 / 雷达 BE 再入 / 硬止损认输 — 无第四种主动离场。

### 生产锚点

| 项 | 值 |
|----|-----|
| 三方 commit | 部署后 `git rev-parse --short HEAD` 本地=GitHub=VPS |
| VPS | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 品种 | ETHUSDT + XAUUSDT（图表 ETH 90m / XAU 45m） |
| 再入开关 | `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED` |
| E2E | 生产必须 `E2E_FORCE_NOTIONAL_USD=0` |

### 关键参数

| 项 | 现行值 |
|----|--------|
| 算仓 | `qty = 本金 × 20% × 5 / 价` |
| 硬止损 | `fill±(max(\|TV.e−SL\|×1.2, 1.5×ATR×1.05)+\|fill−TV.e\|×2)` |
| 雷达档位 | arm TP1×50/65/80/90/95；ETH/XAU 独立 early_be/step/coef |
| 再入价 | 双保险 min/max(5m极值±tick, TV×0.997/1.003)；须优于 TV |
| 再入区 | ETH 0.5×ATR / XAU 0.3×ATR；硬/亏永不重入；最多到 5.0 档 |
| 挂单幂等 | 本地标签 in-flight 绝对拒挂 + 盘口存在则视为成功 |

### AI Agent 速查

```yaml
project: panda-quant-platform
domain: twinstar.pro
vps: /home/panda/panda-quant-platform

rules:
  - hard_stop from fill + buffer + slip; never invent without TV.stop_loss
  - radar BE/micro → purge → dual-insurance limit → protect; hard never reenters
  - local PendingOrderRegistry tag inflight → refuse place even if book empty
  - defer reentry commit until after flat purge
  - E2E_FORCE_NOTIONAL_USD=0 in production; wait real TV

modules:
  smart_reentry: backend/app/core/smart_reentry.py
  reentry_exec: backend/app/core/smart_reentry_mixin.py
  place_guard: backend/app/core/order_place_guard.py
  hard_sl: backend/app/core/breathing_stop.py::compute_temp_tv_stop
  open_atr: backend/app/core/open_atr_scenario.py
  supervisor: backend/app/core/position_supervisor.py
  docs: docs/SMART_REENTRY_CLOSED_LOOP.md
```
