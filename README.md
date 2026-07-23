# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

> **文档同步（2026-07-23 · 三层防线永久共存终稿 · commit `1f716e7`）**  
> 凡与本文冲突的旧描述（含「90m 合成行情作为开仓/雷达 ATR」「≤2.5s 同 symbol 缓存」「呼吸引擎为唯一止损写入方」「TV atr 为开仓 ATR 唯一来源」「离散呼吸档位」「先撤硬止损再挂雷达」）**一律作废**。  
> 权威白皮书：桌面《Gemini终极生产级全功能白皮书.md》  
> 部署：`docs/VPS_DEPLOY.md` · 呼吸：`docs/CONTINUOUS_BREATH_FINAL_SPEC.md` · 旧逻辑清除：`docs/LEGACY_PURGE_LIST_20260722.md`

### 当前实盘一句话

**VPS = 三层防线永久共存（硬止损永冻 + 独立雷达止损 + TP1/TP2）+ 本金×20%×5 算仓 + 开仓前/平仓后净场 + 同 symbol 15s 开平铁律 + ETH/XAU 隔离。**  
硬止损与雷达止损**并行挂单、互不升级替换**；谁先触发谁执行，仓位归零后撤销其余挂单。  
**状态：本地 / GitHub / VPS 已对齐 `1f716e7`，空仓待命，等待真实 TV 信号。**

### 生产代码锚点

| 项 | 值 |
|----|-----|
| 三方 commit | **`1f716e7`**（本地 = origin/main = VPS） |
| VPS 路径 | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 交易对 | **ETH + XAU**（`TRADING_SYMBOLS=ETHUSDT,XAUUSDT`） |

### 三层防线永久共存（核心，不得误解）

| 层 | 规则 |
|----|------|
| **① 硬止损（永久防线）** | 开仓即挂：`distance=\|entry−TV.stop_loss\|×1.2`；LONG=`entry−dist`，SHORT=`entry+dist`（例 1900/1880→**1876**）。至 flat 前：**禁止**撤销 / 改价 / 替换。ATR 升级、雷达上移**都不碰硬止损**。唯一撤销时机：仓位归零。 |
| **② 雷达止损（独立动态）** | 呼吸引擎**额外**挂出的 STOP，**不是**硬止损升级版。与硬止损同时存在、各自改单、各自触发。雷达改单不影响硬止损。 |
| **③ TP 限价** | TP1/TP2 **始终** TV 价各 **30%**。TP3：**仅场景二**（VPS 1h ATR 失败用 TV atr）挂 TV 价 **40%**；场景一不挂 TP3（剩余由雷达收网）。 |
| 部分平仓 | TP 成交后仓位变 70%/40%：硬止损与雷达止损**数量同步收缩**，价格不变。 |
| 归零清理 | 任一止损触发或全部 TP 成交 → 立即撤销其余挂单，不留孤儿单。 |

### 开仓瞬间三件事（同步）

1. 挂硬止损（TV×1.2 永冻）  
2. 挂 TP1 + TP2（30%/30% @ TV 价）  
3. 同步拉取交易所原生 **1h K 线**算真实 ATR → 场景一武装雷达；失败则场景二（TV atr + 挂 TP3）

### 关键参数

| 项 | 现行值 |
|----|--------|
| TV action | 仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`；**无 qty 字段** |
| 算仓 | `qty = 合约本金 × 20% × 5 / 价`（≈本金×1 名义）；忽略 TV qty |
| 15s 铁律 | OPEN 先到 → 15s 内 CLOSE **丢弃**；CLOSE 先到 → **先平后开**；>15s CLOSE 独立平仓 |
| 净场 | 开仓前无仓无挂单；平仓后立即撤该 symbol 全部挂单；反手一律先平 |
| ATR | **优先**交易所原生 1h；失败用 TV atr；雷达/开仓**不用** 90m 合成 |
| 呼吸 | ETH 1.2~2.5 / XAU 0.5~1.2 连续插值；阶段一阶梯**不含** coef |
| 杠杆 | 一律 `FIXED_LEVERAGE=5` |
| 加仓 | **禁用**；同向亦先平后开 |

| 生产域名 | [https://twinstar.pro](https://twinstar.pro) |
|----------|---------------------------------------------|
| **TV Webhook** | `https://twinstar.pro/gemini/webhook` |
| 仓库 | [github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform) |

