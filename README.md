# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

> **文档同步（2026-07-22 · 唯一权威规格）**  
> 凡与本文冲突的旧描述（含「妈妈版」权益×1 算仓、挂 TP123、原生 4H、旧雷达 0.5/0.3/2.0ATR）**一律作废**。  
> 完整行为规格见 **[`docs/VPS_LIVE_CHECKLIST.md`](docs/VPS_LIVE_CHECKLIST.md)**（与代码同步）。  
> 币安执行层验收进度：[docs/BINANCE_EXECUTION_ACCEPTANCE.md](docs/BINANCE_EXECUTION_ACCEPTANCE.md)（B1–B3 仍待实盘自然触发）。  
> 多所 TP 重复排查：[docs/TP_MULTI_EXCHANGE_AUDIT.md](docs/TP_MULTI_EXCHANGE_AUDIT.md)。

### 当前实盘一句话

**VPS = 先平后开开仓 + RISK20 独立算仓 + 呼吸止损引擎（唯一止损写入方）+ 仅挂 TP1/TP2 + 90m 行情 ATR/ADX + 反转保护执行。**  
除 TV 的 3 类信号与引擎自身止损触发外，不存在第三方平仓判断路径。

**近期修复（已入库）：** 止损撤挂抖动；TP 5 分钟超时误撤 → `consumed` 清空 → 核武重挂导致 **TP 重复**（见 [docs/TP_DUPLICATE_INCIDENT_20260722.md](docs/TP_DUPLICATE_INCIDENT_20260722.md)）。

| 项 | 现行值 |
|----|--------|
| TV 消息 | 仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT` |
| 算仓 | `min(权益×20%/VPS止损距, 权益×5/价, TV.qty×(TV止损距/VPS止损距))`；挂止损仍用 VPS `initialStop` |
| 止盈 | **只挂 TP1+TP2**（优先 TV `qty1`/`qty2`；否则约 30%/30%；余仓交阶段二） |
| 止损 | 呼吸引擎两阶段：阶梯 0.75/0.4 + TP 底线 0.5/1.5ATR → ADX 追踪 1.2–2.5×ATR |
| 行情 | 交易所 30m → **合成 90m** → ATR(14)/ADX(14) |
| 加仓 | **禁用**；同向亦先平后开 |
| CAP_ALIGN | **仅检测告警，不下单减仓** |
| 保留兜底 | `HARD_SL_FAIL_ABORT`、`FLIP_CLEAN_ABORT`（先平后开失败暂停）、重启 `FORCE_ALIGN` |

| 生产域名 | [https://twinstar.pro](https://twinstar.pro) |
|----------|---------------------------------------------|
| **TV Webhook（Gemini）** | `https://twinstar.pro/gemini/webhook` |
| 仓库 | [github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform) |
| 默认交易对 | **ETH + XAU** 永续（`TRADING_SYMBOLS=ETHUSDT,XAUUSDT`） |

> Gemini 多用户：Binance / OKX / Gate.io U 本位 + DeepCoin SWAP。  
> 同机可共存 legacy 单账户：币安大脑 `:5003`、深币 `:5004`，与 Gemini `:6010` 互不冲突。

---

## AI Agent 速查（全局模型）

