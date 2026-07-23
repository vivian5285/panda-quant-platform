# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

> **文档同步（2026-07-23 · 硬止损缓冲垫 + 动态雷达启动 + 考核收紧）**  
> 凡与本文冲突的旧描述（含「硬止损=|entry−TV.SL|×1.2 无地板/无滑点」「雷达首动=固定0.75×ATR」「XAU 图表周期=1小时」「90m 合成 ATR」「离散呼吸档位」「先撤硬止损再挂雷达」）**一律作废**。  
> 权威指令：桌面《Gemini硬止损修复与雷达启动阈值合并指令.md》  
> 部署：`docs/VPS_DEPLOY.md` · 呼吸：`docs/CONTINUOUS_BREATH_FINAL_SPEC.md`

### 当前实盘一句话

**VPS = 三层防线永久共存（硬止损永冻 + 独立雷达止损 + TP1/TP2）+ 本金×20%×5 算仓 + 同 symbol 15s 开平铁律 + ETH/XAU 隔离。**  
硬止损与雷达**并行挂单、互不升级替换**；谁先触发谁执行。

### 生产代码锚点

| 项 | 值 |
|----|-----|
| 三方 commit | 见 git HEAD（部署后回填） |
| VPS 路径 | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 交易对 | **ETH + XAU**（`TRADING_SYMBOLS=ETHUSDT,XAUUSDT`） |
| TV 图表周期 | **ETH 90m / XAU 45m**（非 1h；VPS「1h ATR」仅为波动率 oracle，近似对齐周期） |

### 三层防线 + 雷达考核

| 层 | 规则 |
|----|------|
| **① 硬止损（永久）** | `base=max(\|TV.entry−TV.SL\|×1.2, 1.5×ATR×1.05)`，`slip=\|fill−TV.entry\|×2`，挂单=`fill±(base+slip)`。ATR 到位后**仅允许加宽一次**；其后至 flat 禁止收紧/撤销。雷达不碰硬止损。 |
| **② 雷达止损（独立）** | 首动=`TP1(1.35×ATR)×启动比例(50%~85%)`（与 trailDistanceMultiplier **共用** smooth ATR 比，**反向**插值）；步进 `0.4×ATR`（XAU `0.35`）+ TP 底线 + 3ATR 阶段二。**已删除**固定 0.75×ATR 首动门。 |
| **②b 考核收紧（方案A）** | ETH 90min / XAU 60min（≈12～18 次 5min 呼吸采样）。窗口内未达动态首动阈值 → **仅雷达**一次性收紧到 TV 原始距（`fill±\|TV.entry−TV.SL\|`）；硬止损不动。已达首动则机制结束。钉钉 `RADAR_STAGNANT`。 |
| **③ TP 限价** | TP1/TP2 各 30% @ TV 价；TP3 仅场景二 40%。 |

### 开仓瞬间

1. 挂硬止损（fill 原点 + 缓冲地板 + 滑点；ATR 可加宽一次后永冻）  
2. 挂 TP1 + TP2  
3. 拉交易所原生 **1h K** ATR → 场景一武装雷达；失败则场景二（TV atr + TP3）

### 关键参数

| 项 | 现行值 |
|----|--------|
| 算仓 | `qty = 本金 × 20% × 5 / 价` |
| 15s 铁律 | OPEN 先到丢弃晚 CLOSE；CLOSE 先到先平后开 |
| ATR | 优先交易所原生 1h；失败用 TV atr；**不用** 90m 合成 |
| 呼吸 coef | ETH 1.2~2.5 / XAU 0.5~1.2 连续插值 |
| 雷达启动 | TP1×50%~85%（动态）；**禁止**与 0.75×ATR 双轨并存 |
| 杠杆 | `FIXED_LEVERAGE=5` |

| 生产域名 | [https://twinstar.pro](https://twinstar.pro) |
|----------|---------------------------------------------|
| **TV Webhook** | `https://twinstar.pro/gemini/webhook` |
| 仓库 | [github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform) |

---

## AI Agent 速查

```yaml
project: panda-quant-platform
product: GEMINI AI / 双子星AI量化
domain: twinstar.pro
repo_path_on_vps: /home/panda/panda-quant-platform

rules:
  - hard_stop = max(|TV.entry-TV.SL|*1.2, 1.5*ATR*1.05) + |fill-TV.entry|*2; hang from fill; widen-once then frozen
  - radar first-move = TP1_dist * (50%~85% inverse smooth ATR ratio); NO fixed 0.75×ATR gate
  - stagnant tighten (Option A): ETH 18 / XAU 12 breath samples → radar to TV raw dist; hard untouched
  - chart TF: ETH 90m / XAU 45m; VPS 1h ATR is volatility oracle only
  - sizing = equity * 0.20 * 5 / price
  - 15s coalesce; clean slate before open / after flat

modules:
  hard_sl: backend/app/core/breathing_stop.py::compute_temp_tv_stop
  radar_arm: backend/app/core/breathing_profile.py::radar_arm_distance
  stagnant: backend/app/core/adverse_radar_guard.py::_maybe_stagnant_radar_tighten
  open_atr: backend/app/core/open_atr_scenario.py
  supervisor: backend/app/core/position_supervisor.py
```