---

## AI Agent 速查（全局模型）

```yaml
project: panda-quant-platform
product: GEMINI AI / 双子星AI量化
domain: twinstar.pro
repo_path_on_vps: /home/panda/panda-quant-platform
code_anchor: 1f716e7
deploy_status: synced local=github=vps — awaiting real TV

services:
  frontend:6080
  backend:8000
  backend:6010   # TV webhook
  redis:6379

rules:
  - hard_stop frozen until flat (TV stop_loss x1.2); never replace with radar
  - radar stop independent extra STOP; coexist with hard
  - sizing = equity * 0.20 * 5 / price; ignore TV qty
  - 15s coalesce: open-first discards late CLOSE; close-first → flatten then open
  - clean slate before open and after flat
  - ATR prefer VPS native 1h; fallback TV atr + TP3

modules:
  sizing: backend/app/core/tv_entry_sizing.py
  hard_sl: backend/app/core/breathing_stop.py::compute_temp_tv_stop
  open_atr: backend/app/core/open_atr_scenario.py
  radar: backend/app/core/adverse_radar_guard.py + breathing_stop.py
  tp: backend/app/core/tp_regime_targets.py
  coalesce: backend/app/services/webhook_symbol_coalesce.py
  supervisor: backend/app/core/position_supervisor.py
```


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
11. [未登记 / 外部仓位接管](#未登记--外部仓位接管)
12. [重启恢复与兜底机制](#重启恢复与兜底机制)
13. [实盘核实交易日志](#实盘核实交易日志)
14. [绩效结算 · 充值 · 门禁](#绩效结算--充值监控--交易门禁)
15. [推广分润与管理后台](#推广分润与管理后台)
16. [安全 · API · 环境变量](#安全--api--环境变量)
17. [本地开发 · 部署 · HTTPS](#本地开发--部署--https)
18. [运维自检与故障排查](#运维自检与故障排查)
19. [生产就绪与验收](#生产就绪与验收)
20. [技术栈与更新记录](#技术栈与更新记录)

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
SignalDispatcher → 每用户×每 symbol PositionSupervisor
        │
        ├─ LONG/SHORT → 先平后开 → RISK20 算仓 → 开仓 → TP12 + 呼吸止损
        ├─ CLOSE_QUICK/RSI → 反转保护全平
        ├─ 引擎 tick → 90m ATR/ADX → 呼吸改止损价 / 触及全平
        └─ 未登记实盘仓 → 市价 ATR 接管（不编造 TV 历史）
        │
        ▼
trade_logs + 钉钉关键摘要（执行快照杠杆 5× · 按交易所主题）
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
| `backend/state/` / `backend/data/supervisor/` | 呼吸状态：`initial_atr`/`initial_stop`/`breakeven_phase`/… |
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

> **杠杆：** 实盘开仓与钉钉展示不读独立 `LEVERAGE=25` 类 env 作为权威源；一律 `FIXED_LEVERAGE=5`（`tv_entry_sizing` / `exchange_leverage()` / `_alert` 注入）。

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
│   │   ├── tv_entry_sizing.py               # ★ RISK20 + FIXED_LEVERAGE=5
│   │   ├── breathing_stop.py                # ★ 呼吸止损 + 市价 TP 阶梯
│   │   ├── adverse_radar_guard.py           # ★ 止损挂/改/触发 + TP后数量收缩
│   │   ├── market_engine.py / market_indicators.py
│   │   ├── tp_regime_targets.py             # PLACEABLE_TP_LEVELS={1,2}
│   │   ├── tp_slice_guard.py / binance_smart_defense.py
│   │   ├── startup_reconcile.py             # FORCE_ALIGN · 未登记接管 · 旧 schema
│   │   ├── position_cap_guard.py            # 仅检测，不 trim
│   │   ├── close_attribution.py            # 平仓归因证据门
│   │   ├── exchange_errors.py               # ExchangeTransientError
│   │   └── *_client.py                      # trading_leverage=FIXED_LEVERAGE
│   ├── services/
│   │   ├── dispatcher.py / webhook_guard.py / webhook_payload.py
│   │   ├── trading_alerts.py                # theme 杠杆=FIXED；执行快照优先
│   │   └── dingtalk_* / settlement / deposit_monitor …
│   └── tests/
├── docs/VPS_LIVE_CHECKLIST.md               # ★ 行为规格摘要
├── docs/LEGACY_PURGE_LIST_20260722.md       # ★ 已删除/废止清单
├── docs/GEMINI_FINAL_STATUS_20260722.md     # ★ 最终状态清单（验收通过）
├── docs/BINANCE_EXECUTION_ACCEPTANCE.md     # 币安执行层验收（已关闭）
├── docs/E2E_WEBHOOK_TIMELINE_20260722.md    # webhook 全链路时间线
├── docs/E2E_ANOMALY_ANALYSIS_20260722.md    # ATR/开仓补挂两处异常说明
├── docs/OBSERVATION_WINDOW_20260722.md      # 观察窗起止与纪律
├── docs/TP_DUPLICATE_INCIDENT_20260722.md   # TP 重复挂单事故
├── docs/TP_MULTI_EXCHANGE_AUDIT.md
├── docs/DEEPCOIN_BINANCE_PARITY.md
├── docs/KNOWN_ISSUES.md
├── frontend/  deploy/  docker-compose.yml  deploy.sh
└── production_check.sh
```

> 遗留文件 `radar_trail.py` / `vps_radar_stages.py` 仍在仓库中，**live 止损路径已切到 `breathing_stop`**，勿再按旧雷达文档改参数。详见清除清单。

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

1. **开仓永远先平后开** — 不判断新旧方向是否相同；外部/人工仓亦同  
2. **单仓不加仓** — 任意时刻一 symbol 一笔仓；无加权均价合并  
3. **下单数量每次独立计算** — 余额、开仓价、VPS `initialStop`、TV.qty、TV `stop_loss`（仅调整系数）  
4. **止损单全局唯一写入方** — 仅呼吸引擎可下/改/触发止损；订单监控只发事件  

### 二、信号链路

```
POST /gemini/webhook
  → VALID_ACTIONS 校验（其余拒绝+日志；旧 CLOSE_TP/TRAIL/SL_* soft-ignore）
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
保证金 = 合约本金余额 × 0.20
名义价值 = 保证金 × 5 = 合约本金余额 × 1     # 永远
最终数量 = floor(名义价值 / 开仓价 / 步长) × 步长
initialStop = 开仓价 ± 1.5 × VPS_ATR         # 仅挂止损，不算仓
```

| 规则 | 说明 |
|------|------|
| 本金 | **合约本金余额** = U 本位合约总权益（非可用保证金） |
| TV `qty` | **只校验存在**；不参与数量（防天文数字） |
| TV `stop_loss` | **不算仓**；真实挂止损价仍是 VPS `initialStop` |
| 调整时机 | **仅开仓算一次**；后续 tick 不重算 |
| 缺 `TV.qty` | **拒开仓** |
| ATR 异常（缺失/≤0/中位数异常） | **拒开仓** + `ATR_INVALID`/`ATR_ANOMALY`（**禁止** VPS K 线回退发明 atr） |
| ATR 应急降级 | **已废除** — `initial_atr` 唯一来源 = TV webhook `atr` |
| 杠杆 | **`FIXED_LEVERAGE=5`**（client / bind / 钉钉 / API 校验同源） |
| 加仓路径 | 返回 `add_disabled` / qty=0 |
| 开仓日志 | 记录 `notional_target`、`binding=margin20_lev5`、`atr_source=tv_webhook` |
| TV `qty`/`qty1-3` | **完全忽略**（可缺省；不参与算仓/TP 数量） |

### 四、开仓后挂单

| 订单 | 行为 |
|------|------|
| TP1 | 限价；数量=实盘总仓 **固定 30%**（忽略 TV qty1）；价格=`tp1` |
| TP2 | 限价；数量=实盘总仓 **固定 30%**（忽略 TV qty2）；价格=`tp2` |
| TP3 | **不挂**（40% 余仓交呼吸阶段二） |
| 止损 | 呼吸引擎按 **当前仓位 qty** 挂 reduceOnly STOP |

开仓单：优先 **LIMIT @ TV `price`**，不足额市价补（`_place_tv_entry_order`）。

### 五、TP 成交后（订单监控 → 引擎）

1. 确认成交，更新 `remainingQtyPct`（TP1→70%，TP2→40%）  
2. **通知**呼吸引擎：暂停 tick → 撤旧止损 → 按剩余数量 + 当前 `currentStop` 重挂 → 恢复 tick  
3. **不**因 5 分钟超时误撤「现价未到」的健康 TP；满仓时保留 `consumed`；rebuild 前检查盘口是否已有匹配单  
4. 钉钉：成交价、剩余比例、当前止损  

### 六、已删除 / 禁止的行为

完整清单见 [docs/LEGACY_PURGE_LIST_20260722.md](docs/LEGACY_PURGE_LIST_20260722.md)。

| 类别 | 删除项 |
|------|--------|
| 算仓 | `(equity×0.20×5)/price` 忽略止损距与 TV.qty |
| 止盈 | TP3 限价主路径 |
| 旧雷达 | `activated`、0.85×TP1 激活、0.5/0.3 步进、固定 2.0×ATR 作为挂单价 |
| 加仓 | PYRAMID / PROFIT_ADD / 加权均价重挂 |
| 自主平仓 | `CAP_ALIGN` 市价减仓（detect-only） |
| Webhook | `CLOSE_TP` / `CLOSE_TRAIL` / `CLOSE_SL_*` / `CLOSE_PROTECT` / `leg` |
| 钉钉杠杆 | 独立于执行层的第二配置源（曾显示 25×） |

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

其余 action → **拒绝并记日志**，不做交易。旧 `CLOSE_TP`/`CLOSE_TRAIL`/`CLOSE_SL_*` → `legacy_ignored`。

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
| `leverage` | **忽略**；实盘固定 5× | — |
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

实现：`breathing_profile.py`（ETH/XAU 连续插值）+ `breathing_stop.py` + `atr_1h_breathing.py` + `adverse_radar_guard.py`。  
权威全文：[docs/VPS_LIVE_CHECKLIST.md §二～§四](docs/VPS_LIVE_CHECKLIST.md)  
终验证据：[docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md](docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md)

**与仓位计算独立：** 数量开仓一次定死；止损价每个 tick 重算。TV `price`/`stop_loss` **不参与** tick。  
**双币种：** 同一引擎；状态 / 1h ATR / coef 按 `(exchange, user_id, symbol)` 隔离。XAU 更紧靠 **更窄的 minMult/maxMult**（0.5~1.2），**不再**另乘 trail_tighten×0.8。并存时各约 1× 余额名义，合计约 2×。

### 止损价输入（与 TV 挂单价无关）

开仓时：TV `atr` → 冻结 `initialAtr` → `initialStop = entry ± 1.5×initialAtr` → 挂单时再加减执行缓冲（ETH 0.3 / XAU 0.5）。  
运行中：`ratio = atr_1h / initialAtr` → SMA(3) → **连续线性插值** `trailDistanceMultiplier`（非离散档）。

| 参数 | ETH | XAU |
|------|-----|-----|
| coef 区间 (minMult~maxMult) | 1.2 ~ 2.5 | 0.5 ~ 1.2 |
| 冷启动（ratio=1.0） | **1.525** | **0.675** |
| ratioFloor / ratioCeiling | 0.6 / 2.2（共用只读） | 同左 |

### 必须持久化的状态

| 字段 | 含义 |
|------|------|
| `entryPrice` / `watched_entry` | 开仓均价（固定） |
| `initialAtr` | 开仓时刻 ATR，**全程固定**（描述符只读锁） |
| `initialStop` | `entry ± 1.5×ATR`，阶梯基准（固定） |
| `currentStop` / `current_sl` | 当前止损，只朝盈利方向移（每 tick） |
| `best_price`（highest/lowest） | 持仓极值（每 tick） |
| `breakevenPhase` | 是否阶段二（只升不降） |
| `breathing_coefficient` | 当前呼吸系数（1h ATR 连续插值；空闲默认=冷启动，**不是**字面量 1.0） |
| `breath_ratio_history` / `breath_smooth_ratio` | ratio SMA 窗口 |
| `remainingQtyPct` | TP 成交后剩余比例（改挂单量，不改止损公式） |
| `schema_version` | ≥2；旧雷达 schema → 告警暂停 |

### 阶段一（开仓即呼吸，每 tick）

阶段一阶梯 / 早保本 / TP 路径底线 **只用锁定 `initialAtr`，不含呼吸系数**。

```
早保本: 浮盈 ≥ early_be×ATR → 止损锁到 entry±1 tick   # ETH 0.5 / XAU 0.3
step_count = floor(|price − entry| / (step_trigger × initialAtr))
step_stop  = initialStop ± step_count × step_advance × initialAtr
candidate  = max/min(currentStop, step_stop, early_be)   # 只朝盈利

若 |price−entry| ≥ 1.35×ATR：candidate 不低于/不高于 entry±0.5×ATR   # TP1 底线
若 |price−entry| ≥ 2.5×ATR：candidate 不低于/不高于 entry±1.5×ATR    # TP2 底线
若 |price−entry| ≥ 3.0×ATR → breakevenPhase=true（进入阶段二，不回退）
```

### 阶段二（自适应追踪）

```
trail_dist = initialAtr × trailDistanceMultiplier(smoothedRatio)   # = coef；无额外 tighten
currentStop = max/min(currentStop, extreme ∓ trail_dist)
```

新止损价必须**严格优于**当前止损才改单，避免无意义频繁撤挂。

### 触发与失败兜底

- 价格触及 `currentStop` → 市价全平 → 统一状态清零 → 钉钉（标明阶段一/二 + `[ETH]`/`[XAU]`）  
- TP1/TP2 成交 → 通知引擎按 70%/40% **重挂数量**（价格仍用当前 `currentStop`）  
- 改单/下单失败 → **`HARD_SL_FAIL_ABORT`**
- 平仓后：bulk cancel + leftover 逐笔清扫；残留则 `FLAT_ORDERS_LEFT` / 开仓门禁 `OPEN_BOOK_DIRTY`

---

## VPS 行情引擎

| 项 | 值 |
|----|-----|
| 开仓 ATR | **TV webhook `atr`**（冻结为 `initial_atr`） |
| 呼吸 ATR | 币安原生 **1h** K 线 ATR(14)，每 symbol 独立缓存，≤5 分钟刷新 |
| 遗留 90m | 仅作极端 fallback；live 主路径不再依赖 VPS 自算 ATR |
| 消费方 | 开仓算 `initialStop`、呼吸 tick、阶段二 trail、未登记仓位接管 |
| Webhook | 必填 `symbol` + `atr`；可选 `bar_time` 防 OPEN 乱序 |

配置：`STRATEGY_BAR_MINUTES=90`，`KLINE_BASE_INTERVAL=30m`，`KLINE_FETCH_LIMIT=250`。

---

## 钉钉通知策略

配置：管理后台钉钉 或 `.env` `DINGTALK_*`。动作级去重 + 攒批，避免刷屏。

### 执行快照原则（本轮根治）

| 字段 | 来源 |
|------|------|
| 杠杆 | `_alert` **强制**写入 `_resolve_entry_leverage()` → `FIXED_LEVERAGE=5`；theme 种子亦为 5 |
| 方向 / 数量 / 入场 / 止损 | supervisor 本笔状态（缺省时由 `_alert` 注入） |
| 平仓归因 | `close_attribution`：证据不足就承认不足；maker≠TP 价不判止盈；查询失败不报「已空仓」 |

### 事件清单（现行）

| 事件 | 内容要点 |
|------|----------|
| 开仓 | 方向、价格、数量、`initialStop`、权益、**5×** |
| 先平后开 | 检测到已有持仓，已市价全平并撤单，准备执行新开仓 |
| 未登记接管 | **「未登记来源仓位·系统接管（来源待核实）」** — 不编造 TV 关联 |
| 阶段切换 | 进入阶段二、ADX、追踪距离×ATR |
| 止损移动 | 新止损、极值、浮盈%、阶段（`BREATH_*`） |
| TP1/TP2 成交 | 成交价、剩余 70%/40%、当前止损 |
| 止损触发 | 触发价、阶段一/二、盈亏 |
| 反转保护 | `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT` |
| 查询失败 | `EXCHANGE_QUERY_FAIL` / 恢复后 `EXCHANGE_QUERY_OK` |
| 重启 / FORCE_ALIGN | 恢复详情或方向不一致已全平 |
| 异常 | 改单失败、对账不一致、挂单超时、`CAP_ALIGN` 仅告警等 |

### 已删除文案

「雷达激活」「雷达止损」「保护性全平」「风控拦截」「TP3止盈成交」「加仓成交」「首仓」「中势推升」等。

主题标签仍按交易所区分（`#币安5x·ETH` / `#OKX5x·ETH` / `#Gate5x·ETH` / `#深币5x·ETH`）。

---

## 未登记 / 外部仓位接管

真实场景：交易所已有仓位，但 VPS 无对应 `trade_id` / 开仓日志（人工下单、他处开仓、状态丢失等）。

| 步骤 | 行为 |
|------|------|
| 检测 | 启动对账或空仓巡检发现实盘仓且无工厂开仓记录 |
| 接管 | `prepare_manual_adopt`：锚定 `initial_qty`；**拉当前市价 ATR** → `initialStop`；缺 TP1/TP2 时用 `compute_tp_ladder_from_atr`（1.35 / 2.5 / 4.0×ATR） |
| 钉钉 | 「未登记来源仓位·系统接管（来源待核实）」——**不**关联无关历史 TV |
| 保护 | 立即纳入呼吸引擎；禁止裸奔 |
| 后续 TV OPEN | **一律先平后开**（同向也不「续用」外部仓） |
| 后续硬平 | 仅 `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT` 强制全平；裸 `CLOSE` 对同向外部仓可跳过 |

实现：`startup_reconcile.prepare_manual_adopt` · `breathing_stop.compute_tp_ladder_from_atr`。

---

## 重启恢复与兜底机制

1. 查交易所持仓与挂单（**查询失败 ≠ 空仓**：抛 `ExchangeTransientError`，保留账本 + `EXCHANGE_QUERY_FAIL`）  
2. 读持久化呼吸状态；**旧 schema**（`activated`/`stepCount` 且无 `initialAtr`）→ 钉钉告警 + **暂停**该 symbol  
3. 无 `trade_id` → [未登记接管](#未登记--外部仓位接管)  
4. **FORCE_ALIGN**：持仓方向与记录不一致 → 市价全平 + 撤单 + 重置 + 告警  
5. 按 `currentStop` 重挂止损；恢复未成交且仍有利的 TP1/TP2  
6. 重启行情引擎 + 呼吸 tick  
7. 无持仓 → 清状态等待信号  

**CAP_ALIGN**：可检测超标并告警，**禁止**市价减仓。

### 其它护栏

| 机制 | 行为 |
|------|------|
| 仓位一致性 | 以交易所为准修正本地；REST 失败不误判 flat |
| 重复消息 | ~60s 同 action+symbol 忽略 |
| API 断线 | 指数退避重连 |
| 硬止损挂失败 | 开仓后失败可撤仓禁裸奔 |
| Binance `-1003` | 多为 rebuild 启动 REST 风暴；自动约 5min 解封；**避免无必要 rebuild** |

---

## 实盘核实交易日志

1. 用户可见动作入库 `trade_logs`  
2. `detail_json` 含 `live_verified`、sizing meta、`initial_stop`、`leverage`、shield 等  
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
| `LEVERAGE` / `*_LEVERAGE` | **仅兼容旧 .env**；执行与钉钉权威源为 **`FIXED_LEVERAGE=5`** |
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

# 测试（Windows 用 py -3）
cd backend
py -3 -m pytest tests/test_breathing_stop.py tests/test_tv_v6985_sizing.py \
  tests/test_vps_entry_routing.py tests/test_pine_tp_regime_ratios.py \
  tests/test_market_indicators.py tests/test_close_alert_utils.py \
  tests/test_position_cap_guard.py tests/test_manual_adopt.py \
  tests/test_trading_alerts.py tests/test_attribution_evidence_gates.py \
  tests/test_position_query_fail_safe.py tests/test_tp_rebuild_no_duplicate.py -q
```

### VPS 部署

```bash
cd /home/panda/panda-quant-platform
git pull origin main
docker compose up -d --build backend frontend
bash production_check.sh
curl -sS http://127.0.0.1:6010/health
# 核对：docker compose exec -T backend python -c \
#   "from app.core.tv_entry_sizing import FIXED_LEVERAGE; print(FIXED_LEVERAGE)"
```

HTTPS：`sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh`  
Nginx：`/gemini/webhook` → `127.0.0.1:6010`；`/` → `6080`。仅开放 80/443。

> **生产已验收通过后**：避免无必要 rebuild 即可（`-1003` 风险仍在）。见 [docs/OBSERVATION_WINDOW_20260722.md](docs/OBSERVATION_WINDOW_20260722.md)。

---

## 运维自检与故障排查

```bash
curl -s http://127.0.0.1:6010/health
docker compose logs -f backend | grep -E \
  "先平后开|BREATH|FORCE_ALIGN|CAP_ALIGN|Webhook|initial_stop|未登记|EXCHANGE_QUERY|-1003|核武"
```

| 现象 | 排查 |
|------|------|
| HTTP 200 无成交 | `api_status`、绩效门禁、全局暂停、`enabled_exchanges` |
| `missing_stop` / `missing_tv_qty` / `atr_invalid` | 行情 ATR；TV 是否带 `qty`+`stop_loss` |
| 开仓无止损 | 查呼吸挂单；失败应 `HARD_SL_FAIL_ABORT` / 撤仓 |
| 钉钉显示 25× | 应为 5×；确认部署 ≥ `77d171b`，`_alert` 注入 FIXED |
| 重启被暂停 | 旧 schema 或缺 `initial_atr`/`initial_stop`/`tp1·tp2` |
| 未登记仓裸奔 | 应有接管钉钉 + `initial_stop`；查 `prepare_manual_adopt` |
| CAP_ALIGN 钉钉 | 仅告警属预期；不应出现市价减仓 |
| `-1003` / IP ban | 暂停观察计时；约 5min 自解；勿连续 rebuild |
| 查询失败误报空仓 | 应 `EXCHANGE_QUERY_FAIL`，账本保留 |
| 同 bar 先开后平 | 查 `webhook_seq_gate` 版本与日志顺序 |

---

## 生产就绪与验收

**状态跟踪（权威）：** [docs/GEMINI_FINAL_STATUS_20260722.md](docs/GEMINI_FINAL_STATUS_20260722.md)  
**判定：Gemini 币安执行层验收通过**（2026-07-22）。明细见 [docs/BINANCE_EXECUTION_ACCEPTANCE.md](docs/BINANCE_EXECUTION_ACCEPTANCE.md)。  
**连续插值呼吸：生产级终验通过**（2026-07-23）。明细见 [docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md](docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md)。

### 上线前 / 回归核对

- [x] Webhook Secret 与 TV JSON 一致；四 action 行为正确  
- [x] 开仓 → TP1/TP2 → 呼吸跟踪 → 反转/止损平仓路径（E2E webhook 实锤）  
- [x] 钉钉杠杆恒为 **5×**；未登记仓位文案诚实  
- [x] `docs/VPS_LIVE_CHECKLIST.md` / `LEGACY_PURGE_LIST` / 最终状态清单一致  
- [x] B1 观察无 TP 重复抖动；B3 全平清零；B2 qty 收缩代码模拟  
- [x] 连续插值 Test1~4：双币持仓观察 ≥5 采样、回测对比、双币/多用户隔离  

### 自动化验收

```bash
cd backend
py -3 -m pytest tests/test_breathing_stop.py tests/test_continuous_breath_and_atr_lock.py \
  tests/test_continuous_prod_isolation.py tests/test_atr_1h_breathing.py \
  tests/test_tv_v6985_sizing.py tests/test_vps_entry_routing.py \
  tests/test_pine_tp_regime_ratios.py tests/test_market_indicators.py \
  tests/test_market_engine_wire.py tests/test_close_alert_utils.py \
  tests/test_position_cap_guard.py tests/test_vps_dev_checklist.py \
  tests/test_v656_core.py tests/test_tp_rebuild_no_duplicate.py \
  tests/test_tp_timeout_no_thrash.py tests/test_tp_fill_stop_qty_resize.py \
  tests/test_tp3_phase2_flat_clear.py tests/test_user_symbol_isolation.py \
  tests/test_deepcoin_binance_parity.py tests/test_manual_adopt.py \
  tests/test_trading_alerts.py tests/test_attribution_evidence_gates.py \
  tests/test_position_query_fail_safe.py -q
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

### 2026-07-23 · 连续插值呼吸生产终验

| Commit / 证据 | 内容 |
|--------|------|
| **连续插值终验** | [CONTINUOUS_BREATH_PROD_TEST_20260723.md](docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md) — Test1~4 **PASS**，可作长期生产配置 |
| `aab2e41` | 连续 `trailDistanceMultiplier`；钉钉平仓归因细化 |
| XAU 参数修正 | 回测后 `coef_min/max` **0.5~1.2**（原文 0.8~1.8 过松）；冷启动 **0.675** |
| `56bdb4b` | 平仓挂单 fail-closed 计数 + 开仓零挂单门禁 |
| 冷启动种子 | 空闲/重置 coef=品种冷启动（禁字面量 1.0 误夹紧/放松） |

### 2026-07-22 · 生产级最终落地

| Commit / 证据 | 内容 |
|--------|------|
| **最终状态** | [GEMINI_FINAL_STATUS_20260722.md](docs/GEMINI_FINAL_STATUS_20260722.md) — **币安执行层验收通过** |
| E2E webhook | LONG 0.029→TP/呼吸→CLOSE_QUICK_EXIT；两处过程异常已闭环说明 |
| 开仓日志措辞 | 空盘口补挂改称「开仓初始化补挂」，避免与旧核武事故混淆 |
| **`77d171b`** | 杠杆根治；未登记仓市价 ATR 接管；CAP trim stub；清除清单 |
| `48ed021` | 观察窗文档 |
| `78ad0d8` | 仓位查询失败≠空仓；平仓归因证据门 |
| `2a64d61` | 防 TP 重复；DeepCoin 对齐 |
| `3524ac6` / `ba76f31` | 止损撤挂抖动；90m 锚点；ATR 两级兜底 |
| `8623f0b` / `3b61a3e` | RISK20；TP12；呼吸引擎收拢止损写入 |

### 历史说明（勿再当现行）

此前 README 中的「路径比例雷达 50/60/70/80」「TP123 基础单×3」「PYRAMID 加仓」「TV `risk_pct`/`tv_sl` 权威算仓与挂止损」「妈妈版权益×1」「钉钉主题可回落 env 25×」「**离散呼吸档位 / XAU trail_tighten×0.8**」等，均已被本节与 `docs/VPS_LIVE_CHECKLIST.md` / `docs/LEGACY_PURGE_LIST_20260722.md` / `docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md` **取代**。

事故档案中的修复思路（先平后开、TP 不重挂已成交档、硬止损禁普通限价秒平等）仍有运维参考价值，但参数与模块名请以**呼吸止损 + RISK20 + FIXED_LEVERAGE**为准。

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。