```yaml
project: panda-quant-platform
product: GEMINI AI / 双子星AI量化
domain: twinstar.pro
repo_path_on_vps: ~/panda-quant-platform
authority: docs/VPS_LIVE_CHECKLIST.md   # 行为唯一权威

services:
  frontend:6080    # React + nginx /api/
  backend:8000     # FastAPI
  backend:6010     # Flask TV webhook
  redis:6379

# 信号主链路
TradingView POST → nginx /gemini/webhook → :6010/webhook
  → 校验 secret / action∈{LONG,SHORT,CLOSE_QUICK_EXIT,CLOSE_RSI_EXIT} / 幂等
  → 立即 HTTP 200 → SignalDispatcher → PositionSupervisor.handle_signal()

# 四条硬性原则
rules:
  - 开仓永远先平后开（不问同向/反向）
  - 单仓不加仓（无 PYRAMID / PROFIT_ADD 生效路径）
  - 仓位无状态纯函数（不读 add_count / 历史仓）
  - 止损单唯一写入方 = 呼吸止损引擎（adverse_radar_guard + breathing_stop）

# 开仓流水线
open_flow: |
  查实盘 → 非空则市价全平+撤单+等确认 → 重置呼吸状态
  → 拉 VPS ATR → initialStop=entry±1.5×ATR
  → qty=min(风险/VPS距, 名义/价, TV.qty×TV距/VPS距)   # TV.stop_loss 只调系数
  → LIMIT@TV price（不足市价补）→ 挂 TP1/TP2 → 呼吸引擎挂止损(带qty)
  → 行情引擎持续供 ATR/ADX → 钉钉开仓

# 平仓
close_tv: CLOSE_QUICK_EXIT | CLOSE_RSI_EXIT → 市价全平+撤单+重置+钉钉反转保护
close_breath: 价格触及 currentStop → 引擎全平+重置+钉钉阶段一/二
tp_fill: 订单监控只通知 → 引擎暂停tick → 撤旧止损 → 按70%/40%重挂 → 恢复tick

# 关键模块
sizing: backend/app/core/tv_entry_sizing.py          # RISK20 + TV.qty×(TV距/VPS距)
breath: backend/app/core/breathing_stop.py           # 阶段一/二纯函数
engine: backend/app/core/adverse_radar_guard.py      # 挂/改/触发止损唯一路径
market: backend/app/core/market_engine.py            # 30m→90m ATR/ADX
market_ind: backend/app/core/market_indicators.py
tp: backend/app/core/tp_regime_targets.py            # PLACEABLE={1,2}
webhook: backend/app/services/webhook_guard.py       # VALID_ACTIONS 仅4个
supervisor: backend/app/core/position_supervisor.py
deepcoin: backend/app/core/position_supervisor_deepcoin.py
```

---

## 目录

