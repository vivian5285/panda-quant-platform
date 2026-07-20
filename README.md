# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

> **文档同步（2026-07-20）：** 开仓盘口 = 基础单×3（TP123）+ 条件委托×1（**TV `tv_sl` 硬止损**）；**仓位 = TV `risk_pct`/`qty_ratio`/`leverage` 唯一公式**（已删除 REGIME_MARGIN 旧 sizing）；**雷达 = markPrice WebSocket**；**OPEN 一律先平后开**。实盘事故与优化见 [§实盘事故 · 注意事项 · 优化指南](#实盘事故--注意事项--优化指南)。

| 生产域名 | [https://twinstar.pro](https://twinstar.pro) |
|----------|---------------------------------------------|
| **TV Webhook（Gemini）** | `https://twinstar.pro/gemini/webhook` |
| 仓库 | [github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform) |
| 默认交易对 | **ETH + XAU** 永续双品种（`TRADING_SYMBOLS=ETHUSDT,XAUUSDT`；各所 native 符号见 `symbol_registry.py`） |

> **Gemini 多用户** 支持 Binance / OKX / Gate.io U 本位永续 + DeepCoin SWAP 内测。  
> 同机可共存 **legacy 单账户** 服务：币安大脑 `:5003`、深币 `:5004`，与 Gemini `:6010` **端口与路径互不冲突**。

---

## 🤖 AI Agent 速查（读这一段即可建立全局模型）

```yaml
project: panda-quant-platform
product: GEMINI AI / 双子星AI量化
domain: twinstar.pro
repo_path_on_vps: ~/panda-quant-platform   # 不是 /path/to/...

# 三进程 Docker
services:
  frontend:6080   # React SPA + nginx 反代 /api/
  backend:8000      # FastAPI REST
  backend:6010      # Flask TradingView Webhook（同容器内第二线程）
  redis:6379        # 运行时标记、勿公网暴露

# 信号主链路（毫秒级响应 TV，下单异步）
TradingView POST → nginx /gemini/webhook → 127.0.0.1:6010/webhook
  → 校验 secret / JSON / action / 幂等
  → 立即 HTTP 200
  → 后台线程 SignalDispatcher → 每用户 PositionSupervisor.handle_signal()
  → 交易所 API 实盘下单 + TradeLog + 关键动作钉钉

# 统一交易工厂（全交易所一套逻辑）
trading_factory:
  factory: backend/app/core/exchange_factory.py   # 按 User.exchange 创建 Client + Supervisor
  supervisors:
    binance_okx_gate: backend/app/core/position_supervisor.py
    deepcoin: backend/app/core/position_supervisor_deepcoin.py
  shared_mixins: [PositionCapGuardMixin, AdverseRadarMixin, StartupReconcileMixin]
  binance_only_mixin: BinanceSmartDefenseMixin      # OKX/Gate 复用同一 TP/雷达挂单实现
  shared_modules: [radar_trail, vps_radar_stages, vps_hard_sl, tv_entry_sizing, tp_slice_guard, same_direction_policy, startup_reconcile, close_attribution, webhook_seq_gate, ws_price_listeners, dingtalk_alert_dedupe]
  defense_route_a: |
    开仓盘口 = 基础单×3（TP123 只减仓限价）+ 条件委托×1（TV tv_sl 硬止损 Stop-Limit）；禁止普通限价硬止损（会秒平）；
    硬止损 = 严格按 TV tv_sl 挂单（多空·全所统一）；禁止 VPS 开仓价×档位% 旧宽止损；缺 tv_sl 则告警且不挂宽止损兜底；
    UPDATE_SL → 按新 tv_sl 改挂；雷达达档位路径比例后启动保本追踪（可改条件单槽）；
    DeepCoin 双轨条件单并行
  leverage: |
    开仓/加仓优先用 TV leverage 设交易所杠杆与算仓；config LEVERAGE/OKX/GATE/DEEPCOIN 仅作缺省回退
  sizing: |
    唯一公式：止损距离=|price-tv_sl|；风险金额=权益×(risk_pct/100)；理论仓位=风险/距离；
    杠杆限制=权益×leverage/price；硬上限=50000/price；最终=min(三者)×qty_ratio；floor 到品种步长；
    OPEN/ADD 同一公式；VPS 直接用 TV risk_pct/qty_ratio/leverage；禁止 REGIME_MARGIN 旧逻辑；
    硬止损挂失败 → 立即撤仓（禁止裸奔）
  webhook_order: |
    同 bar OPEN+CLOSE（任意 seq，含 V1.6.10 OPEN:1 CLOSE:2）→ 短暂缓冲后一律先 CLOSE 再 OPEN，最终必须有仓；
    单独 OPEN 等待 WEBHOOK_SEQ_WAIT_SEC 同伴 CLOSE；Redis 幂等 seq:{symbol}_{bar}_{seq} 24h；缺口超时强制先平后开释放


# 执行铁律（PositionSupervisor — 四所相同）
rules:
  - 永远一手、单向持仓 One-Way
  - **铁律 OPEN**：任意带开仓的 TV（LONG/SHORT OPEN）→ **一律先平现有仓/清挂单，再开新仓**（刷新）；同 bar 平+开亦然；最终必有仓
  - **铁律 CLOSE**：单独平仓 TV → 全平 + 撤尽挂单 + 状态清零，干净等待下次 TV（不开新仓）
  - 反方向 / 雷达进行中：同样先平后开
  - PYRAMID / PROFIT_ADD：同向追加（不加强制先平）；无仓或反向则降级 OPEN → 先平后开
  - 开仓后挂 **基础单×3**：TP1/2/3（reduceOnly）+ **TV硬止损 Stop-Limit 条件单**（价格=TV `tv_sl`；禁止普通限价，否则会立刻成交秒平）
  - **硬止损**：严格按 TV `tv_sl`（多空·Binance/OKX/Gate/DeepCoin 统一）；**禁止**开仓价×档位% 旧逻辑；缺 `tv_sl` → `HARD_SL_MISSING` 告警、不漏挂宽止损
  - **雷达（宁松勿紧 · 适度追随）**：按档位 `REGIME_RADAR` 启动 — R1 **85%**/步进35%/呼吸1.0ATR · R2 **80%**/30%/0.8 · R3 **75%**/25%/0.65 · R4 **70%**/20%/0.5；**价格源 = markPrice WebSocket**（`ws_price_listeners`）；紧 TP1 有效比例抬至 ~92%；开仓 25s + 双轮确认；TP 成交强制激活；误挂 `RADAR_REVOKE`；与 TP123/TV硬止损互不抢份额
  - **钉钉**：关键动作实盘核查后推送一次（`dingtalk_alert_dedupe` 去重）；监控循环不刷屏
  - 禁止与 TV 反向持仓：哨兵 / 重启 / 空闲巡检 → FORCE_ALIGN 全平
  - 人工/外部同向仓：manual adopt 后保留仓位，TV CLOSE 不强制全平，补挂 TP123 + **TV硬止损**（雷达按档位路径比例激活）
  - **人工/外部全平**：哨兵/空闲巡检检测到实盘归零 → **立即撤销 TP123 + 硬止损/STOP**（不等待平仓确认），防止孤儿止盈反向开仓
  - **雷达越过 TP1/TP2**：雷达止损有效上移后，若 SL ≥ TP1（多）或 SL ≤ TP1（空），主动撤销过时 TP1/TP2 限价单（`TP_ORPHAN_PURGE`）
  - **加仓合并**：PYRAMID/PROFIT_ADD → 加权均价重置雷达、硬止损沿用/更新 TV `tv_sl`、TV 新 TP123 替换旧限价
  - **三层止损**：TV `CLOSE_STOPLOSS` = 第一指令立即全平；盘口硬止损 = TV `tv_sl` Stop-Limit；6 阶段雷达 = 动态锁利（路径比例启动）
  - 未结清绩效账单 / 用户暂停 / 全局暂停 → 跳过建仓；平仓类信号在暂停时仍放行

# 策略对接（Pine 终极版 / v6.9.x 双品种）
tv_actions: [LONG, SHORT, CLOSE, CLOSE_PROTECT, CLOSE_TP3, CLOSE_STOPLOSS]
entry_fields: [action, secret, symbol, price, regime, atr, tv_tp1, tv_tp2, tv_tp3, tv_sl, risk_pct, leverage, qty_ratio, entry_type?, bar_index?, seq?]
close_fields: [action, secret, symbol, regime, price, atr, side, reason, pnl_pct?, bar_index?, seq?]
extra_actions: [UPDATE_SL]   # 按新 tv_sl 改挂硬止损（全所统一）
note: OPEN/ADD 必填 tv_sl+risk_pct+leverage；qty_ratio OPEN 默认1、加仓常用0.3~0.5；禁止旧 REGIME_MARGIN sizing
dual_symbol: ETHUSDT + XAUUSDT 独立 supervisor；symbol 字段必填（.P 后缀支持）
vps_checklist: docs/VPS_LIVE_CHECKLIST.md   # Cursor 实盘自查清单

# 密钥与配置优先级（重要）
webhook_secret: platform_runtime.json webhook.secret（管理后台）> .env WEBHOOK_SECRET
chain_rpc: platform_runtime.json chain_rpc.*（管理后台）> .env ETH_RPC_URL 等
dingtalk: platform_runtime.json dingtalk.*（管理后台）> .env DINGTALK_*
deposit_hd: platform_runtime.json deposit.*（管理后台）> .env DEPOSIT_HD_MNEMONIC
webhook_secret_length: 无最低长度限制，管理员自行决定（哪怕 1 位）

# 持久化（部署必挂载卷）
volumes:
  backend/data:   SQLite、panda.db、platform_runtime.json
  backend/state:  user_{id}.json 雷达/止盈/TV 状态
  backend/logs:   应用日志
  backend/.env:   只读挂载 /app/.env

# 关键入口文件
webhook_ingress: backend/app/webhook_server.py
dispatch: backend/app/services/dispatcher.py
same_dir_policy: backend/app/core/same_direction_policy.py
trading_control: backend/app/services/trading_control.py
engine: backend/app/core/position_supervisor.py
engine_deepcoin: backend/app/core/position_supervisor_deepcoin.py
exchange_factory: backend/app/core/exchange_factory.py
mixins: backend/app/core/{adverse_radar_guard,binance_smart_defense,startup_reconcile,position_cap_guard}.py
sizing: backend/app/core/tv_entry_sizing.py
radar: backend/app/core/{radar_trail,vps_radar_stages,ws_price_listeners}.py
hard_sl: backend/app/core/vps_hard_sl.py
dingtalk_dedupe: backend/app/services/dingtalk_alert_dedupe.py
close_attr: backend/app/core/close_attribution.py
admin_api: backend/app/api/admin.py
admin_ui_system_tab: frontend/src/pages/admin/tabs/AdminSystemTab.tsx  # Webhook Secret 配置置顶
self_check: production_check.sh + backend/scripts/check_system.py
```

---

## 目录

1. [产品定位与商业模式](#产品定位与商业模式)
2. [角色与权限矩阵](#角色与权限矩阵)
3. [系统架构与数据流](#系统架构与数据流)
4. [配置体系：.env vs 管理后台 vs platform_runtime.json](#配置体系env-vs-管理后台-vs-platform_runtimejson)
5. [项目目录详解](#项目目录详解)
6. [统一交易工厂 · 实盘逻辑全集](#统一交易工厂--实盘逻辑全集)
7. [TradingView Webhook 对接手册](#tradingview-webhook-对接手册)
8. [实盘核实交易日志](#实盘核实交易日志)
9. [钉钉通知策略](#钉钉通知策略)
10. [绩效结算 · 充值监控 · 交易门禁](#绩效结算--充值监控--交易门禁)
11. [推广分润与下级审计](#推广分润与下级审计)
12. [管理后台 16 Tab 全览](#管理后台-16-tab-全览)
13. [用户端页面地图](#用户端页面地图)
14. [安全体系](#安全体系)
15. [API 索引](#api-索引)
16. [交易日志 event_type 词典](#交易日志-event_type-词典)
17. [环境变量速查](#环境变量速查)
18. [本地开发](#本地开发)
19. [VPS 部署与更新](#vps-部署与更新)
20. [HTTPS · Nginx · 多系统共存](#https--nginx--多系统共存)
21. [运维自检与测试命令](#运维自检与测试命令)
22. [故障排查手册](#故障排查手册)
23. [生产就绪清单](#生产就绪清单)
24. [VPS 实盘自查清单](#vps-实盘自查清单)
25. [技术栈与路线图](#技术栈与路线图)
26. [实盘事故 · 注意事项 · 优化指南](#实盘事故--注意事项--优化指南)
27. [更新记录](#更新记录)

---

## 产品定位与商业模式

### 对外 vs 对内

| 维度 | 说明 |
|------|------|
| **用户感知** | 绑定交易所 API → AI 策略托管 ETH 永续 |
| **技术实现** | TradingView Pine 算价发 Webhook → VPS 多用户并发执行 |
| **资金隔离** | 每用户独立 API Key（Fernet 加密），仓位互不影响 |
| **收费** | 周期净盈利 × **25%** AI 绩效服务费（`PLATFORM_FEE_RATE`） |
| **结算周期** | 主周期 **30 天**；无盈利或仍有持仓宽限至 **35 天**；须全平仓后结算 |
| **审计** | 所有实盘动作写 `trade_logs`；钉钉仅抄送**关键摘要** |

### Gemini vs Legacy 单账户

| 系统 | 端口 | Nginx 路径 | 说明 |
|------|------|------------|------|
| **Gemini 多用户（本仓库）** | 8000 / 6010 / 6080 | `/gemini/webhook` | SaaS、**统一交易工厂**、四所 Mixin 栈、结算、推广 |
| 币安单账户大脑 | 5003 | `/binance/webhook` | 独立 legacy，互不共用 Supervisor |
| Deepcoin 单账户 | 5004 | `/deepcoin/webhook` | 独立 legacy |

### 费用与分润（默认）

| 项目 | 比例 | 变量 |
|------|------|------|
| AI 绩效服务费 | 25% 周期净盈利 | `PLATFORM_FEE_RATE` |
| 一级推广 | 10% 下级净盈利（从绩效费池划） | `REFERRAL_L1_RATE` |
| 二级推广 | 5% 下下级净盈利 | `REFERRAL_L2_RATE` |
| 平台净留存 | 约 10%（例：盈利 $1000 → 用户付 $250，L1 $100 + L2 $50，平台 $100） | — |

### 资金闭环

```
TV 信号 → 用户交易所实盘 → 周期结束且全平仓
  → 生成绩效账单（25%）
  → 用户向 HD 专属子地址转 USDT（或 TxHash / 申诉）
  → 链上监控自动匹配（SETTLEMENT_AUTO_CONFIRM）或管理员确认
  → 可选：子地址 USDT 归集至冷钱包
  → 初始本金重置 + L1/L2 奖励入账 → 恢复交易
```

---

## 角色与权限矩阵

| 角色 | 交易日志 | 账户/持仓 | 结算 | 说明 |
|------|----------|-----------|------|------|
| **用户** | 仅本人 `GET /api/users/logs` | Dashboard / Profile | 本人账单 + 一键缴纳 | 成交页可展开实盘核实明细 |
| **管理员** | 全站 + 用户详情 + 系统 Tab 全域日志 | 用户全字段、强制平仓 | 确认收款、申诉审核、到账扫描 | `/admin` 需 `admin` 角色 JWT |
| **推广者 L1/L2** | 仅直接/间接下级 | 下级权益、持仓、结算状态 | 不可操作用户结算 | 推广中心「查看日志」弹窗 |

越权访问下级日志 → `403`。

---

## 系统架构与数据流

```
┌──────────────────────────────────────────────────────────────────┐
│  TradingView Pine（算价、Regime、ATR、tv_tp1/2/3、bar_index/seq、平仓 reason） │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS POST /gemini/webhook
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  nginx → Flask webhook_server :6010                               │
│  secret 校验 · IP 白名单(可选) · 频率限制 · 幂等指纹 · JSON 修复   │
│  ★ 校验通过立即 200，X-Webhook-Latency-Ms 记录耗时                  │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 后台线程
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  SignalDispatcher（ThreadPool 并发）                              │
│  跳过：用户暂停 / 未结清绩效 / 全局暂停(仅建仓) / API 未激活 / 交易所未开放  │
│  平仓 CLOSE* 在用户暂停或全局暂停时仍放行                              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 每用户一把锁 + FIFO 信号队列（最长等 120s）
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  PositionSupervisor    PositionSupervisor    ...
  + Binance/OKX/Gate/DeepCoin Client
  + markPrice WS 雷达 tick（~0.45s）+ 自适应哨兵（远 5s / 近激活 1s / 雷达中 1.2s）+ 10s 空闲巡检
  + state/user_{id}.json
         │                   │
         ▼                   ▼
    用户 A 交易所 API    用户 B 交易所 API
         └─────────┬─────────┘
                   ▼
         trade_logs（detail_json 实盘核实）
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
  用户端        管理端        推广者下级
  TradeLog      全域日志       DownlineLogsModal
                   │
                   ▼
         钉钉（按交易所 GEMINI 主题 #币安25x / #深币25x / #OKX25x / #Gate25x，仅关键动作）
```

### Docker 拓扑

| 服务 | 宿主机端口 | 容器内 | 说明 |
|------|------------|--------|------|
| `frontend` | **6080** → 80 | nginx 静态 + 反代 `/api/` → backend:8000 | 用户/管理 SPA |
| `backend` | **8000** | FastAPI `uvicorn app.main:app` | REST API |
| `backend` | **6010** | Flask `webhook_server` 独立线程 | TV 专用，避开 5002/5003/5004 |
| `redis` | 6379 | 缓存、全局暂停标记 | **禁止公网暴露** |

### 持久化卷（`docker-compose.yml` 已配置）

| 宿主机路径 | 容器路径 | 内容 |
|------------|----------|------|
| `backend/data/` | `/app/data` | `panda.db`、`platform_runtime.json` |
| `backend/state/` | `/app/state` | `user_{id}.json` |
| `backend/logs/` | `/app/logs` | 应用日志 |
| `backend/.env` | `/app/.env`（只读） | 环境变量 |

---

## 配置体系：.env vs 管理后台 vs platform_runtime.json

**原则：** 敏感运维项可在管理后台可视化配置，写入 `backend/data/platform_runtime.json`（Fernet 加密字段），**优先于** `.env`，**保存后立即生效**，多数无需重启。

| 配置项 | 管理后台入口 | runtime 键 | .env 回退 | 备注 |
|--------|--------------|------------|-----------|------|
| **Webhook Secret** | 系统 → TradingView Webhook 密钥（置顶） | `webhook.secret` | `WEBHOOK_SECRET` | **无长度限制**，与 TV JSON `secret` 一致 |
| **Webhook 公网 URL** | 同上只读展示 | — | `API_PUBLIC_URL` + `WEBHOOK_PUBLIC_PATH` | 默认 `https://twinstar.pro/gemini/webhook` |
| **钉钉** | 平台与钱包 → 钉钉告警 | `dingtalk.webhook` / `secret` | `DINGTALK_*` | |
| **链上 RPC** | 平台与钱包 → 链上 RPC | `chain_rpc.eth_rpc_url` 等 | `ETH_RPC_URL` 等 | 充值监控读 `get_rpc_url()`，**非仅 .env** |
| **HD 充值助记词** | 钱包中心 → HD 充值 | `deposit.mnemonic` | `DEPOSIT_HD_MNEMONIC` | |
| **冷/热钱包私钥** | 钱包中心各子页 | `wallet.*` | `PAYOUT_*` 等 | |
| **开放交易所** | 系统 → 平台开放设置 | `platform.enabled_exchanges` | — | 未勾选则用户不可绑 API + 停止 Supervisor |
| **全局交易暂停** | 风控 Tab | Redis `platform:trading_paused` | — | |
| **提现门槛** | 钱包/提现设置 | Redis + runtime | `.env` 默认 | |

### `platform_runtime.json` 结构示例

```json
{
  "webhook": { "secret": "<Fernet 加密>" },
  "dingtalk": { "webhook": "...", "secret": "<加密>" },
  "chain_rpc": {
    "eth_rpc_url": "https://...",
    "bsc_rpc_url": "https://...",
    "arbitrum_rpc_url": "https://...",
    "polygon_rpc_url": "https://...",
    "tron_api_url": "https://api.trongrid.io",
    "tron_api_key": "<加密>"
  },
  "deposit": { "mnemonic": "<加密>" },
  "platform": { "enabled_exchanges": ["binance", "okx"], "support_telegram": "@..." }
}
```

文件路径：`backend/data/platform_runtime.json`（Docker 卷持久化）。

---

## 项目目录详解

```
panda-quant-platform/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口、启动 Supervisor 池、Webhook 线程
│   │   ├── webhook_server.py       # Flask :6010 POST /webhook GET /health
│   │   ├── config.py               # pydantic Settings（读 .env）
│   │   ├── api/
│   │   │   ├── auth.py             # 注册/登录/JWT/验证码
│   │   │   ├── users.py            # 用户资料、日志、同步成交
│   │   │   ├── admin.py            # 管理员全功能 API（见 API 索引）
│   │   │   ├── referrals.py        # 推广 + 下级日志
│   │   │   ├── wallet.py           # 充值/提现/转账
│   │   │   └── system.py           # 系统监控、Webhook 测试
│   │   ├── core/
│   │   │   ├── position_supervisor.py      # ★ Binance/OKX/Gate 统一执行大脑
│   │   │   ├── position_supervisor_deepcoin.py
│   │   │   ├── exchange_factory.py         # ★ 交易工厂：Client + Supervisor 选型
│   │   │   ├── adverse_radar_guard.py      # ★ TV硬止损 + 雷达 + Route A
│   │   │   ├── binance_smart_defense.py    # TP123 对齐/heal（OKX/Gate 复用）
│   │   │   ├── startup_reconcile.py        # ★ 重启接管 + 空闲巡检 + 人工 adopt
│   │   │   ├── radar_trail.py              # 路径激活 / 有效比例 / 开仓保护期
│   │   │   ├── vps_radar_stages.py         # Stage 0~5 锁利
│   │   │   ├── vps_hard_sl.py              # TV tv_sl 权威硬止损（旧 entry% 已废止）
│   │   │   ├── close_attribution.py       # 全平归因
│   │   │   ├── tv_entry_sizing.py          # ★ TV risk 公式 OPEN/ADD sizing（四所统一）
│   │   │   ├── combined_notional.py        # ETH+XAU 合计名义 ≤ 13× 本金
│   │   │   ├── symbol_registry.py          # 品种归一化 ETHUSDT/XAUUSDT
│   │   │   ├── position_cap_guard.py       # 超 cap  trim + 防线重挂
│   │   │   ├── tp_slice_guard.py           # TP123 分批 + consumed 推断
│   │   │   ├── same_direction_policy.py    # 同向 ATR/价差策略（辅助模块）
│   │   │   ├── regime_utils.py             # Regime 1~4 校验
│   │   │   ├── binance_client.py / okx_client.py / gate_client.py / deepcoin_client.py
│   │   │   ├── position_manager.py
│   │   │   └── symbol_precision.py         # ETH tick 0.01
│   │   ├── models/__init__.py      # User, Trade, TradeLog, Settlement, ...
│   │   ├── schemas/__init__.py     # Pydantic 出入参
│   │   └── services/
│   │       ├── dispatcher.py             # Supervisor 池 + 广播 + 风控门禁
│   │       ├── trading_control.py        # 用户/全局暂停、风险档位 risk_multiplier
│   │       ├── webhook_payload.py        # TV JSON 解析/修复（含 Pine 缺引号）
│   │       ├── webhook_guard.py          # secret/IP/频率/action 白名单
│   │       ├── webhook_secrets.py        # 管理后台 Webhook Secret
│   │       ├── webhook_idempotency.py    # 指纹去重；bar_index+seq → 24h Redis 键
│   │       ├── webhook_seq_gate.py       # bar_index/seq 有序缓冲与缺口等待
│   │       ├── chain_rpc_config.py       # 管理后台 RPC
│   │       ├── dingtalk_notify.py          # 钉钉攒批 + 重试 + 企业微信兜底
│   │       ├── dingtalk_secrets.py       # 管理后台钉钉
│   │       ├── trading_alerts.py           # 按交易所主题推送
│   │       ├── alert_service.py          # notify_admin / notify_system
│   │       ├── deposit_monitor.py        # 链上到账扫描
│   │       ├── settlement.py             # 绩效结算
│   │       ├── settlement_payment_tracking.py
│   │       ├── platform_runtime.py       # runtime.json 读写
│   │       ├── startup_audit.py          # 生产检查、接管审计
│   │       └── radar_context.py          # 重启接管交叉验证
│   ├── scripts/check_system.py     # 容器内全域自检
│   ├── tests/                      # pytest
│   └── .env.example
├── frontend/
│   └── src/
│       ├── pages/                  # 用户页 + Admin.tsx
│       ├── pages/admin/tabs/       # 16 个懒加载管理 Tab
│       ├── components/TradeLogDetailPanel.tsx
│       └── i18n/locales/{zh,en}.ts
├── deploy/                         # nginx、HTTPS、UFW 脚本
├── docker-compose.yml
├── deploy.sh                       # 一键部署
└── production_check.sh             # 宿主机自检（调用 check_system.py）
```

---

## 统一交易工厂 · 实盘逻辑全集

> **核心原则：四所一套逻辑。** Binance / OKX / Gate / DeepCoin 共用同一套 Mixin 栈、信号链路、防线编排、重启接管与空闲巡检；`exchange_factory.py` 仅负责选型 **Client + Supervisor**，DeepCoin 仅在 **数量单位** 与 **止损挂单形态** 上有最小差异。

### 0. 工厂架构一览

```
exchange_factory.create_supervisor(user, client)
        │
        ├─ Binance / OKX / Gate → PositionSupervisor
        │     Mixins: PositionCapGuard + AdverseRadar + BinanceSmartDefense + StartupReconcile
        │
        └─ DeepCoin → DeepcoinPositionSupervisor
              Mixins: PositionCapGuard + AdverseRadar + StartupReconcile
              （TP/雷达挂单逻辑内联，语义与 BinanceSmartDefense 对齐）
```

| 层级 | 模块 | 文件 | 四所共享 |
|------|------|------|----------|
| 工厂 | Client / Supervisor 创建 | `exchange_factory.py` | ✅ |
| 信号 | FIFO 队列 + `_execute_signal` | `position_supervisor*.py` | ✅ |
| 开仓量 | TV risk_pct 公式 OPEN/ADD | `tv_entry_sizing.py` | ✅ |
| 硬止损 + 雷达 | Route A 三层防线 | `adverse_radar_guard.py` + `radar_trail.py` | ✅ |
| 止盈 | TP123 对齐 / heal | `binance_smart_defense.py`（DeepCoin 内联） | ✅ 语义 |
| 重启 / 巡检 | 接管 + manual adopt | `startup_reconcile.py` | ✅ |
| 超 cap | trim + 重挂 | `position_cap_guard.py` | ✅ |
| 交叉验证 | 重启恢复上下文 | `services/radar_context.py` | ✅ |

**DeepCoin 仅有的差异：**

| 项 | Binance / OKX / Gate | DeepCoin |
|----|----------------------|----------|
| 数量单位 | ETH（`round_quantity`） | 合约张（`face_value=0.1`，整数张） |
| 状态文件 | `state/user_{id}.json` | `data/supervisor/deepcoin_{id}/` |
| 止损形态 | **开仓：硬止损 = TV tv_sl Stop-Limit**（基础单 TP123×3）；雷达启动后可改合并条件追踪槽 | **双轨并行** — TV硬止损 + 雷达条件单 |
| Mixin | 含 `BinanceSmartDefenseMixin` | 不含，方法内联等价实现 |

---

### 一、实盘需求总览

| 需求 | 说明 |
|------|------|
| **极速响应 TV** | 网关校验通过后 **立即 HTTP 200**，下单在后台线程异步执行 |
| **永远一手** | 单向 One-Way；工厂 OPEN 同向已有仓 → **先平后开**（人工 adopt 同向仓除外） |
| **策略价格由 TV 指挥** | `price/regime/atr/tv_tp1~3/tv_sl` 由 Pine 下发；VPS 执行、挂单、雷达、对齐 |
| **VPS 独立 sizing** | 唯一公式：权益×risk_pct/\|price−tv_sl\|，再与杠杆限制、50k 硬顶取 min × qty_ratio；硬止损 = TV `tv_sl` |
| **逆势零容忍** | 实盘方向 ≠ `last_tv_side` → 哨兵/重启/空闲巡检 `FORCE_ALIGN` |
| **人工仓保护** | manual adopt 后：TV CLOSE 不强制全平；补挂 TP123 + **TV硬止损** + 雷达待命 |
| **全链路可审计** | 所有决策写 `trade_logs.detail_json`；关键动作钉钉（含盘口结构 / 雷达有效路径 / 平仓归因） |
| **风控可门禁** | 暂停/绩效未缴/全局暂停 → 跳过建仓；**CLOSE\* 仍放行** |
| **盘口结构** | 开仓后币安「基础单」应为 **3**：TP1+TP2+TP3；「条件委托」**1**：TV `tv_sl` 硬止损 Stop-Limit（雷达启动前） |

---

### 二、统一信号链路

```
TradingView POST /gemini/webhook
  → webhook_server.py :6010（同步校验 → HTTP 200）
  → SignalDispatcher.dispatch()（线程池广播）
  → supervisor.handle_signal()（每用户 FIFO 队列，最长等 120s）
  → _execute_signal()
       ├─ LONG / SHORT / PYRAMID / PROFIT_ADD → _handle_tv_entry()
       ├─ CLOSE / CLOSE_PROTECT / CLOSE_TP3 → 全平（manual adopt 同向可跳过）
       ├─ CLOSE_STOPLOSS → 立即市价全平（第一优先级）
       └─ UPDATE_SL → 按新 TV tv_sl 改挂硬止损
  → set_leverage(TV leverage) → 市价开/平 → 挂 TP123 + TV硬止损(必须成功否则撤仓) → 启动哨兵
```

**设计原则：** 网关只做收信；**所有实盘决策在 Supervisor 线程**完成。

#### 分发门禁

| 条件 | LONG/SHORT/ADD | CLOSE\* |
|------|----------------|---------|
| 用户 inactive / API 未激活 | 跳过 | 跳过 |
| 交易所未开放 | 跳过 | 跳过 |
| 用户暂停 / 绩效未缴 | 跳过 | **仍执行** |
| 全局暂停 | 网关 503 拦截建仓 | **放行** |

`risk_multiplier = global_risk × 用户档位`（0.6 / 1.0 / 1.4）注入 payload，用于 **cap guard** 与 regime margin 缩放。

---

### 三、统一 TV 信号规则

#### OPEN（`entry_type` 缺省或 `OPEN`）

| 场景 | 四所行为 |
|------|----------|
| 空仓 | TV risk 公式算仓开仓 → **TP123 限价 + TV硬止损 Stop-Limit** + 哨兵（雷达待命） |
| 已有仓 · **工厂单** | **先平后开** |
| 已有仓 · **人工 adopt 同向** | 保留仓位，刷新 TP / 硬止损限价 / 雷达状态 |
| 反方向 | **先平后开** |

#### PYRAMID / PROFIT_ADD

| 规则 | 说明 |
|------|------|
| 数量 | **同一 TV risk 公式** × `qty_ratio`（加仓常用 0.3~0.5；缺省回退 R1=0/R2=0.3/R3=0.5/R4=0.7） |
| 次数上限 | 按档位：R1=1 / R2=2 / R3=2 / R4=3（`MAX_ADD_TIMES_REG*`） |
| 加仓后 | **核武清场重挂** TP123：按 TV 最新 `tv_tp1/2/3` 价格 + 新总头寸 × regime 比例重算分批；同步 **TV硬止损**（沿用/更新 `tv_sl`）；**雷达按新 entry/TP1 距离重置**（四所相同 `_rebuild_defenses_after_tv_add`） |

#### CLOSE / CLOSE_PROTECT / CLOSE_TP3

工厂单 → 全平；manual adopt 同向 → 可跳过 CLOSE，刷新防线。空仓 `CLOSE_PROTECT` → 撤单复位。

#### UPDATE_SL

按 payload `tv_sl` **改挂盘口硬止损**（全所统一）；缺 `tv_sl` 则跳过并告警。

#### TV 硬止损（权威价 = TradingView `tv_sl` · 多空 · 四所统一）

```
硬止损挂单价 = TV tv_sl（严格按策略下发；禁止 VPS 开仓价×档位% 旧宽止损）
缺 tv_sl     → HARD_SL_MISSING 告警，不挂宽止损兜底（禁止漏挂假宽止损）
UPDATE_SL  → 用新 tv_sl 强制改挂
```

历史表 `REGIME_HARD_SL_PCT`（2.78/3.89/5.56/8.33%）**仅文档/审计保留，不参与实盘挂单**。

**开仓挂单形态（Binance / OKX / Gate · 四所同逻辑）：**

| 项目 | 说明 |
|------|------|
| 订单类型 | **Stop-Limit / 条件全平槽**（币安 UI：**条件委托**）；禁止普通限价硬止损（会秒平） |
| 价格 | **TV `tv_sl`** |
| 数量 | 全仓位（或 closePosition 槽） |
| 与 TP 合计 | **基础单 = 3**（TP123）+ **条件委托 = 1**（TV硬止损）；雷达启动后可改同一合并槽 |
| 降级 | Stop-Limit → STOP_MARKET（qty）→ closePosition（最后手段，应告警） |
| DeepCoin | 条件触发单（限价优先，失败市价）· 双轨可并行雷达 |

优先级：`CLOSE_STOPLOSS` 立即市价全平 > 盘口 TV硬止损成交 > `UPDATE_SL` 改挂。
---

### 四、统一开仓 Sizing（TV 唯一公式 · 四所相同 · ETH+XAU）

实现：`tv_entry_sizing.py` · **已删除 REGIME_MARGIN 旧逻辑**

```
止损距离   = |price − tv_sl|
风险金额   = 账户权益 × (risk_pct / 100)     # risk_pct 由 TV 下发，如 0.81 / 2.03
理论仓位   = 风险金额 / 止损距离
杠杆限制   = 账户权益 × leverage / price     # leverage 由 TV 下发
硬上限     = 50000 / price
最终下单量 = min(理论仓位, 杠杆限制, 硬上限) × qty_ratio
精度       = floor(量 / 步长) × 步长         # ETH 0.001 / XAU 0.01
```

VPS **直接使用** TV 的 `risk_pct` / `qty_ratio` / `leverage`，不重新计算。OPEN 默认 `qty_ratio=1`；加仓用 TV `qty_ratio`（常见 0.3~0.5）。

| 参数 | 来源 | 说明 |
|------|------|------|
| `risk_pct` / `qty_ratio` / `leverage` | **TV 必填** | 权威；缺则拒单 / 不下单 |
| `tv_sl` | **TV 必填** | 同时用于 sizing 距离 + 硬止损挂单价 |
| `HARD_NOTIONAL` | 50000 U | 单笔名义硬顶 |
| `MAX_COMBINED_NOTIONAL_MULT` | **13.0** | ETH+XAU 合计名义上限（安全闸） |
| `ADD_RATIO_REG1~4` | 0 / 0.3 / 0.5 / 0.7 | TV 未传 qty_ratio 时的加仓回退 |
| `MAX_ADD_TIMES_REG1~4` | 1 / 2 / 2 / 3 | 各档位最大加仓次数 |

算账示例（本金 1000 U · ETH@1892.43 · qty_ratio=1 · leverage=25）：

| Regime | risk_pct | 止损距离 | 下单量 |
|--------|----------|----------|--------|
| R1 | 0.81% | 12.08 | **0.67 ETH** |
| R2 | 1.35% | 14.09 | **0.96 ETH** |
| R3 | 2.03% | 14.02 | **1.45 ETH** |
| R4 | 2.70% | 15.94 | **1.69 ETH** |

换算：任意本金下单量 = 上表(1000U) × (本金/1000)。硬止损挂单价 = TV `tv_sl`（权威）。

---

### 五、统一防线 · Route A

```
① TV硬止损            严格按 TV tv_sl · Stop-Limit/条件槽（多空·全所统一）
② 雷达保本 (radar)    价格达 TP1 有效路径比例后激活 · Stage 0~5 ATR 追踪
③ TP123               regime 比例 reduceOnly 限价（基础单）
```

#### 开仓盘口结构（核对用）

| 交易所 UI | 开仓后应见 | 不应见 |
|-----------|------------|--------|
| 币安「基础单」 | **3**（TP1+TP2+TP3） | 硬止损误挂普通限价 → 秒平 |
| 币安「条件委托」 | **1**（TV硬止损 Stop-Limit；雷达启动前） | 缺 tv_sl / 降级 STOP_MARKET |
| 钉钉开仓文案 | `盘口结构：基础单×3 + 条件委托×1…` · `TV硬止损（已挂单）` | 把硬止损挂成普通限价秒平 |

#### 雷达启动（全所同一套 `evaluate_radar_arm_gate` + `REGIME_RADAR`）

| 档位 | 激活（entry→TP1） | 前进步进 `move_step` | 呼吸 `trail_offset` | 说明 |
|------|-------------------|----------------------|---------------------|------|
| R1 震荡 | **85%** | **35%** | **1.0 ATR** | 宁松勿紧 · 适度追随 |
| R2 弱势 | **80%** | **30%** | **0.8 ATR** | |
| R3 中势 | **75%** | **25%** | **0.65 ATR** | |
| R4 强势 | **70%** | **20%** | **0.5 ATR** | 非紧追 |

**价格监控（最快路径）：**

| 层 | 机制 | 周期 |
|----|------|------|
| **主** | 各所 `markPrice` WebSocket → `ws_price_listeners` → `_radar_ws_fast_tick` | 节流 **~0.45s** |
| **兜底** | 哨兵 REST `get_current_price(prefer_ws=True)` | 远 **5s** / 近激活 **1s** / 雷达中 **1.2s** |

WS tick 同步：剩余头寸、`consumed_tp_levels`、TP123 路径进度、按档位挂/移雷达止损。平仓后 `_unbind_price_ws_listener`。

**附加全域护栏（防刚开仓噪声误挂保本）：**

1. **有效激活**：若 `|TP1−entry| < 1×ATR`，有效路径抬至约 **92%**（再叠加绝对位移地板：`max(0.55×ATR, 0.15%×entry)`）
2. **开仓保护期**：`trade_opened_at` 后 **25s** 内禁止路径启动
3. **双轮确认**：连续 **2** 次确认均达有效比例才 `_latch_radar`
4. **误挂撤销**：未达条件却出现保本 SL → `RADAR_REVOKE` 恢复硬止损
5. **TP 成交**：`tp1/2/3_filled` **强制**激活 + 合并单槽挂保本 STOP + 盘口核实钉钉（不与 TP 限价抢份额）
6. **禁止死亡螺旋**：头寸因 TP1/2 成交减少后，**绝不**把「盘口 TP 限价消失」当成漏挂而按缩减后仓位重挂同价 TP1；`consumed_tp_levels` + 现价已达/qty+book 证据 → `TP_SKIP_REHANG` 钉钉拒绝补挂
7. **防秒挂秒撤**：盘口已对齐 → `live_already_aligned` / `on_book` 跳过；WS 与哨兵共用锁，禁止新旧雷达/宽止损双系统抢权限

**止盈成交对账（全所）：**

| 事件 | 系统行为 | 钉钉 |
|------|----------|------|
| **TP 价已达 + 该档限价消失** | 认定成交，记入 `consumed`，**绝不重挂**该档，耐心等更高档 | `TP_FILLED`（一次） |
| ETH/XAU 市价引起的细微 qty 漂移 | 忽略（漂移阈值 8%）；不以噪声当漏挂 | — |
| 现价在 TP1 附近但 TP1 已成交 | 跳过补挂 TP1，剩余只挂 TP2/TP3 | `TP_SKIP_REHANG` |
| 路径达档位激活% 或 TP 吃单 | 雷达启动并按 `move_step` 随 TP2/TP3 前进（条件槽） | `RADAR_ARM` / `TRAIL`（一次） |
| TV硬止损 | 合并槽 / DeepCoin 双轨，与 TP123 限价互不抢份额；价=tv_sl | 开仓钉钉 |

**三层分工（互不抢份额）：** `TP123 限价` ‖ `TV硬止损(tv_sl)` ‖ `雷达追踪条件槽` ‖ 各自推进，定期补挂只动 TP 限价。

**锁利阶段（启动后 · 步进=档位 `move_step`，非固定 50%）：**

| Stage | 含义 |
|-------|------|
| 0 | 仅硬止损防守 · 雷达候命 |
| 1 | 路径达激活 · 保本锁润 |
| 2 | TP1→TP2 达 `move_step` · 追踪前进 |
| 3 | 到达 TP2 · 锁利 |
| 4 | TP2→TP3 达 `move_step` · 加深 |
| 5 | 到达 TP3 · 极限保护 |

- **合并语义（Binance/OKX/Gate）：** 开仓硬止损 = Stop-Limit 条件单（价=tv_sl）；雷达激活后合并槽取 LONG `max(tv_sl, radar)` / SHORT `min(...)`
- **DeepCoin：** VPS/条件止损与雷达条件单并行（双轨）
- **STOP 安全钳制：** `clamp_stop_market_safe()` 防止追踪 SL 越过 mark 瞬间全平
- **平仓归因：** 近入场 + 近雷达 SL 优先判 `exchange_stop`，避免 0.15% 容差把保本误标成 TP1（`close_attribution.py`）

> 完整自查清单：**[`docs/VPS_LIVE_CHECKLIST.md`](docs/VPS_LIVE_CHECKLIST.md)**

---

### 六、Regime 参数（`tp_regime_ratios.py` · Pine qty_percent 对齐）

与 Pine 策略 `strategy.exit` 的 `qty_percent` **逐档对齐**；四所共用 `build_regime_settings()`。
OPEN 仓位见上节 **TV risk 公式**（`risk_pct`/`qty_ratio`/`leverage`），勿与下表 TP 分批比例混淆。

| Regime | OPEN 保证金权重 | TP 分批 (%) | 雷达激活 | 步进 | 呼吸 ATR× |
|--------|-----------------|-------------|----------|------|-----------|
| 1 | **8%** | **25/35/40** | **85%** | **35%** | **1.00** |
| 2 | **14%** | 20/35/45 | **80%** | **30%** | **0.80** |
| 3 | **20%** | 18/32/50 | **75%** | **25%** | **0.65** |
| 4 | **26%** | 5/20/75 | **70%** | **20%** | **0.50** |

> 雷达参数唯一源码：`backend/app/core/radar_trail.py` → `REGIME_RADAR`（与上表一致）。

钉钉开仓/加仓/重启明细会显示：`止盈比例 TP1/2/3 = xx/xx/xx%`、`雷达状态`（档位% / 本笔有效%）、`雷达触发价`、`盘口结构`。

---

### 七、重启接管 + 空闲巡检

**重启：** DB/Webhook/state 交叉验证 → `loss_shield` / `profit_radar` 分轨 → TP123 + **TV硬止损** + 雷达状态恢复 → 哨兵

**空闲巡检（10s，`monitoring=False`）：** 账本/实盘偏差收口 · 反向 FORCE_ALIGN · 同向 manual adopt · dust 扫尾

---

### 八、哨兵 + WebSocket 雷达（自适应）

| 模式 | 周期 | 用途 |
|------|------|------|
| WS mark 推送 | ~0.45s | TP1 路径 / 雷达激活与前进（主路径） |
| 哨兵 · 远 TP1 | **5s** | 方向背离 · 仓异动 · cap · 敞口巡检 |
| 哨兵 · 近激活 | **1s** | 路径接近档位激活比例 |
| 哨兵 · 雷达中 | **1.2s** | 追踪 / TP 对账 / 补挂兜底 |

方向背离 · 仓位异动(TP/人工) · 雷达追踪 · cap trim · 全平归因 · **头寸↔止盈挂单敞口巡检**

**敞口巡检（每轮哨兵）：** 实盘持仓 vs reduceOnly 止盈挂单合计
- `tp_booked_sum > live_qty` → `TP_OVER_COMMIT` 核武重挂 + 钉钉
- 实盘方向 ≠ TV/账本方向（如平多过量变蚂蚁空仓）→ `POSITION_SIDE_FLIP` 强平对齐 TV + 钉钉
- 加仓后 `_rebuild_defenses_after_tv_add` 结束再核实敞口，雷达按新总头寸同步

---

### 九、同向 ATR 模块（辅助）

`same_direction_policy.py` 提供 ATR/档位/价差决策。当前工厂 OPEN 主路径为 **先平后开**；manual adopt 走 preserve。同向仅更新止盈逻辑保留供扩展。

---

### 十、铁律 · 人工 · heal

| 规则 | 四所 |
|------|------|
| 反方向 | 先平后开 |
| 逆势 | FORCE_ALIGN |
| 人工加仓/减仓 | 重构防线 + ADJUST |
| TP heal | 对齐跳过；缺失则 `_smart_realign_defenses()` |

审计：`GET /api/admin/startup-audit` · 关键字 `VPS STARTUP` / `idle_patrol`

### 信号队列

FIFO · 锁超时 120s → `LOCK_TIMEOUT` · 建仓前 TOCTOU 二次校验暂停

---

## TradingView Webhook 对接手册

### URL（生产）

```
https://twinstar.pro/gemini/webhook
```

内网直连（仅调试）：`http://127.0.0.1:6010/webhook`

### Secret 配置

1. **推荐：** 管理后台 → **系统健康** → 最上方 **TradingView Webhook 密钥** → 保存（加密写入 runtime，**立即生效**）
2. **或：** `backend/.env` → `WEBHOOK_SECRET=...`（需 `docker compose up -d --force-recreate backend`）
3. Pine JSON 中 `"secret"` 必须与上完全一致；**长度无限制**（管理员自定）

### 支持的 action

| action | 说明 | TV 是否常用 |
|--------|------|-------------|
| `LONG` | 开多（工厂同向先平后开） | ✅ |
| `SHORT` | 开空（工厂同向先平后开） | ✅ |
| `CLOSE` | 换防清场全平（manual adopt 同向可跳过） | 可选 |
| `CLOSE_PROTECT` | 保护性全平（带 reason、pnl_pct） | ✅ |
| `CLOSE_TP3` | TP3 终极收网全平 | ✅ |
| `CLOSE_STOPLOSS` | TV 止损类全平（平台立即市价） | ✅ |
| `UPDATE_SL` | 按新 TV `tv_sl` **改挂**硬止损 | 可选 |

### 开仓 JSON（含时序字段）

```json
{
  "symbol": "ETHUSDT.P",
  "action": "SHORT",
  "entry_type": "OPEN",
  "secret": "你的密码",
  "price": 1840.34,
  "regime": 1,
  "atr": 4.44,
  "tv_tp1": 1837.01,
  "tv_tp2": 1834.12,
  "tv_tp3": 1831.46,
  "tv_sl": 1844.34,
  "risk_pct": 0.81,
  "leverage": 25,
  "qty_ratio": 1,
  "bar_index": 27048,
  "seq": 1
}
```

> **必填：** `tv_sl`（硬止损+算仓距离）· `risk_pct` · `leverage` · `qty_ratio`（OPEN 默认 1）。  
> `entry_type` 可选 `OPEN` / `PYRAMID` / `PROFIT_ADD`。`symbol` 必填（支持 `.P`）。仓位严格按 TV risk 公式，禁止 REGIME_MARGIN。

### 时序字段（bar_index + seq）

策略 Webhook 应带上：

| 字段 | 含义 |
|------|------|
| `bar_index` | 当前 K 线索引 |
| `seq` | 同一 `bar_index` 内从 1 递增的事件序号 |

```json
{
  "action": "CLOSE_PROTECT",
  "secret": "你的密码",
  "symbol": "ETHUSDT.P",
  "bar_index": 200,
  "seq": 1
}
```

**TV 同 K 线 OPEN+CLOSE（VPS 铁律 · 四所统一）：**

| TV 发出 | 含义 | VPS |
|---------|------|-----|
| 仅 `CLOSE_*` | 保护性/止损全平 | 执行平仓，仓位归零，撤尽挂单 |
| `CLOSE_*` + `OPEN`（**任意 seq**，含 V1.6.10：OPEN `seq=1` + CLOSE `seq=2`） | 同秒刷新 | **短暂缓冲 → 一律先平后开**；最终实盘**必须有仓**；再挂 TP123/硬止损/雷达候命；钉钉实盘后推一次 |
| 仅 `OPEN` | 空仓开仓 | 等待 `WEBHOOK_SEQ_WAIT_SEC` 同伴 CLOSE；超时后开仓 |

> **禁止**按 seq 数字先开后平（会导致开仓秒平）。排序键：`先 CLOSE 再 OPEN`，seq 仅作次要键。单独 OPEN 会短暂停顿等同伴 CLOSE。

**VPS 规则（全所共用）：**

1. **排序**：`bar_index` ↑ → `seq` ↑ → **CLOSE 优先于 OPEN** → 入队时间
2. **幂等**：`seq:{symbol}_{bar}_{seq}_{action}_{price}_{tps}`，TTL 24h
3. **串行派发**：同 symbol 串行，保证 CLOSE 整段完成后再 OPEN
4. **干净翻仓**：平仓必须仓位归零 + 撤尽 TP/雷达/硬止损；OPEN 前再扫一遍挂单（钉钉 `FLIP_CLEAN`）
5. **乱序**：缺前置 `seq` 暂存 `WEBHOOK_SEQ_WAIT_SEC`（默认 3s），超时钉钉后强制释放
6. **最终状态**：开/平后交易所对账（`POSITION_RECONCILE`）

实现：`webhook_seq_gate.py` · `webhook_idempotency.py` · `webhook_server.py` · `_force_flat_before_open`

### 保护性全平 JSON

```json
{
  "action": "CLOSE_PROTECT",
  "secret": "你的密码",
  "regime": 2,
  "price": 3480,
  "atr": 12.5,
  "side": "LONG",
  "reason": "ADX衰减/波动率保护",
  "pnl_pct": -1.25
}
```

### TP3 全平 JSON

```json
{
  "action": "CLOSE_TP3",
  "secret": "你的密码",
  "regime": 1,
  "price": 3800,
  "atr": 12.5,
  "side": "LONG",
  "reason": "TP3终极收网"
}
```

### CLOSE_STOPLOSS JSON（TV 止损类 · 立即市价全平）

```json
{
  "action": "CLOSE_STOPLOSS",
  "secret": "你的密码",
  "symbol": "ETHUSDT.P",
  "regime": 1,
  "price": 1844.34,
  "atr": 4.44,
  "side": "SHORT",
  "reason": "TV stoploss",
  "bar_index": 27048,
  "seq": 2
}
```

> `CLOSE_STOPLOSS` 是 TV 指令优先全平；盘口硬止损 = TV `tv_sl` 条件单。二者都可能触发离场。

> **Pine 常见坑：** `CLOSE_PROTECT` JSON 里 `side`、`reason` **必须闭合引号**，否则 TV 报 400。Gemini 网关对 v6.9.30 类缺引号格式有兼容修复（`webhook_payload.py`）。

### 网关时序

| 阶段 | 行为 |
|------|------|
| 同步 | 校验 → **立即 HTTP 200**（通常 <50ms） |
| 时序门 | `bar_index+seq` 排序 / 缺口等待后按序释放 |
| 异步 | **按 symbol 串行**派发（保证同品种 CLOSE→OPEN 不竞态），用户侧仍可并发 |
| 幂等 | 时序指纹含 action+价格/TP（24h）；无时序字段用内容指纹（默认 120s）→ `{ "status": "duplicate" }` |

响应头：`X-Webhook-Latency-Ms`

---

## 实盘核实交易日志

### 原则

1. 用户可见交易动作均入库 `trade_logs`
2. `trade_logger.enrich_detail()` 附加 `live_verified`、`verified_at`、`source`
3. 前端统一 `TradeLogDetailPanel` 展示
4. **钉钉不替代日志**

### detail_json 常用字段

| 字段 | 说明 |
|------|------|
| `live_verified` | `true` = Supervisor 实盘核实 |
| `source` | `platform_supervisor` / `binance_exchange_sync` |
| `live_audit` | 止盈扫描：aligned、duplicate_tps、missing_tps |
| `tv_tps` / `regime` / `side` / `qty` / `entry` | 仓位上下文 |
| `held_atr` / `new_atr` / `atr_changed` | 同向智能筛选 ATR 比对 |
| `price_diff_pct` / `threshold_pct` / `decision` | 同向价差与决策原因 |
| `old_tv_tps` / `new_tv_tps` | 仅更新止盈时的前后对比 |
| `pnl` / `funding_fee` / `exit_price` | 平仓 |
| `close_action` | CLOSE_TP3 / CLOSE_PROTECT 等 |

### 查看入口

| 角色 | 路径 |
|------|------|
| 用户 | `/trades?tab=logs` |
| 管理员 | `/admin` → 用户详情日志 / **系统 → 全域交易日志** |
| 推广者 | `/referrals` → 查看日志 |

---

## 钉钉通知策略

配置：管理后台 **平台与钱包 → 钉钉告警**（或 `.env` `DINGTALK_*`）。

### 发送节流、去重与重试

- **动作级去重**：`dingtalk_alert_dedupe.py` — 同类关键动作（开仓/雷达启动/TP 成交/追踪前进等）实盘核查后 **推送一次**，监控循环不刷屏
- **攒批**：默认最多 `DINGTALK_BATCH_MAX=8` 条或 `DINGTALK_BATCH_FLUSH_SEC=6` 秒合并为一条 Markdown 摘要（规避 20 条/分钟限流）
- **重试**：失败后指数退避 1s / 2s / 4s（`DINGTALK_RETRY_MAX`）
- **兜底**：重试耗尽后若配置了 `WECOM_WEBHOOK`，改推企业微信群机器人
- `critical` 系统告警 / 归集失败可走 `immediate` 立即发送

### 用户实盘钉钉（`trading_alerts.py`）

按用户绑定交易所选 **GEMINI量化** 独立主题（与原版黑金币安单机系统 UI 区分）：

| 交易所 | 标签 | 主题色 | 品牌 |
|--------|------|--------|------|
| Binance | `#币安25x`（读 `LEVERAGE`） | 靛蓝 🔷 | GEMINI量化 · 币安合约实盘引擎 |
| DeepCoin | `#深币25x` | 翡翠绿 🟢 | GEMINI量化 · 深币 SWAP 实盘引擎 |
| OKX | `#OKX25x` | 紫罗兰 🟣 | GEMINI量化 · OKX 合约实盘引擎 |
| Gate | `#Gate25x` | 琥珀橙 🟠 | GEMINI量化 · Gate 合约实盘引擎 |

前端 API 绑定页交易所卡片使用同色主题（`exchange-picker-{exchange}`），便于与原版系统视觉区分。

**会推送：** `OPEN`、`PYRAMID`、`PROFIT_ADD`、`NOTIONAL_CAP`、`CLOSE`、`CLOSE_TP3`、`CLOSE_PROTECT`、`CLOSE_STOPLOSS`、`CLOSE_ATTRIBUTION`、`POSITION_RECONCILE`、`RADAR_ARM`、`RADAR_REVOKE`、`TRAIL`、`SAME_DIR_TP_REFRESH`、`SAME_DIR_REOPEN`、`STARTUP`、`STARTUP_FAIL`、`FORCE_ALIGN`、`POSITION_SIDE_FLIP`、`TP_OVER_COMMIT`、`ADJUST`、`MANUAL_ADJUST`、`DEFENSE_HEAL_FAIL`、`INSUFFICIENT_BALANCE`、`LOCK_TIMEOUT`、`TP_RETRY_FAIL`、`API_OFFLINE`、`SENTINEL_ERROR`、`severity=critical`

**平仓来源区分（钉钉标题/核实明细）：**

| 场景 | 钉钉识别 |
|------|----------|
| 路径达档位激活%（R1 85% / R2 80% / R3 75% / R4 70%）首次挂保本 | `RADAR_ARM`「雷达启动·防回吐」· 启动来源=路径（每笔一次） |
| TP1/2/3 限价吃单后强制保本 | `RADAR_ARM`「雷达启动·…后防回吐（止盈成交）」· 启动来源=TP成交 |
| 盘口归零·限价止盈 | `CLOSE_ATTRIBUTION`「限价止盈成交·TP…」 |
| 盘口归零·雷达/条件止损 | `CLOSE_STOPLOSS`「保本雷达/条件止损触发」 |

**开仓钉钉关键字段：**

| 字段 | 含义 |
|------|------|
| 盘口结构 | 基础单×3：TP123 + 条件委托×1：TV硬止损 Stop-Limit |
| TV硬止损 | `@价 = TV tv_sl · Stop-Limit 条件单` |
| TV tv_sl | 与盘口硬止损同价（权威） |
| 雷达状态 | 待命 · 档位路径%（本笔有效%：TP1 间距收紧） |
| 雷达触发价 | 现价需达的近似价（有效路径 × TP1 间距） |

**不推送（仅 TradeLog）：** `DEFENSE_HEAL`、`DEFENSE_HEAL_OK`、`SIGNAL`、`TP_RETRY`、`ADVERSE_SL_REPAIR` 等过程类

### 平台级钉钉（`notify_system`）

`SYSTEM_RESTART`、`SYSTEM_INIT_FAIL`、`DISPATCH_*`、`SETTLEMENT_APPEAL` 等

---

## 绩效结算 · 充值监控 · 交易门禁

### 结算周期

1. API 绑定或上次确认后开始 **30 天**周期
2. 到期：无盈利或仍有持仓 → 宽限 **35 天**
3. 全平仓 + 有净盈利 → 账单 `pending`
4. 用户缴纳 → `submitted` → 链上自动匹配或管理员确认 → `paid`/`confirmed`
5. 本金重置、推广分润、**恢复交易**

### 未缴费门禁

- Dispatcher **跳过**该用户新信号
- 前端 **PendingPerfFeeCard** 横幅（Dashboard / Settlements 一键缴纳）

### HD 专属充值 + 链上监控

| 组件 | 说明 |
|------|------|
| HD 助记词 | 钱包中心配置 → 每用户独立 USDT 子地址 |
| `deposit_monitor.py` | 默认每 **180s** 扫描（`DEPOSIT_SCAN_INTERVAL_SEC`） |
| 自动确认 | `SETTLEMENT_AUTO_CONFIRM=true` 时到账自动确认绩效费 |
| 管理端 | **缴纳日志** Tab：扫描健康、立即扫描、缴纳跟踪时间线 |
| RPC | 读 `chain_rpc_config.get_rpc_url()`，**管理后台配置即可**，不必写 `.env` |

### 用户 API 绑定要求

| 权限 | 要求 |
|------|------|
| 合约/Futures | **必须开启** |
| 提现 Withdraw | **必须关闭** |
| IP 白名单 | **强烈建议** VPS 出口 IP |

---

## 推广分润与下级审计

- 邀请链接：`{FRONTEND_URL}/register?ref=PANDA-XXXXXXXX`
- 结算确认后 L1/L2 奖励入账推广人钱包
- 推广者 API：`GET /api/referrals/downline/{id}/logs|account|trades`（权限校验 L1/L2）

### 提现分级（可热改）

| 金额 | 处理 |
|------|------|
| < $10（默认） | 拒绝 |
| ≤ $100 | 秒到；可自动链上打款 |
| $100 ~ $500 | 待审核 |
| ≥ $500 | 须管理员审核 |

---

## 管理后台 16 Tab 全览

访问：`admin` 角色登录 → `/admin`

| Tab | 键名 | 核心能力 |
|-----|------|----------|
| 概览 | `home` | 统计、快捷入口、生产状态 |
| 用户 | `users` | 列表筛选、详情、交易控制、强制平仓、日志明细 |
| 账户 | `accounts` | 托管账户一览、API 状态 |
| 信号 | `signals` | TV 模板、测试下发、Webhook 接收日志 |
| 执行 | `execution` | Supervisor 监控、WebSocket |
| 风控 | `risk` | 全局暂停、风险倍率、告警 |
| 分析 | `analytics` | 平台 PnL |
| 审计 | `audit` | 操作审计、Webhook 明细 |
| 财务 | `finance` | 财务概览 |
| 结算 | `settlements` | 账单统计、状态筛选、确认/驳回 |
| 缴纳日志 | `deposits` | 链上扫描健康、到账跟踪、申诉 |
| 推广 | `referrals` | L1/L2 总览 |
| 提现 | `withdrawals` | 审核、完成、拒绝 |
| 平台与钱包 | `addresses` | HD/冷/热钱包、RPC、钉钉、公共地址、归集 |
| **系统健康** | `system` | **Webhook Secret（置顶）**、平台开放交易所、启动接管审计、Webhook 测试、全域日志 |

默认管理员：`ADMIN_EMAIL` / `ADMIN_PASSWORD`（**部署必改**）

---

## 用户端页面地图

| 页面 | 路径 |
|------|------|
| 官网 | `/` |
| 注册/登录 | `/register` `/login` |
| 仪表盘 | `/dashboard`（含待缴绩效费卡片） |
| API 绑定 | `/api`（Binance/OKX/Gate/DeepCoin） |
| 交易 | `/trading` |
| 成交/日志 | `/trades` |
| 绩效结算 | `/settlements`（`?pay=1` 直达缴纳） |
| 推广 | `/referrals` |
| 提现 | `/withdraw` |
| 个人中心 | `/profile` |

---

## 安全体系

| 措施 | 实现 |
|------|------|
| Webhook secret | body `secret` == `get_webhook_secret()`（runtime 优先） |
| 幂等 | 指纹 TTL 120s |
| IP 白名单 | 可选 `WEBHOOK_ALLOWED_IPS` |
| 频率限制 | 每 IP 120/min |
| Payload | action 白名单；LONG/SHORT 必填 regime/atr/price/tv_tp1~3 |
| API Key | Fernet `ENCRYPTION_KEY` |
| JWT | 用户 API Bearer |
| 角色隔离 | admin / referrer 下级校验 |
| 生产严格 | `PRODUCTION_STRICT=1` 弱密钥拒绝启动 |
| TxHash | 防重复绑定 |

---

## API 索引

基础：`https://twinstar.pro/api` 或 `http://VPS:8000/api`

### 公开/用户

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康、`production_ready` |
| POST | `/auth/register` `/auth/login` | 认证 |
| GET | `/users/logs` | 交易日志 |
| POST | `/users/sync-exchange-logs` | 同步币安成交 |
| GET | `/settlements/payment-tracking` | 缴纳时间线 |

### 推广者

| GET | `/referrals/downline/{id}/logs` | 下级日志 |
| GET | `/referrals/downline/{id}/account` | 下级账户 |

### 管理员（节选）

| GET/PATCH | `/admin/webhook/settings` | Webhook Secret / URL |
| GET/PATCH | `/admin/chain-rpc/settings` | 链上 RPC |
| GET/PATCH | `/admin/dingtalk/settings` | 钉钉 |
| GET/PATCH | `/admin/platform/public-settings` | 开放交易所 |
| GET | `/admin/startup-audit` | VPS 接管审计 |
| GET | `/admin/deposit-monitor/status` | 扫描健康 |
| POST | `/admin/deposit/scan` | 立即扫描到账 |
| GET | `/admin/settlements/summary` | 结算统计 |
| GET | `/admin/system/trade-logs` | 全域日志 |
| GET | `/admin/wallet/overview` | 链上余额 |

### Webhook（非 /api）

| POST | `:6010/webhook` 或 `/gemini/webhook` | TV 信号 |
| GET | `:6010/health` | 进程健康 |

Swagger：`http://127.0.0.1:8000/docs`（`PRODUCTION_STRICT=1` 时关闭）

---

## 交易日志 event_type 词典

| event_type | 说明 |
|------------|------|
| `SIGNAL` | 收到 TV 信号 |
| `OPEN` | 开仓成功 |
| `SAME_DIR_TP_REFRESH` | 同向智能持仓：ATR/档位不变、价差不足，忽略重复开仓，仅更新止盈 |
| `SAME_DIR_REOPEN` | 同向刷新换仓：ATR 变 / 档位变 / 价差够大，先平后开（日志在 SIGNAL 类） |
| `CLOSE` | 全平 |
| `CLOSE_TP3` / `CLOSE_PROTECT` | 分类全平（钉钉分标签） |
| `CLOSE_PROTECT_EMPTY` | 空仓保护撤单复位 |
| `TRAIL` | 雷达推止损 |
| `RADAR_ARM` | 雷达按路径比例启动保本追踪 |
| `RADAR_REVOKE` | 误挂保本后撤销，恢复 TV硬止损 |
| `TP_ORPHAN_PURGE` | 雷达越过 TP1/TP2 后撤销过时限价 |
| `DEFENSE_HEAL` / `DEFENSE_HEAL_OK` / `DEFENSE_HEAL_FAIL` | 止盈对齐 |
| `STARTUP` / `STARTUP_FAIL` | 重启接管 |
| `ADJUST` / `MANUAL_ADJUST` | 人工异动 |
| `ADVERSE_SL_DISARM` | 防护盾撤销（雷达接管；清仓复位时不误报） |
| `FORCE_ALIGN` | 方向背离强平 |
| `POSITION_SIDE_FLIP` | 平多/平空过量导致逆势蚂蚁仓，强平对齐 TV |
| `TP_OVER_COMMIT` | 止盈挂单合计超过实盘头寸，核武重挂 |
| `LOCK_TIMEOUT` | 信号锁超时 |
| `BINANCE_FILL` | 交易所成交同步 |

---

## 环境变量速查

完整模板：[backend/.env.example](backend/.env.example)

### 生产必改（仍建议保留在 .env）

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT，≥32 随机 |
| `ENCRYPTION_KEY` | API Key 加密 |
| `ADMIN_PASSWORD` | 管理员密码 |
| `FRONTEND_URL` | `https://twinstar.pro` |
| `API_PUBLIC_URL` | `https://twinstar.pro` |
| `WEBHOOK_PUBLIC_PATH` | `/gemini/webhook`（默认） |
| `EMAIL_DEV_MODE` | 生产 `false` + SMTP |

### Webhook（可改管理后台，不必写 .env）

| 变量 | 说明 |
|------|------|
| `WEBHOOK_SECRET` | .env 回退；**无长度限制** |
| `WEBHOOK_PORT` | 6010 |
| `WEBHOOK_IDEMPOTENCY_TTL_SEC` | 120 |

### 交易

| 变量 | 默认 |
|------|------|
| `SYMBOL` | ETHUSDT |
| `LEVERAGE` / `OKX_LEVERAGE` / `GATE_LEVERAGE` / `DEEPCOIN_LEVERAGE` | **25** |
| `SIZING_MARGIN_LEVERAGE` | 5 | 保证金预算系数（与交易所杠杆解耦） |
| `VPS_RISK_PCT` | 3.0 | OPEN 基础风险% |
| `ADD_RATIO_REG1~4` | 见 `.env.example` | TV 未传 qty_ratio 时的档位默认 |
| `MAX_ADD_TIMES_REG1~4` | 见 `.env.example` | 档位最大加仓次数 |
| `SAME_DIR_IGNORE_PRICE_DIFF_PCT` | 0.20 | 同向 ATR 模块价差阈值（辅助） |
| `OKX_SYMBOL` / `GATE_SYMBOL` / `DEEPCOIN_SYMBOL` | 见 `.env.example` |

### 结算与监控

| 变量 | 默认 | 说明 |
|------|------|------|
| `PLATFORM_FEE_RATE` | 0.25 | 绩效费 |
| `SETTLEMENT_PRIMARY_DAYS` | 30 | |
| `SETTLEMENT_AUTO_CONFIRM` | true | 链上自动确认 |
| `DEPOSIT_SCAN_INTERVAL_SEC` | 180 | 到账扫描间隔 |

### RPC（可改管理后台）

`ETH_RPC_URL`、`BSC_RPC_URL`、`ARBITRUM_RPC_URL`、`POLYGON_RPC_URL`、`TRON_API_*`

---

## 本地开发

```bash
# 后端
cd backend && python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt && cp .env.example .env
uvicorn app.main:app --reload --port 8000   # Webhook 同进程 :6010

# 前端
cd frontend && npm install && npm run dev    # :5173 代理 /api

# 测试
cd backend && pytest tests/ -q
cd frontend && npm run build
```

---

## VPS 部署与更新

```bash
git clone https://github.com/vivian5285/panda-quant-platform.git
cd panda-quant-platform          # 实际路径 ~/panda-quant-platform
cp backend/.env.example backend/.env
nano backend/.env

chmod +x deploy.sh production_check.sh
bash deploy.sh
```

### 日常更新

```bash
cd ~/panda-quant-platform
git pull origin main
docker compose up -d --build backend frontend
```

修改 **仅** `platform_runtime.json`（管理后台保存）→ **无需重启**。  
修改 `backend/.env` → `docker compose up -d --force-recreate backend`

---

## HTTPS · Nginx · 多系统共存

### DNS

| 记录 | 值 |
|------|-----|
| A `@` | VPS IP（例 187.77.130.144） |
| A `www` | 同左 |

### 一键 HTTPS

```bash
sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh
```

### Nginx 路由（`deploy/nginx-twinstar-locations.conf`）

| 路径 | 转发 |
|------|------|
| `/gemini/webhook` | `127.0.0.1:6010/webhook` |
| `/binance/webhook` | `127.0.0.1:5003/webhook` |
| `/deepcoin/webhook` | `127.0.0.1:5004/webhook` |
| `/` | `127.0.0.1:6080`（前端 + `/api/` 反代） |

防火墙：仅开放 **80/443**；6010/8000/6379 **不对公网**。

---

## 运维自检与测试命令

### VPS 一键自检

```bash
cd ~/panda-quant-platform
bash production_check.sh
docker compose exec backend python scripts/check_system.py
```

> **说明：** `[11] 充值监控 RPC 就绪` 读管理后台 runtime；若 `[4]` 仍提示 `.env RPC` 误报，请 `git pull` 最新代码（已修复）。

### Webhook 测试

**VPS 内网：**
```bash
curl -s http://127.0.0.1:6010/health
curl -s -w "\nHTTP %{http_code}\n" -X POST "https://twinstar.pro/gemini/webhook" \
  -H "Content-Type: application/json" \
  -d '{"action":"LONG","secret":"你的密码","price":3500,"regime":1,"atr":12.5,"tv_tp1":3600,"tv_tp2":3700,"tv_tp3":3800}'
```

**Windows CMD：**
```cmd
curl -s -w "\nHTTP %{http_code}\n" -X POST "https://twinstar.pro/gemini/webhook" -H "Content-Type: application/json" -d "{\"action\":\"LONG\",\"secret\":\"你的密码\",\"price\":3500,\"regime\":1,\"atr\":12.5,\"tv_tp1\":3600,\"tv_tp2\":3700,\"tv_tp3\":3800}"
```

| HTTP | 含义 |
|------|------|
| 200 | 网关正常，已收信号 |
| 403 | secret 错误 |
| 400 | JSON/字段错误 |
| 502/504 | nginx 或 6010 未起 |

### 日志关键字

```bash
docker compose logs -f backend | grep -E "VPS STARTUP|账户接管|Webhook|FORCE_ALIGN"
```

### 备份

```bash
bash backend/scripts/backup_data.sh
```

---

## 故障排查手册

| 现象 | 排查 |
|------|------|
| TV 无成交 | 用户 `api_status`、绩效门禁、全局暂停、`enabled_exchanges`、Webhook 日志；查 `signal_dispatch_logs` 用户结果 |
| HTTP 200 但钉钉 `DISPATCH_PARTIAL_FAIL` | 查 `errors[].message`；常见为风控字段缺失（已修复 `risk_multiplier` 默认值） |
| 雷达激活后瞬间全平 | 已修复：STOP 挂价高于 mark 会触发；现用 `clamp_stop_market_safe`；另查有效路径%/25s 保护期是否被绕过 |
| 币安「条件委托缺失」 | 开仓硬止损应为 **TV tv_sl 条件单**；缺失查 `HARD_SL_MISSING` / 挂单失败；挂失败应已撤仓 |
| 基础单 ≠ 3 或条件委托缺失 | 应对齐：TP123 限价 + TV硬止损 Stop-Limit；少单查 `DEFENSE_HEAL` / 挂单失败 |
| 雷达过早启动 / 近入场误标 TP1 | 查 `evaluate_radar_arm_gate`、有效比例、`RADAR_REVOKE`、平仓归因顺序（`close_attribution.py`） |
| 同向重复信号仍平仓 | **设计如此**：工厂 OPEN 铁律 = 先平后开刷新仓位；勿当 bug |
| 同秒开多又秒平空仓 | 查 `webhook_seq_gate`：必须 CLOSE→OPEN；日志应有 `same-bar CLOSE→OPEN unit` / `hold OPEN for CLOSE companion` |
| 开仓后立刻被 CAP 削仓（蚂蚁残仓） | 查 OPEN grace / `position_cap_guard`；空仓 OPEN 禁止秒 trim（`7f1abdd`） |
| TP1 成交后反复挂撤同价 TP | 查 `consumed_tp_levels` / `TP_SKIP_REHANG`；禁止按缩量重挂已成交档 |
| 钉钉 TP_FILLED / TRAIL 刷屏 | 查 `dingtalk_alert_dedupe`；监控循环不得推关键动作 |
| 条件单秒挂秒撤死循环 | 查是否新旧雷达/宽止损双逻辑并存；应对齐则 `live_already_aligned` 跳过 |
| 硬止损普通限价秒平 | **禁止**把 TV硬止损挂成可立即成交的普通限价；必须 Stop-Limit 条件单 |
| 雷达太慢 / 保本晚 | 确认 markPrice WS 已绑；哨兵近激活应 ~1s，非 6–8s |
| `supervisors=0` | 无用户绑定 API 或交易所未开放 |
| Webhook 403 | secret 与后台/TV JSON 不一致 |
| 重启后 TP 叠单 | 查 `DEFENSE_HEAL`；应对齐时 `skipped:true` |
| RPC 自检误报 | 管理后台已配 RPC → 更新代码；以 `[11]` 为准 |
| `production_ready=false` | `GET /api/health` → `security_warnings`；系统 Tab 生产清单 |
| 推广者 403 | 目标非 L1/L2 |
| HTTPS 502 | `docker compose ps`、nginx `proxy_pass` 6080 |

---

## 生产就绪清单

### 信号与执行

- [ ] 管理后台配置 Webhook Secret，TV URL = `https://twinstar.pro/gemini/webhook`
- [ ] `curl` POST 带 secret 返回 200
- [ ] 用户 API：合约开、提现关
- [ ] `GET /admin/startup-audit` 接管正常

### 资金与结算

- [ ] HD 助记词 + RPC（管理后台）+ 扫描健康绿色
- [ ] 绩效缴纳链上自动确认或申诉流程通
- [ ] 钉钉收到 OPEN/CLOSE/RADAR_ARM/STARTUP

### 基础设施

- [ ] `bash production_check.sh` 通过
- [ ] `backend/data` `backend/state` 卷持久化
- [ ] HTTPS 证书有效；6379 不暴露

---

## VPS 实盘自查清单

Cursor 开发与 VPS 上线前，按 **[`docs/VPS_LIVE_CHECKLIST.md`](docs/VPS_LIVE_CHECKLIST.md)** 逐项对照：

| 模块 | 优先级 | 要点 |
|------|--------|------|
| Webhook + ETH/XAU 路由 | 🔴 P0 | `symbol` 必填；`bar_index`+`seq` 有序 |
| OPEN sizing + **13×** 名义 cap | 🔴 P0 | TV `risk_pct`/`qty_ratio`/`leverage` 公式；ETH+XAU ≤13× |
| TV硬止损 Stop-Limit | 🔴 P0 | 严格按 TV `tv_sl`；基础单×3 + 条件委托×1；禁止普通限价硬止损 |
| 路径雷达 + WS 实时 + 档位呼吸 | 🟡 P1 | R1–R4：85/80/75/70% · move_step · ATR 呼吸 · markPrice WS · 25s + 双确认 |
| 钉钉 | 🟢 P2 | 盘口结构 / 雷达触发价 / `RADAR_ARM`·`RADAR_REVOKE` / 动作去重一次推送 |

自动化验收（`backend/`）：

```bash
py -m pytest tests/test_dual_symbol.py tests/test_vps_dev_checklist.py tests/test_radar_trail.py tests/test_vps_radar_stages.py tests/test_ws_radar_tick.py tests/test_vps_hard_sl.py tests/test_adverse_radar_guard.py tests/test_close_attribution.py tests/test_trading_alerts_tp_ratio.py -q
```

---

## 技术栈与路线图

| 层 | 技术 |
|----|------|
| API | FastAPI, SQLAlchemy, Pydantic, python-binance |
| 执行 | PositionSupervisor, threading 哨兵 |
| Webhook | Flask :6010 |
| 链上 | tronpy, web3 |
| 缓存 | Redis 7 |
| 前端 | React 18, Vite, TypeScript, ECharts |
| i18n | 中/英 |
| 部署 | Docker Compose, Nginx, Certbot |

### 已完成（节选）

- [x] **统一交易工厂**：四所共享 Mixin 栈 + Route A 防线 + VPS sizing + manual adopt
- [x] 多交易所多用户执行（Binance/OKX/Gate/DeepCoin）
- [x] **杠杆优先 TV `leverage`**（config 仅缺省回退）；与 risk 公式算仓一致
- [x] **ETH + XAU 双品种**：独立 supervisor + **13×** 名义 cap + 品种路由
- [x] **TV risk 公式 sizing**：`risk_pct`/`qty_ratio`/`leverage` 权威；已删除 REGIME_MARGIN 旧逻辑
- [x] **TV硬止损 Stop-Limit**：严格按 TV 	v_sl（多空·全所）；条件委托挂单；禁止开仓价×%旧宽止损；禁止普通限价（会秒平）
- [x] **路径比例雷达 + 阶段锁利**（R1–R4：85/80/75/70% · 步进 35/30/25/20% · 呼吸 1.0/0.8/0.65/0.5 ATR）+ 紧 TP1 有效比例 / 开仓保护期 / 双轮确认 / `RADAR_REVOKE`
- [x] **markPrice WebSocket 雷达监控**（四所 `ws_price_listeners`）+ 自适应哨兵兜底
- [x] **Webhook `bar_index`+`seq` 有序门** + 24h 幂等 + 钉钉攒批/去重/重试/企微兜底
- [x] **平仓归因**：近入场雷达止损不误标 TP1
- [x] **TV 同 bar 先平后开** + 雷达进行中强制清场再开；空仓仅 OPEN 直接开仓、雷达候命
- [x] manual adopt：TV CLOSE 不误平同向人工仓；空闲巡检 10s
- [x] TV 字段解析 + 网关极速 200
- [x] 管理后台 Webhook/RPC/钉钉 可视化配置
- [x] 绩效费链上监控 + 自动确认 + 缴纳跟踪 UI
- [x] 实盘 TradeLog 全角色明细 + 钉钉按交易所主题
- [x] 分发风控：`risk_multiplier` 默认值、平仓信号暂停放行

### 规划中

- [ ] Bybit 多用户
- [ ] Regime 参数后台可配置

---

## 实盘事故 · 注意事项 · 优化指南

> **给运维 / 后续 Agent 的实盘备忘（2026-07）。**  
> 下列问题均在币安/OKX/Gate/DeepCoin 统一工厂上踩过或防过。改代码前先对照本节，改完跑对应 pytest，再 `git push` + VPS 拉新。

### 一、执行铁律（必须永远成立）

| # | 铁律 | 正确行为 | 错误行为（实盘事故） |
|---|------|----------|----------------------|
| 1 | **带开仓的 TV** | 一律先平现有仓 / 清挂单 → 再开新仓（刷新） | 有仓直接加仓或跳过清场 |
| 2 | **同秒/同 bar 平+开** | 短暂缓冲 → **先 CLOSE 再 OPEN**，最终**必有仓** | 按 `seq` 数字先开后平 → 开仓秒平空仓 |
| 3 | **单独平仓 TV** | 全平 + 撤尽 TP/雷达/硬止损 + 状态清零，干净等待下次 TV | 平完残留挂单、孤儿 TP 反向成交 |
| 4 | **三层防线分槽** | TP123 限价 ‖ TV硬止损(tv_sl) ‖ 雷达条件槽互不抢份额 | 新旧双系统抢挂 → 秒挂秒撤 |
| 5 | **钉钉** | 动作实盘核查后推送**一次**（去重） | 监控循环刷 `TP_FILLED` / `TRAIL` |
| 6 | **四所一套逻辑** | Binance / OKX / Gate / DeepCoin 同一铁律 | 某所仍走旧雷达/旧宽止损 |

**代码入口：**

- 时序门：`backend/app/services/webhook_seq_gate.py`
- 开仓侧：`_handle_tv_entry` / `_force_flat_before_open`（两 supervisor）
- 平仓侧：`handle_signal` → `_close_all` + `_purge_defense_orders_on_flat`
- 串行：`webhook_server.py` per-symbol 队列（禁止并发打乱 CLOSE/OPEN）

---

### 二、已发生 / 高危实盘事故档案

#### A. 同秒 OPEN + CLOSE → 先开后平空仓（P0 · 2026-07-19）

| 项 | 内容 |
|----|------|
| **现象** | TV 同秒发出开多 + 保护性全平；实盘先开仓再秒平，最终空仓 |
| **TV 样例** | `LONG` `entry_type=OPEN` `seq=1` + `CLOSE_PROTECT` `seq=2`，同一 `bar_index`（V1.6.10） |
| **根因** | 旧门控按 **seq 升序**释放；OPEN=1 先于 CLOSE=2。文档曾假设「平 seq 小、开 seq 大」，与 Pine 实际相反 |
| **修复** | 排序改为 **CLOSE 优先于 OPEN**（seq 仅次要键）；单独 OPEN 等待同伴 CLOSE；成对单元释放 CLOSE→OPEN |
| **验证日志** | `[WebhookSeq] hold OPEN for CLOSE companion` → `same-bar CLOSE→OPEN unit` → `release … CLOSE` 再 `… LONG` |
| **测试** | `test_seq_gate_v1610_open_seq1_close_seq2_final_open` |
| **Commit** | `c97e086` → 铁律再强化 `1156fba` |

**注意：** 以后改 seq 门控时，**禁止**再以「seq 数字大小」决定开平先后。

#### B. 硬止损挂成普通限价 → 开仓秒平（P0）

| 项 | 内容 |
|----|------|
| **现象** | 开仓后瞬间全平；币安基础单异常 |
| **根因** | 硬止损被挂成**可立即成交的普通限价**（价格已在市价一侧） |
| **修复** | 硬止损必须是 **Stop-Limit 条件单**；价格严格 = TV `tv_sl`；挂失败立即撤仓 |
| **注意** | 盘口期望：基础单×3（TP123）+ 条件委托×1（TV硬止损）；雷达启动前条件委托=1 |

#### C. TP1 成交后重挂死亡螺旋（P0）

| 项 | 内容 |
|----|------|
| **现象** | TP1 已吃单，系统按缩减后仓位反复挂/撤同价 TP1；钉钉狂刷 |
| **根因** | 把「盘口 TP 限价消失」当成漏挂；未用价到+簿口证据记账 `consumed_tp_levels` |
| **修复** | 价到 + 限价消失 → 记入 consumed，**永不重挂该档**（`TP_SKIP_REHANG`）；成交需价格/峰值证据 |
| **注意** | ETH/XAU 市价细微 qty 漂移（约 8%）不要当漏挂/人工减仓 |

#### D. 空仓 OPEN 后「蚂蚁残仓」秒 trim（P0）

| 项 | 内容 |
|----|------|
| **现象** | 空仓刚 OPEN，立刻被 CAP/对齐逻辑部分平仓，仓位被削成蚂蚁 |
| **根因** | 开仓后立刻做名义 cap / 敞口 trim，把正常新仓当成超限 |
| **修复** | OPEN grace 阻断 CAP；禁止 flat-OPEN 后即时部分平；穿市 TP 消毒 |
| **Commit** | `7f1abdd` |

#### E. 雷达 / 硬止损 / TP 抢份额 · 秒挂秒撤（P0）

| 项 | 内容 |
|----|------|
| **现象** | 条件单刚挂上又撤、再挂；盘口抖动；费率与拒单风险 |
| **根因** | 新旧雷达逻辑并存，或定期补挂误动硬止损/雷达槽；WS tick 与哨兵双路径无锁 |
| **修复** | Route A 分槽；已对齐 `live_already_aligned` / `on_book` 跳过；WS+哨兵共用锁 + 节流 |
| **注意** | **禁止**同时跑两套雷达启动或两套硬止损；VPS 只保留一套 TV tv_sl 路径 |

#### F. 钉钉刷屏（P1）

| 项 | 内容 |
|----|------|
| **现象** | `TP_FILLED`、雷达前进、对本金快照等连发；淹没真正关键告警 |
| **根因** | 监控循环推送；`consumed` 被 8% 漂移误清空后重复认定成交 |
| **修复** | `dingtalk_alert_dedupe`；关键动作实盘后一次；过程类仅 TradeLog |
| **Commit** | `4c5e3c7` |

#### G. 雷达监控过慢 / 保本晚（P1）

| 项 | 内容 |
|----|------|
| **现象** | 价格已到档位激活路径，雷达仍数秒后才挂；利润回吐 |
| **根因** | 仅靠 6–8s REST 哨兵轮询，未吃 markPrice WebSocket |
| **修复** | WS 推送驱动 `_radar_ws_fast_tick`（~0.45s）；近激活哨兵 1s / 雷达中 1.2s |
| **Commit** | `ce2d3c9` |
| **档位表** | R1 85%/35%/1.0ATR · R2 80%/30%/0.8 · R3 75%/25%/0.65 · R4 70%/20%/0.5（宁松勿紧） |

#### I. 重启接管反复补挂 TP1（P0 · 2026-07-20）

| 项 | 内容 |
|----|------|
| **现象** | 重启后仓位在 TP1 附近被反复吃掉，到不了 TP2/TP3；日志狂刷补挂 |
| **根因** | 现价已过 TP1 仍当「缺失」→ `sanitize` 推离市价再挂 → 立即成交 → 再判缺失 |
| **修复** | 现价/峰值达 TPₙ → 记入 consumed，只挂更高档 + 雷达；禁止 push-and-place |
| **接管步骤** | ①读开仓价/TV 方向 ②现价 vs TP123 ③达激活比例则雷达 ④只补真正缺失的更高档 ⑤不无故平仓 |
| 项 | 内容 |
|----|------|
| **现象** | 刚开仓噪声触发保本；或平仓归因把保本止损标成 TP1 |
| **修复** | 25s 开仓保护期 + 双轮确认 + 紧 TP1 有效比例抬高；`RADAR_REVOKE`；平仓归因优先 `exchange_stop` |
| **注意** | 雷达哲学是「适度追随」不是「紧追」；勿把 move_step 改回固定 50% 紧跟 |

---

### 三、日常运维要注意什么

1. **VPS 更新后必须重启** webhook（6010）与 backend，否则仍跑旧 seq 门 / 旧雷达。  
2. **看日志顺序**：同 bar 刷新应看到 CLOSE release → OPEN release → 开仓钉钉有仓；若先 OPEN 后 CLOSE，立即停机查版本。  
3. **币安盘口对账**：开仓后基础单=3、条件委托=1；多一张条件单先查是否降级 STOP_MARKET。  
4. **Pine 字段**：`bar_index`+`seq` 必填；`symbol` 必填（ETH/XAU）；`tv_sl` 可发但不挂单。  
5. **不要手改 state.json 的 `consumed_tp_levels` / `radar_latched`**，除非知道在修死亡螺旋。  
6. **禁止**在未跑测试时同时改 `webhook_seq_gate` + 两套 supervisor 的挂单路径。  
7. **人工同向仓**：TV **CLOSE** 仍可走 manual 保护；TV **OPEN** 一律先平后开刷新（不再 preserve 开仓）。  
8. **钉钉限流**：企业机器人 20 条/分钟；依赖攒批+去重，勿再加监控循环推送。

**常用日志 grep：**

```bash
docker compose logs -f backend | grep -E \
  "WebhookSeq|same-bar CLOSE|hold OPEN|先平后开|FLIP_CLEAN|TP_SKIP_REHANG|RADAR_ARM|live_already_aligned|FORCE_ALIGN"
```

---

### 四、如何继续优化（优先级建议）

| 优先级 | 方向 | 说明 |
|--------|------|------|
| P0 | 保持铁律单测绿灯 | `test_webhook_seq.py` + `test_vps_entry_routing.py`（OPEN 必调 `_force_flat_before_open`） |
| P0 | 部署后冒烟 | 同 bar 模拟：先发 OPEN seq=1 再发 CLOSE seq=2，确认最终有仓 |
| P1 | WS 健康 | 监控 `markPrice` 断线重连；WS 失效时哨兵 1s 兜底是否生效 |
| P1 | 拒单/精度 | 各所 tick/lot 对齐；Stop-Limit 触发价与限价间距符合交易所规则 |
| P2 | 钉钉文案 | 开仓/清场/雷达启动字段统一（盘口结构、档位激活%、剩余头寸） |
| P2 | Regime 后台可配 | 激活/步进/呼吸进管理后台，但仍单一源码表，防双配置 |
| P3 | 可观测性 | 对「同 bar CLOSE→OPEN 耗时」「force_flat 失败率」打点告警 |

**回归命令（改执行/雷达/时序后必跑）：**

```bash
cd backend
py -m pytest tests/test_webhook_seq.py tests/test_vps_entry_routing.py \
  tests/test_ws_radar_tick.py tests/test_vps_radar_stages.py \
  tests/test_radar_trail.py tests/test_adverse_radar_guard.py -q
```

---

### 五、铁律复核清单（每次大改打勾）

- [ ] 同 bar OPEN+CLOSE（任意 seq）→ 日志先 CLOSE 后 OPEN，最终有仓  
- [ ] 任意 OPEN → 调用 `_force_flat_before_open`（有仓平仓 / 无仓清挂单）  
- [ ] 单独 CLOSE → 仓位 0 + 挂单 0 + 雷达/consumed 复位  
- [ ] 雷达读 WS mark；激活/步进/呼吸只读 `REGIME_RADAR`  
- [ ] TP123 / 宽止损 / 雷达不互相撤挂；对齐则跳过  
- [ ] 钉钉关键动作去重，无监控循环刷屏  
- [ ] 四所行为一致；无旧逻辑双轨  
- [ ] README 本节与代码同步；已 push `main`

---

## 更新记录

> 按时间倒序。生产 VPS：`git pull` → `docker compose up -d --build`（或既有部署脚本）后重启 supervisor。

### 2026-07-20 · 重启接管：现价已过 TP 禁止补挂（防 TP1 死亡螺旋）

| 项 | 内容 |
|----|------|
| **事故** | VPS 重启后反复「缺失 TP1」→ 推离市价补挂 → 秒成 → 再补挂；仓位耗在 TP1 附近，走不到 TP2/TP3 |
| **铁律** | 开仓价 + 现价对账：现价/峰值已达 TP1 → **只挂 TP2/TP3** + 评估雷达激活；达 TP2 → 只挂 TP3；**禁止** sanitize 推离后挂穿市 TP |
| **实现** | `levels_past_by_mark` 写入 `consumed_tp_levels`；`_patch_missing` / `_place_all_defense` / Deepcoin 重建 **跳过 `price_past_tp`**；重启不无故平仓（仅方向背离 FORCE_ALIGN） |
| **雷达** | 接管时按档位激活比例检查是否启动；已达则锁润追踪，勿空转补挂 TP1 |
| **测试** | `tests/test_tp_past_mark_skip.py` |

---

### 2026-07-19 · 执行铁律简化：OPEN 一律先平后开 · CLOSE 单独清零等待

| 信号 | 行为 |
|------|------|
| 任意带开仓 TV（OPEN） | **一律**先平现有仓 / 清挂单 → 再开新仓（刷新）；空仓亦先清场 |
| 同 bar 平仓+开仓 | 门控先平后开 + 开仓侧仍先平后开；**最终必有仓** |
| 单独平仓 TV | 全平 + 撤尽挂单 + 状态清零，干净等待下次 TV |
| 钉钉 | 清场/开仓/平仓实盘核实后各推一次（去重） |

四所：`position_supervisor` + `position_supervisor_deepcoin` 同一套 `_handle_tv_entry` / `_force_flat_before_open`。

---

### 2026-07-19 · Webhook 同秒 OPEN+CLOSE 铁律（防开仓秒平）

**实盘事故：** V1.6.10 同 bar 发出 OPEN `seq=1` + CLOSE_PROTECT `seq=2`，旧门控按 seq 升序 → 先开后平 → 空仓。

| 项 | 修复 |
|----|------|
| 排序 | `(CLOSE优先, seq, 到达时间)` — **不再**以 seq 决定开平先后 |
| 同伴等待 | 单独 OPEN 缓冲 `WEBHOOK_SEQ_WAIT_SEC`，等可能的 CLOSE |
| 成对释放 | 同 bar 同时有 OPEN+CLOSE → 单元释放：先全平再开仓，**最终必有仓** |
| 范围 | 四所共用 `webhook_seq_gate` + per-symbol 串行 dispatch |
| 测试 | `test_seq_gate_v1610_open_seq1_close_seq2_final_open` |

---

### 2026-07-19 · `ce2d3c9` — WebSocket 驱动雷达实时监控（四所统一）

**目标：** 雷达监控必须用最快 mark 价，精密跟随 TP123 / 剩余头寸 / 档位呼吸，杜绝挂撤死循环；钉钉动作一次；TV 到达时序干净。

| 项 | 内容 |
|----|------|
| 价格源 | Binance / OKX / Gate / DeepCoin 公共 `markPrice` WS → `_set_ws_price` → `notify_price_listeners` |
| 绑定 | `ws_price_listeners.py`；supervisor `_ensure_price_ws` / `_on_ws_price_tick` / `_radar_ws_fast_tick` |
| 节流 | `RADAR_WS_TICK_MIN_SEC ≈ 0.45`；与哨兵共用锁，避免双路径抢挂 |
| 哨兵周期 | 正常 **5s** · 近激活 **1s** · 雷达中 **1.2s**（DeepCoin 与主 supervisor 对齐） |
| 计算 | 实时 qty、TP 成交记账、路径进度、按 `REGIME_RADAR` 前进挂单 |
| 共存 | TP123 限价 ‖ VPS 宽止损 ‖ 雷达条件槽；`live_already_aligned` / `on_book` 跳过重复挂撤 |
| TV | 有仓/雷达中 → **一律先平后开**（清场 + 新 TP123 + 宽止损 · 雷达候命）；空仓仅 OPEN → 直接开仓、雷达候命 |
| 钉钉 | 关键动作实盘核查后一次（既有 dedupe）；监控循环不推 |
| 测试 | `tests/test_ws_radar_tick.py` |
| 关键文件 | `ws_price_listeners.py` · `*_client.py` · `position_supervisor.py` · `position_supervisor_deepcoin.py` |

### 2026-07-19 · `89e1446` — 档位雷达重调（宁松勿紧 · 适度追随）

| 档位 | 激活 | 步进 | 呼吸 |
|------|------|------|------|
| R1 | 85% | 35% | 1.0 ATR |
| R2 | 80% | 30% | 0.8 ATR |
| R3 | 75% | 25% | 0.65 ATR |
| R4 | 70% | 20% | 0.5 ATR |

- 单一源码表 `REGIME_RADAR`（`radar_trail.py`）+ `vps_radar_stages` 按 `move_step` 前进（取消固定 50% 阶段）
- 四所共用，避免新老雷达参数并存

### 2026-07 · `7f1abdd` — 空仓 OPEN 禁「蚂蚁残仓」秒 trim

- 空仓仅 OPEN：不再开仓后立刻 CAP 部分平仓
- 穿市 TP 消毒 / OPEN grace 阻断 CAP
- TP 成交认定需价格/峰值证据，防误标

### 2026-07 · `4c5e3c7` — 钉钉监控刷屏治理

- `dingtalk_alert_dedupe`：同类关键推送冷却去重
- 修复 `consumed_tp_levels` 在 8% 漂移内被误清空导致 `TP_FILLED` 连发

### 2026-07-20 · `5e68990` / `17d39bb` — TV risk 公式 + TV 硬止损

- **仓位**：唯一公式 `权益×risk_pct/|price−tv_sl|`，再与杠杆限制、50k 硬顶取 min × `qty_ratio`；OPEN/ADD 同式；删除 REGIME_MARGIN
- **硬止损**：严格挂 TV `tv_sl`；删除开仓价×档位% 宽止损；`UPDATE_SL` 改挂；挂失败立即撤仓
- Webhook OPEN/ADD 必填 `risk_pct` / `leverage` / `tv_sl`

### 2026-07 · `6bda1dc` / `f67267a` / `4aacaaa` — 先平后开 · 份额共存 · TP 死亡螺旋

- TV 同 bar：`bar_index`+`seq` 排序；CLOSE 先于 OPEN；干净归零再开
- TP 成交优先「价到 + 簿口消失」证据；禁止成交后按缩量重挂同价 TP1（`TP_SKIP_REHANG`）
- 硬止损 / 雷达 / TP123 **分槽**，不抢 reduceOnly 份额

### 2026-07 · 更早 hardening（节选）

| Commit | 摘要 |
|--------|------|
| `73a2815` | V1.6.10 seq 门 + 实盘雷达/对账钉钉强化 |
| `ebe1ff6` | TP 成交勿标人工；硬止损与雷达 qty 互不打架 |
| `38f970e` / `b0d6729` | 路径比例启动雷达；TP 成交强制激活 |
| `9fedd66` / `a972298` / `b1714f2` | VPS 硬止损 Stop-Limit（禁普通限价秒平） |
| `3c6c2ea` | 紧 TP1 噪声护栏 + 误归因防护 |

### 铁律复核清单（每次大改后对照）

见上文 **[实盘事故 · 注意事项 · 优化指南 §五](#五铁律复核清单每次大改打勾)**。摘要：

1. **时序**：同 bar 任意 seq → CLOSE 优先于 OPEN，最终必有仓  
2. **OPEN**：一律 `_force_flat_before_open` 再开仓  
3. **CLOSE**：单独平仓则清零等待  
4. **价格 / 档位 / 份额 / 钉钉 / 四所一致** — 禁止双系统与刷屏  

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。
