# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS**。TV → VPS webhook → 多交易所 U 永续独立执行。

> **文档同步（2026-07-25）** · 权威长文：根 `README.md` · 再入场：`docs/SMART_REENTRY_CLOSED_LOOP.md` · 部署：`docs/VPS_DEPLOY.md`

### 当前实盘一句话

**三层防线 + 智能再入场 + 本地挂单标签幂等 + 挂单硬帽≤5 + ETH/XAU 隔离。**  
TV 窗口三条路：止盈 / 雷达 BE 再入 / 硬止损认输 — 无第四种主动离场。  
**杜绝同价 50 笔 LIMIT**；日亏熔断生产关闭；限流走共享 90s 冷静。

### 生产锚点

| 项 | 值 |
|----|-----|
| 三方 commit | 部署后 `git rev-parse --short HEAD` 本地=GitHub=VPS |
| VPS | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 品种 | ETHUSDT + XAUUSDT（图表 ETH 90m / XAU 45m） |
| 再入开关 | `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED` |
| E2E | 生产必须 `E2E_FORCE_NOTIONAL_USD=0` |
| 日亏熔断 | `DAILY_LOSS_CIRCUIT_ENABLED=False`（误熔断曾挡真实 TV） |

### 关键参数

| 项 | 现行值 |
|----|--------|
| 算仓 | `qty = 本金 × 20% × 5 / 价` |
| 硬止损 | `fill±(|TV.e−SL|×buffer)`（默认 buffer=1.2；无 ATR 地板/滑点垫） |
| TP 比例 | 固定 **10/20/70**；TP3 与雷达并行互斥 |
| 雷达档位 | arm TP1×50/65/80/90/95；ETH/XAU 独立 early_be/step/coef |
| 再入价 | 双保险 min/max(5m极值±tick, TV×0.997/1.003)；须优于 TV |
| 再入区 | ETH 0.5×ATR / XAU 0.3×ATR；硬/亏永不重入；最多到 5.0 档 |
| 挂单硬帽 | 单品种未成交挂单总数 **≤5**；超限 → critical + **暂停该品种开仓** |
| 退出所有权 | `exit_ownership`: NONE / TP3_LIMIT / RADAR_STOP；先成交锁定，拒挂另一腿 |
| API 限流 | `-1003` → `ip_rest_cooldown` 共享 90s；盘口不可读禁 cancel_all/盲补 |

### 防重复限价（反 50 笔风暴）

1. `PendingOrderRegistry` 本地 in-flight 标签 → 盘口空也拒挂  
2. 同价已有 reduce-only LIMIT → 视为成功，禁止再挂  
3. LIMIT≥6 → 仅同价去重，禁止再挂/核武盲补  
4. `OPEN_ORDERS_HARD_CAP=5` → 超限暂停开仓  
5. 查单失败 fail-closed；`newClientOrderId` 幂等  

### AI Agent 速查

```yaml
project: panda-quant-platform
domain: twinstar.pro
vps: /home/panda/panda-quant-platform

rules:
  - hard_stop = fill ± (|TV.e−SL|×1.2); no ATR floor / slip pad; missing SL → reject
  - TP 10/20/70 always; TP3 ↔ radar mutex
  - local PendingOrderRegistry → refuse place even if book empty
  - OPEN_ORDERS_HARD_CAP=5; DAILY_LOSS_CIRCUIT_ENABLED=False
  - -1003 → ip_rest_cooldown 90s shared ETH+XAU
  - E2E_FORCE_NOTIONAL_USD=0 in production; wait real TV
  - three-way commit alignment required

modules:
  smart_reentry: backend/app/core/smart_reentry.py
  reentry_exec: backend/app/core/smart_reentry_mixin.py
  place_guard: backend/app/core/order_place_guard.py
  hard_sl: backend/app/core/breathing_stop.py::compute_temp_tv_stop
  open_atr: backend/app/core/open_atr_scenario.py
  rate_cool: backend/app/core/ip_rest_cooldown.py
  daily_loss: backend/app/core/daily_loss_circuit.py
  supervisor: backend/app/core/position_supervisor.py
  docs: docs/SMART_REENTRY_CLOSED_LOOP.md
```