1. [产品定位与商业模式](#产品定位与商业模式)
2. [角色与权限矩阵](#角色与权限矩阵)
3. [系统架构与数据流](#系统架构与数据流)
4. [配置体系](#配置体系env-vs-管理后台-vs-platform_runtimejson)
5. [项目目录详解](#项目目录详解)
6. [统一交易工厂 · 实盘逻辑（权威）](#统一交易工厂--实盘逻辑权威)
7. [TradingView Webhook 对接手册](#tradingview-webhook-对接手册)
8. [呼吸止损引擎详解](#呼吸止损引擎详解)
9. [VPS 行情引擎](#vps-行情引擎)
10. [钉钉通知策略](#钉钉通知策略)
11. [重启恢复与兜底机制](#重启恢复与兜底机制)
12. [实盘核实交易日志](#实盘核实交易日志)
13. [绩效结算 · 充值 · 门禁](#绩效结算--充值监控--交易门禁)
14. [推广分润与管理后台](#推广分润与管理后台)
15. [安全 · API · 环境变量](#安全--api--环境变量)
16. [本地开发 · 部署 · HTTPS](#本地开发--部署--https)
17. [运维自检与故障排查](#运维自检与故障排查)
18. [生产就绪与验收](#生产就绪与验收)
19. [技术栈与更新记录](#技术栈与更新记录)

---

## 产品定位与商业模式

### 对外 vs 对内

| 维度 | 说明 |
|------|------|
| **用户感知** | 绑定交易所 API → AI 策略托管永续 |
| **技术实现** | TradingView Pine 发 Webhook → VPS 多用户并发执行 |
| **资金隔离** | 每用户独立 API Key（Fernet），仓位互不影响 |
| **收费** | 周期净盈利 × **25%**（`PLATFORM_FEE_RATE`） |
| **结算** | 主周期 30 天；宽限至 35 天；须全平仓后结算 |

### Gemini vs Legacy

| 系统 | 端口 | Nginx 路径 |
|------|------|------------|
| **Gemini 多用户（本仓库）** | 8000 / 6010 / 6080 | `/gemini/webhook` |
| 币安单账户大脑 | 5003 | `/binance/webhook` |
| Deepcoin 单账户 | 5004 | `/deepcoin/webhook` |

### 费用与分润

| 项目 | 比例 |
|------|------|
| AI 绩效服务费 | 25% 周期净盈利 |
| 一级推广 | 10%（从绩效费池） |
| 二级推广 | 5% |
| 平台净留存 | 约 10%（例：盈利 $1000 → 用户付 $250） |

---

## 角色与权限矩阵

| 角色 | 交易日志 | 账户/持仓 | 结算 |
|------|----------|-----------|------|
| **用户** | 仅本人 | Dashboard / Profile | 本人账单 |
| **管理员** | 全站 | 强制平仓、全字段 | 确认收款、申诉 |
| **推广者 L1/L2** | 仅下级 | 下级权益只读 | 不可操作用户结算 |

---

## 系统架构与数据流

```
TradingView Pine（方向 / TP1·TP2 价 / qty / qty1·qty2）
        │ HTTPS POST /gemini/webhook
        ▼
nginx → Flask :6010（secret · action 白名单 · 幂等 · 立即 200）
        │ 后台线程
        ▼
SignalDispatcher → 每用户 PositionSupervisor
        │
        ├─ LONG/SHORT → 先平后开 → RISK20 算仓 → 开仓 → TP12 + 呼吸止损
        ├─ CLOSE_QUICK/RSI → 反转保护全平
        └─ 引擎 tick → 90m ATR/ADX → 呼吸改止损价 / 触及全平
        │
        ▼
trade_logs + 钉钉关键摘要（按交易所主题）
```

### Docker 拓扑

| 服务 | 宿主机 | 说明 |
|------|--------|------|
| `frontend` | **6080** | SPA + `/api/` 反代 |
| `backend` | **8000** | FastAPI |
| `backend` | **6010** | TV Webhook |
| `redis` | 6379 | **禁止公网** |

### 持久化卷

| 路径 | 内容 |
|------|------|
| `backend/data/` | SQLite、`platform_runtime.json` |
| `backend/state/` | `user_{id}.json`（呼吸状态：`initial_atr`/`initial_stop`/`breakeven_phase`/…） |
| `backend/logs/` | 应用日志 |
| `backend/.env` | 环境变量（只读挂载） |

---

## 配置体系：.env vs 管理后台 vs platform_runtime.json

**原则：** 敏感运维项可在管理后台写入 `backend/data/platform_runtime.json`（Fernet），**优先于** `.env`，多数保存后立即生效。

| 配置项 | 管理后台 | runtime / .env |
|--------|----------|----------------|
| Webhook Secret | 系统 → Webhook 密钥 | `webhook.secret` > `WEBHOOK_SECRET`（无长度限制） |
| 钉钉 | 平台与钱包 | `dingtalk.*` > `DINGTALK_*` |
| 链上 RPC | 平台与钱包 | `chain_rpc.*` > `ETH_RPC_URL` 等 |
| HD 助记词 | 钱包中心 | `deposit.mnemonic` |
| 开放交易所 | 系统 | `platform.enabled_exchanges` |
| 全局暂停 | 风控 | Redis `platform:trading_paused` |

---

## 项目目录详解

```
panda-quant-platform/
├── backend/app/
│   ├── main.py / webhook_server.py / config.py
│   ├── core/
│   │   ├── position_supervisor.py           # Binance/OKX/Gate 执行大脑
│   │   ├── position_supervisor_deepcoin.py
│   │   ├── exchange_factory.py
│   │   ├── tv_entry_sizing.py               # ★ RISK20 无状态算仓
│   │   ├── breathing_stop.py                # ★ 呼吸止损纯函数
│   │   ├── adverse_radar_guard.py           # ★ 止损挂/改/触发 + TP后数量收缩
│   │   ├── market_engine.py                 # ★ 30m→90m ATR/ADX
│   │   ├── market_indicators.py
│   │   ├── tp_regime_targets.py             # PLACEABLE_TP_LEVELS={1,2}
│   │   ├── tp_slice_guard.py / binance_smart_defense.py
│   │   ├── startup_reconcile.py             # FORCE_ALIGN · 旧 schema 暂停
│   │   ├── position_cap_guard.py            # 仅检测，不 trim
│   │   └── *_client.py
│   ├── services/
│   │   ├── dispatcher.py / webhook_guard.py / webhook_payload.py
│   │   ├── trading_alerts.py / close_alert_utils.py
│   │   └── dingtalk_* / settlement / deposit_monitor …
│   └── tests/
├── docs/VPS_LIVE_CHECKLIST.md               # ★ 行为规格摘要
├── docs/BINANCE_EXECUTION_ACCEPTANCE.md     # 币安执行层验收跟踪（B1–B3）
├── docs/TP_DUPLICATE_INCIDENT_20260722.md   # TP 重复挂单事故与修复
├── docs/DEEPCOIN_BINANCE_PARITY.md          # DeepCoin ↔ Binance 语义对齐
├── docs/KNOWN_ISSUES.md
├── frontend/  deploy/  docker-compose.yml  deploy.sh
└── production_check.sh
```

> 遗留文件 `radar_trail.py` / `vps_radar_stages.py` 仍在仓库中，**live 路径已切到 `breathing_stop`**，勿再按旧雷达文档改参数。

---

## 统一交易工厂 · 实盘逻辑（权威）

### 0. 工厂架构

```
exchange_factory.create_supervisor(user, client)
  ├─ Binance/OKX/Gate → PositionSupervisor
  │     Mixins: CapGuard(detect-only) + AdverseRadar(breath) + SmartDefense(TP) + StartupReconcile
  └─ DeepCoin → DeepcoinPositionSupervisor（语义对齐；张数单位不同）
```

### 一、四条硬性原则（不可动摇）

1. **开仓永远先平后开** — 不判断新旧方向是否相同  
2. **单仓不加仓** — 任意时刻一 symbol 一笔仓；无加权均价合并  
3. **下单数量每次独立计算** — 余额、开仓价、VPS `initialStop`、TV.qty、TV `stop_loss`（仅调整系数）  
4. **止损单全局唯一写入方** — 仅呼吸引擎可下/改/触发止损；订单监控只发事件  

### 二、信号链路

```
POST /gemini/webhook
  → VALID_ACTIONS 校验（其余拒绝+日志）
  → HTTP 200
  → handle_signal
       ├─ LONG / SHORT → _handle_tv_entry → _force_flat_before_open → _open_position
       └─ CLOSE_QUICK_EXIT / CLOSE_RSI_EXIT → _close_all（反转保护）
```

| 条件 | LONG/SHORT | CLOSE_QUICK/RSI |
|------|------------|-----------------|
| 用户暂停 / 绩效未缴 | 跳过建仓 | **仍执行** |
| 全局暂停 | 拦截建仓 | **放行** |
| API 未激活 / 交易所未开放 | 跳过 | 跳过 |

### 三、下单数量（唯一公式）

实现：`tv_entry_sizing.compute_tv_entry_qty` · `SIZING_MODE=risk20_cap5x_tv_qty_cap`  
权威细则：[docs/VPS_LIVE_CHECKLIST.md §二](docs/VPS_LIVE_CHECKLIST.md)

```
风险资金 = 合约权益 × 0.20
名义上限 = 合约权益 × 5
initialStop = 开仓价 ± 1.5 × VPS_ATR          # 开仓前 market_engine
VPS实际止损距离 = |开仓价 − initialStop|
TV隐含止损距离 = |开仓价 − TV.stop_loss|
调整系数 = TV隐含止损距离 / VPS实际止损距离
调整后的TV数量上限 = TV.qty × 调整系数
理论数量 = min(风险资金/VPS实际止损距离, 名义上限/开仓价, 调整后的TV数量上限)
最终数量 = floor(理论数量 / 步长) × 步长
```

| 规则 | 说明 |
|------|------|
| TV `stop_loss` | **只参与调整系数**；真实挂止损价仍是 VPS `initialStop` |
| 调整时机 | **仅开仓算一次**；后续 tick 不重算 |
| 缺 `TV.qty` | **拒开仓** |
| ATR 异常且可从 `TV.stop_loss` 反推 | **应急降级开仓**（见「VPS 行情引擎 · ATR 容错」），非静默拒单 |
| ATR 异常且无可用 `TV.stop_loss` | **拒开仓** + `ATR_INVALID`/`ATR_ANOMALY` |
| 杠杆 | 交易所统一设 **5×**（`FIXED_LEVERAGE`） |
| 加仓路径 | 返回 `add_disabled` / qty=0 |
| 开仓日志 | 记录 `adjust_coef`、三候选 qty、`binding`、`atr_source` |

### 四、开仓后挂单

| 订单 | 行为 |
|------|------|
| TP1 | 限价；数量优先 TV `qty1`，否则约总仓 30%；价格=`tp1` |
| TP2 | 限价；数量优先 TV `qty2`，否则约总仓 30%；价格=`tp2` |
| TP3 | **不挂** |
| 止损 | 呼吸引擎按 **当前仓位 qty** 挂 reduceOnly STOP（禁止仅靠无量 closePosition 作为主路径） |

开仓单：优先 **LIMIT @ TV `price`**，不足额市价补（`_place_tv_entry_order`）。

### 五、TP 成交后（订单监控 → 引擎）

1. 确认成交，更新 `remainingQtyPct`（TP1→70%，TP2→40%）  
2. **通知**呼吸引擎：暂停 tick → 撤旧止损 → 按剩余数量 + 当前 `currentStop` 重挂 → 恢复 tick  
3. **不**单独强制把止损改到 entry+1tick / entry+1.5ATR（价格由阶段一底线公式自动覆盖）  
4. 钉钉：成交价、剩余比例、当前止损  

### 六、已删除 / 禁止的行为

| 类别 | 删除项 |
|------|--------|
| 算仓 | `(equity×0.20×5)/price` 忽略止损距与 TV.qty |
| 止盈 | TP3 限价、TP3 成交钉钉主路径 |
| 旧雷达 | `activated`、0.85×TP1 激活、0.5/0.3 步进、固定 2.0×ATR |
| 加仓 | PYRAMID / PROFIT_ADD / 加权均价重挂 |
| 自主平仓 | 保护性全平本地判断、`CAP_ALIGN` 市价减仓 |
| Webhook | `CLOSE_TP` / `CLOSE_TRAIL` / `CLOSE_SL_*` / `CLOSE_PROTECT` / `leg` |

---

## TradingView Webhook 对接手册

### URL

```
https://twinstar.pro/gemini/webhook
```

内网调试：`http://127.0.0.1:6010/webhook`

### 仅支持的 action（4 个）

| action | 含义 |
|--------|------|
| `LONG` | 开多（先平后开） |
| `SHORT` | 开空（先平后开） |
| `CLOSE_QUICK_EXIT` | 反转保护全平 |
| `CLOSE_RSI_EXIT` | 反转保护全平 |

其余 action → **拒绝并记日志**，不做交易。

### 开仓 JSON 示例

```json
{
  "symbol": "ETHUSDT.P",
  "action": "LONG",
  "secret": "你的密码",
  "price": 3300.5,
  "qty": 1.2,
  "qty1": 0.36,
  "qty2": 0.36,
  "tp1": 3350,
  "tp2": 3480,
  "tp3": 3560,
  "stop_loss": 3200.5,
  "regime": 3,
  "bar_index": 27048,
  "seq": 1
}
```

| 字段 | VPS 怎么用 | 参与交易所止损价？ |
|------|------------|-------------------|
| `secret` | 鉴权（必填）；旧字段 `token` 仍兼容 | **否** |
| `price` | 开仓参考价；与 `stop_loss` 算 TV 隐含止损距（只改仓位） | **否** |
| `qty` | 三选一候选（须先 × 调整系数） | **否** |
| `qty1` / `qty2` | TP1/TP2 限价挂单数量 | **否** |
| `qty3` | **不用**（不挂 TP3） | — |
| `stop_loss` | **只**反推 TV 隐含止损距 → 修正 qty；**绝不当**挂单价 | **否** |
| `tp1` / `tp2` | TP1/TP2 限价挂单价格 | **否** |
| `tp3` | **不用** | — |
| `atr` / `adx` | **不读**；行情引擎自算 | — |
| `symbol` | 必填（支持 `.P`）；ETH/XAU 独立 supervisor | — |

> 只有 `price−stop_loss` 这一次减法服务仓位换算；止损价全部来自 VPS `initialStop` / 呼吸引擎。  
> 完整字段+tick 流程见 [`docs/VPS_LIVE_CHECKLIST.md`](docs/VPS_LIVE_CHECKLIST.md)。

### 反转保护 JSON

```json
{
  "action": "CLOSE_QUICK_EXIT",
  "secret": "你的密码",
  "symbol": "ETHUSDT.P",
  "side": "LONG",
  "price": 3280,
  "reason": "评分反转",
  "pnl_pct": -0.8
}
```

### 时序与幂等

- Secret：JSON 字段名 **`secret`**（值与后台/env 一致）；旧 `token` 仍接受  
- 同 bar `OPEN+CLOSE`：门控 **先 CLOSE 再 OPEN**（`webhook_seq_gate`）  
- 幂等：`action+symbol` 默认约 60s；含 `bar_index+seq` 时 24h Redis 键  
- Secret 来源：管理后台 runtime 优先于 `.env`

---

## 呼吸止损引擎详解

实现：`breathing_stop.py`（纯函数）+ `adverse_radar_guard.py`（挂单/改单/触发）。  
权威全文：[docs/VPS_LIVE_CHECKLIST.md §二～§四](docs/VPS_LIVE_CHECKLIST.md)

**与仓位计算独立：** 数量开仓一次定死；止损价每个 tick 重算。TV `price`/`stop_loss` **不参与** tick。

### 止损价输入（与 TV 无关）

开仓时：30m→90m → `initialAtr`（此后固定）→ `initialStop = entry ± 1.5×initialAtr` → 首张止损挂单价 + 阶梯基准。

### 必须持久化的状态

| 字段 | 含义 |
|------|------|
| `entryPrice` / `watched_entry` | 开仓均价（固定） |
| `initialAtr` | 开仓时刻 ATR，**全程固定** |
| `initialStop` | `entry ± 1.5×ATR`，阶梯基准（固定） |
| `currentStop` / `current_sl` | 当前止损，只朝盈利方向移（每 tick） |
| `best_price`（highest/lowest） | 持仓极值（每 tick） |
| `breakevenPhase` | 是否阶段二（只升不降） |
| `remainingQtyPct` | TP 成交后剩余比例（改挂单量，不改止损公式） |
| `schema_version` | ≥2；旧雷达 schema → 告警暂停 |

### 阶段一（保本前，每 tick）

```
step_count = floor(|price − entry| / (0.75 × initialAtr))
step_stop  = initialStop ± step_count × 0.4 × initialAtr
candidate  = max/min(currentStop, step_stop)   # 只朝盈利

若 |price−entry| ≥ 1.35×ATR：candidate 不低于/不高于 entry±0.5×ATR   # TP1 底线
若 |price−entry| ≥ 2.5×ATR：candidate 不低于/不高于 entry±1.5×ATR    # TP2 底线
若 |price−entry| ≥ 3.0×ATR → breakevenPhase=true（进入阶段二，不回退）
```

### 阶段二（ADX 连续追踪，每 tick；ADX 仅 90m 闭合更新）

```
trail_dist = trail_distance(adx) × initialAtr   # ADX 15→1.2 … 35→2.5
currentStop = max/min(currentStop, extreme ∓ trail_dist)
```

### 触发与失败兜底

- 价格触及 `currentStop` → 市价全平 → 重置 → 钉钉（标明阶段一/二）  
- TP1/TP2 成交 → 通知引擎按 70%/40% **重挂数量**（价格仍用当前 `currentStop`）  
- 改单/下单失败 → **`HARD_SL_FAIL_ABORT`**

---

## VPS 行情引擎

| 项 | 值 |
|----|-----|
| 源 | 各所 `fetch_klines`；失败可回落 Binance 公共 |
| 合成 | 每 3 根 **30m** → 1 根 **90m**；锚点 `bucket=(t_ms//5400000)*5400000`（UTC epoch，非进程启动） |
| 指标 | 闭合 90m 后 Wilder **ATR(14)** / **ADX(14)** |
| ATR 容错 | **现行两级（见 `atr_emergency_fallback`）**：① VPS ATR 不可用/低于近50根中位数×0.3、或与 TV 隐含 ATR 连续偏离达阈值，**且**能从 `TV.stop_loss` 反推隐含 ATR → **本笔降级用 TV 隐含 ATR 开仓**（`atr_source=tv_emergency_fallback`）+ 钉钉 `ATR_FALLBACK`，随后**暂停该 symbol 自动开仓**直至人工恢复；② 无法反推（无可用 TV stop）→ **拒本次开仓**+钉钉 `ATR_INVALID`/`ATR_ANOMALY`（不永久暂停全局）。呼吸倍数不变，只换 ATR 数值来源。 |
| 消费方 | 开仓算 `initialStop`、呼吸 tick、阶段二 trail |
| Webhook | **禁止**用 `msg.atr` / `msg.adx` 驱动决策；可选 `bar_time` 防 OPEN 乱序 |

配置：`STRATEGY_BAR_MINUTES=90`，`KLINE_BASE_INTERVAL=30m`，`KLINE_FETCH_LIMIT=250`。  
上线前核对：TV 90m vs VPS `bar_open_ms`（见 `docs/VPS_LIVE_CHECKLIST.md` 附件）。

---

## 钉钉通知策略

配置：管理后台钉钉 或 `.env` `DINGTALK_*`。动作级去重 + 攒批，避免刷屏。

### 事件清单（现行）

| 事件 | 内容要点 |
|------|----------|
| 开仓 | 方向、价格、数量、`initialStop`、权益 |
| 先平后开 | `先平后开：检测到已有持仓，已市价全平并撤单，准备执行新开仓` |
| 阶段切换 | 进入阶段二、ADX、追踪距离×ATR |
| 止损移动 | 新止损、极值、浮盈%、阶段 |
| TP1/TP2 成交 | 成交价、剩余 70%/40%、当前止损 |
| 止损触发 | 触发价、阶段一/二、盈亏 |
| 反转保护 | `reason`、平仓价 |
| 重启 / FORCE_ALIGN | 恢复详情或方向不一致已全平 |
| 异常 | 改单失败、对账不一致、挂单超时等 |

### 已删除文案

「雷达激活」「雷达止损」「保护性全平」「风控拦截」「TP3止盈成交」「加仓成交」「首仓」等。

主题标签仍按交易所区分（`#币安…` / `#OKX…` / `#Gate…` / `#深币…`）；展示杠杆以本笔 5× 实盘为准。

---

## 重启恢复与兜底机制

1. 查交易所持仓与挂单  
2. 读持久化呼吸状态；**旧 schema**（`activated`/`stepCount` 且无 `initialAtr`）→ 钉钉告警 + **暂停**该 symbol，不强行转换  
3. **FORCE_ALIGN**：持仓方向与记录不一致 → 市价全平 + 撤单 + 重置 + 告警  
4. 按 `currentStop` 重挂止损；恢复未成交且仍有利的 TP1/TP2  
5. 重启行情引擎 + 呼吸 tick  
6. 无持仓 → 清状态等待信号  

**CAP_ALIGN**：可检测超标并告警，**禁止**市价减仓。

### 其它护栏

| 机制 | 行为 |
|------|------|
| 仓位一致性 | 以交易所为准修正本地 |
| 重复消息 | ~60s 同 action+symbol 忽略 |
| API 断线 | 指数退避重连（1s,2s,4s…） |
| 硬止损挂失败 | 开仓后失败可撤仓禁裸奔 |

---

## 实盘核实交易日志

1. 用户可见动作入库 `trade_logs`  
2. `detail_json` 含 `live_verified`、sizing meta、`initial_stop`、shield 等  
3. 前端 `TradeLogDetailPanel`；**钉钉不替代日志**  

查看：用户 `/trades` · 管理端系统全域日志 · 推广者下级日志（权限校验）。

---

## 绩效结算 · 充值监控 · 交易门禁

- 周期 30/35 天；全平且有净盈利出账；未缴费 → Dispatcher **跳过建仓**（平仓仍放行）  
- HD 专属地址 + `deposit_monitor` 扫描；`SETTLEMENT_AUTO_CONFIRM` 可自动确认  
- API 绑定：合约开、提现关；建议 IP 白名单  

---

## 推广分润与管理后台

- 邀请：`{FRONTEND_URL}/register?ref=PANDA-XXXXXXXX`  
- 管理端 `/admin`：用户、信号、风控、结算、缴纳、Webhook Secret、开放交易所、启动审计等  
- 默认管理员：`ADMIN_EMAIL` / `ADMIN_PASSWORD`（**部署必改**）  

用户端：`/dashboard` `/api` `/trading` `/trades` `/settlements` `/referrals` `/withdraw` `/profile`

---

## 安全 · API · 环境变量

| 措施 | 实现 |
|------|------|
| Webhook secret | body == runtime/env |
| Action 白名单 | 仅 4 个交易 action |
| 幂等 / 限频 | Redis + 每 IP 120/min |
| API Key | Fernet `ENCRYPTION_KEY` |
| 生产严格 | `PRODUCTION_STRICT=1` 弱密钥拒启 |

### 交易相关环境变量（现行）

| 变量 | 说明 |
|------|------|
| `STRATEGY_BAR_MINUTES` | **90** |
| `KLINE_BASE_INTERVAL` | **30m** |
| `SIZING_MARGIN_LEVERAGE` | 5（与名义上限一致） |
| `LEVERAGE` 等 | 仅缺省回退展示；实盘开仓绑定 **5×** |
| `MAX_ADD_TIMES*` / `ADD_RATIO*` | 已废弃（加仓禁用），保留避免旧 .env 报错 |
| `MAX_COMBINED_NOTIONAL_MULT` | ETH+XAU 合计名义闸（默认 13×） |
| `WEBHOOK_IDEMPOTENCY_TTL_SEC` | 默认 60 |

完整模板：[`backend/.env.example`](backend/.env.example)

### API 摘要

- 用户：`/api/auth/*` `/api/users/logs` `/api/settlements/*`  
- 管理：`/api/admin/webhook/settings` `/api/admin/startup-audit` …  
- Webhook：`POST :6010/webhook` · `GET :6010/health`  
- Swagger：`:8000/docs`（生产严格模式可关）  

---

## 本地开发 · 部署 · HTTPS

```bash
# 后端
cd backend && python -m venv .venv && pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000   # Webhook 同进程 :6010

# 前端
cd frontend && npm install && npm run dev

# 测试（Windows 用 py）
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_close_alert_utils.py \
  tests/test_position_cap_guard.py -q
```

### VPS 部署

```bash
cd ~/panda-quant-platform
git pull origin main
docker compose up -d --build backend frontend
bash production_check.sh
```

HTTPS：`sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh`  
Nginx：`/gemini/webhook` → `127.0.0.1:6010`；`/` → `6080`。仅开放 80/443。

---

## 运维自检与故障排查

```bash
curl -s http://127.0.0.1:6010/health
docker compose logs -f backend | grep -E "先平后开|BREATH|FORCE_ALIGN|CAP_ALIGN|Webhook|initial_stop|missing_stop"
```

| 现象 | 排查 |
|------|------|
| HTTP 200 无成交 | `api_status`、绩效门禁、全局暂停、`enabled_exchanges` |
| `missing_stop` / `missing_tv_qty` / `missing_tv_stop_loss` / `atr_invalid` | 行情 ATR；TV 是否带 `qty`+`stop_loss` |
| 开仓无止损 | 查呼吸挂单；失败应 `HARD_SL_FAIL_ABORT` / 撤仓 |
| 重启被暂停 | 旧 schema 或缺 `initial_atr`/`initial_stop`/`tp1·tp2` |
| CAP_ALIGN 钉钉 | 仅告警属预期；不应出现市价减仓 |
| 同 bar 先开后平 | 查 `webhook_seq_gate` 版本与日志顺序 |

---

## 生产就绪与验收

**状态跟踪（权威）：** [docs/BINANCE_EXECUTION_ACCEPTANCE.md](docs/BINANCE_EXECUTION_ACCEPTANCE.md)  
判定口令：仅当 **B1+B2+B3** 均有真实交易所证据后，方可宣布「Gemini 币安执行层验收通过」。

### 上线前

- [ ] Webhook Secret 与 TV JSON 一致；`curl` POST 四 action 行为正确  
- [ ] 模拟：开仓 → 阶段一阶梯 → TP1 止损数量收缩 → TP2 再收缩 → 阶段二 → 止损/反转平仓  
- [ ] 重启：有效状态恢复；旧 schema 告警暂停  
- [ ] ATR/ADX 与 TV 90m 图核对  
- [ ] 先平后开：确认完成前不提前算仓开仓  
- [ ] `docs/VPS_LIVE_CHECKLIST.md` 与 README 一致  
- [ ] **B1** TP 重复修复后 30–60min 无核武重挂复发  
- [ ] **B2** 真实 TP 成交 → 止损 qty 收缩  
- [ ] **B3** 真实全平 → supervisor 状态清零  

### 自动化验收

```bash
cd backend
py -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_market_engine_wire.py \
  tests/test_close_alert_utils.py tests/test_position_cap_guard.py \
  tests/test_vps_dev_checklist.py tests/test_v656_core.py \
  tests/test_tp_rebuild_no_duplicate.py tests/test_tp_timeout_no_thrash.py \
  tests/test_tp_fill_stop_qty_resize.py tests/test_tp3_phase2_flat_clear.py \
  tests/test_user_symbol_isolation.py tests/test_deepcoin_binance_parity.py -q
```

---

## 技术栈与更新记录

| 层 | 技术 |
|----|------|
| API | FastAPI, SQLAlchemy, Pydantic |
| 执行 | PositionSupervisor + 呼吸引擎 + 行情引擎 |
| Webhook | Flask :6010 |
| 前端 | React 18, Vite, TypeScript |
| 部署 | Docker Compose, Nginx, Certbot |

### 2026-07-22 · 最终权威规格落地

| Commit | 内容 |
|--------|------|
| `8623f0b` | RISK20 算仓；TP12；90m；止损带 qty + TP 后收缩；CAP detect-only；钉钉清理 |
| `3b61a3e` | 开仓用 **VPS initialStop** 算仓；止损写入收拢呼吸引擎；旧 schema 暂停；checklist 同步 |
| `ba76f31` / `3524ac6` | 90m 锚点；ATR 两级兜底；止损撤挂抖动与空仓清零；钉钉送达；TV.qty×止损距系数 |
| （本节） | **防 TP 重复**：超时勿误撤有效 TP；盘口已有匹配 TP 则跳过 rebuild；DeepCoin 对齐；验收/事故文档 |

### 历史说明（勿再当现行）

此前 README 中的「路径比例雷达 50/60/70/80」「TP123 基础单×3」「PYRAMID 加仓」「TV `risk_pct`/`tv_sl` 权威算仓与挂止损」「妈妈版权益×1」等，均已被本节与 `docs/VPS_LIVE_CHECKLIST.md` **取代**。事故档案中的修复思路（先平后开、TP 不重挂已成交档、硬止损禁普通限价秒平等）仍有运维参考价值，但参数与模块名请以**呼吸止损 + RISK20**为准。

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。
