# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS**。TV → VPS webhook → 多交易所 U 永续独立执行。

> **文档同步（2026-07-25 · 白皮书 v3.0）** · 权威长文：根 `README.md` · 再入场：`docs/SMART_REENTRY_CLOSED_LOOP.md` · 部署：`docs/VPS_DEPLOY.md`  
> 凡与本文冲突的旧描述（「5 档递进」「arm 50~95%」「buffer 1.1/1.2/1.3」「字面 TP1×0.85」）**一律作废**。

### 当前实盘一句话

**硬止损是底线，雷达是骑士。** TP1 之前仅硬止损守护；`fill±tp1_distance×0.85`（重入×1.00）后雷达被动跟随。硬止损垫固定 **1.15**；ADX 弱/中/强档仅影响 trail；重入最多一次；TP 10/20/70；挂单硬帽≤5；ETH/XAU 隔离。

### 生产锚点

| 项 | 值 |
|----|-----|
| 三方 commit | 部署后 `git rev-parse --short HEAD` 本地=GitHub=VPS |
| VPS | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 品种 | ETHUSDT（90m）+ XAUUSDT（45m） |
| 再入开关 | `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED` |
| E2E | 生产必须 `E2E_FORCE_NOTIONAL_USD=0` |
| 日亏熔断 | `DAILY_LOSS_CIRCUIT_ENABLED=False` |

### 关键参数（白皮书 v3.0）

| 项 | 现行值 |
|----|--------|
| 算仓 | `qty = 本金 × 20% × 5 / 价` |
| 硬止损 | `fill±(\|TV.e−SL\|×**1.15**)`（全档位固定） |
| TP 比例 | 固定 **10/20/70**；TP3 与雷达互斥 |
| 雷达启动 | `tp1_distance=\|TV.tp1−TV.price\|`；首次 ×0.85 / 重入 ×1.00；激活→entry±0.5×ATR |
| ADX 档位 | 0 弱(&lt;20) / 1 中(20–30) / 2 强(&gt;30)；可选 webhook `tier`；步长/跟进/呼吸按品种表 |
| 再入 | 仅雷达扫出；ETH 0.5×ATR / XAU 0.3×ATR 区；窗口 ETH 2 根 90m / XAU 3 根 45m；**最多 1 次**；成功后 trail +1 档 + arm=1.00 |
| 再入价 | 双保险 min/max(5m极值±tick, TV×0.997/1.003)；须优于 TV **且** 优于上次开仓价 |
| 挂单硬帽 | 单品种未成交挂单总数 **≤5** |
| 退出所有权 | `exit_ownership`: NONE / TP3_LIMIT / RADAR_STOP |

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
whitepaper: v3.0-2026-07-25

rules:
  - hard_stop = fill ± (|TV.e−SL| × 1.15); missing SL → reject
  - TP 10/20/70 always; TP3 ↔ radar mutex
  - radar arm = fill ± tp1_distance × (0.85 first / 1.00 reentry); max reentry = 1
  - local PendingOrderRegistry → refuse place even if book empty
  - OPEN_ORDERS_HARD_CAP=5; DAILY_LOSS_CIRCUIT_ENABLED=False
  - E2E_FORCE_NOTIONAL_USD=0 in production; wait real TV
  - three-way commit alignment required

modules:
  trend_tiers: backend/app/core/trend_tier_params.py
  smart_reentry: backend/app/core/smart_reentry.py
  reentry_exec: backend/app/core/smart_reentry_mixin.py
  breathing: backend/app/core/breathing_stop.py
  guard: backend/app/core/adverse_radar_guard.py
  place_guard: backend/app/core/order_place_guard.py
```
