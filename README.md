# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

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
  shared_modules: [radar_trail, tv_entry_sizing, tp_slice_guard, same_direction_policy, startup_reconcile]
  defense_route_a: TV tv_sl + TP123 + 雷达保本；Binance/OKX/Gate 合并单槽 STOP；DeepCoin 双轨并行
  leverage: 25× 全所统一（config LEVERAGE / OKX / GATE / DEEPCOIN，钉钉 #币安25x 动态读取）
  sizing: OPEN 由 VPS 公式（忽略 TV qty_ratio）；ADD = base_qty × TV qty_ratio（档位动态）

# 执行铁律（PositionSupervisor — 四所相同）
rules:
  - 永远一手、单向持仓 One-Way；工厂 OPEN 同向已有仓 → 先平后开（人工接管同向仓除外）
  - 反方向 TV 信号：一律先平后开（cancel all → 市价全平 → 再开仓）
  - PYRAMID / PROFIT_ADD：同向追加，数量 = base_qty × TV qty_ratio；**加仓后核武重挂 TP123（新价格×新总头寸）+ TV SL + 雷达**
  - 开仓后挂限价止盈 TP1/2/3（reduceOnly）+ **VPS 自主硬止损**（开仓价×档位%，TV tv_sl 仅参考）+ **6 阶段雷达移动保本（TP1 三重验证后启动）**
  - **硬止损**：`距离 = 开仓价 × 档位%`（R1~R4：2.78/3.89/5.56/8.33%）；**Stop-Limit** 缓冲执行；**忽略 TV UPDATE_SL**
  - 禁止与 TV 反向持仓：哨兵 / 重启 / 空闲巡检 → FORCE_ALIGN 全平
  - 人工/外部同向仓：manual adopt 后保留仓位，TV CLOSE 不强制全平，补挂 TP123 + **VPS 硬止损**（雷达 TP1 确认后按 6 阶段激活）
  - **人工/外部全平**：哨兵/空闲巡检检测到实盘归零 → **立即撤销 TP123 + STOP**（不等待平仓确认），防止孤儿止盈反向开仓
  - **雷达越过 TP1/TP2**：雷达止损有效上移后，若 SL ≥ TP1（多）或 SL ≤ TP1（空），主动撤销过时 TP1/TP2 限价单（`TP_ORPHAN_PURGE`）
  - **加仓合并**：PYRAMID/PROFIT_ADD → 加权均价重置雷达、硬止损取更宽（多取低/空取高）、TV 新 TP123 替换旧限价
  - **三层止损**：TV `CLOSE_STOPLOSS` = 第一指令立即全平；VPS 宽硬止损 = 限价保险；6 阶段雷达 = 动态锁利（TP1 三重验证后）
  - 未结清绩效账单 / 用户暂停 / 全局暂停 → 跳过建仓；平仓类信号在暂停时仍放行

# 策略对接（Pine v6.9.45 双系统）
tv_actions: [LONG, SHORT, CLOSE, CLOSE_PROTECT, CLOSE_TP3]
entry_fields: [action, secret, price, regime, atr, tv_tp1, tv_tp2, tv_tp3, tv_sl?, entry_type?]
close_fields: [action, secret, regime, price, atr, side, reason, pnl_pct?]
extra_actions: [UPDATE_SL]   # VPS 忽略，仅记录日志；硬止损由 开仓价×档位% 自主计算
note: TP1/TP2 策略内部记账不发 TV 警报；仅 TP3 与保护性全平各发一条
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
radar: backend/app/core/radar_trail.py
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
│  TradingView Pine v6.9.45（算价、Regime、ATR、tv_tp1/2/3、平仓 reason） │
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
  + 6s 哨兵 + 10s 空闲巡检（方向背离、人工 adopt、雷达、TP 成交）
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
│   │   │   ├── adverse_radar_guard.py      # ★ TV SL + 雷达 + Route A 合并止损
│   │   │   ├── binance_smart_defense.py    # TP123 对齐/heal（OKX/Gate 复用）
│   │   │   ├── startup_reconcile.py        # ★ 重启接管 + 空闲巡检 + 人工 adopt
│   │   │   ├── radar_trail.py              # 雷达激活/保本/STOP 安全钳制
│   │   │   ├── tv_entry_sizing.py          # ★ VPS OPEN/ADD  sizing（四所统一）
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
│   │       ├── webhook_idempotency.py    # 指纹去重 TTL
│   │       ├── chain_rpc_config.py       # 管理后台 RPC
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
| 开仓量 | VPS OPEN/ADD sizing | `tv_entry_sizing.py` | ✅ |
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
| 止损形态 | **Route A 合并单槽** — 一个 `closePosition` STOP | **双轨并行** — TV SL + 雷达条件单各一张 |
| Mixin | 含 `BinanceSmartDefenseMixin` | 不含，方法内联等价实现 |

---

### 一、实盘需求总览

| 需求 | 说明 |
|------|------|
| **极速响应 TV** | 网关校验通过后 **立即 HTTP 200**，下单在后台线程异步执行 |
| **永远一手** | 单向 One-Way；工厂 OPEN 同向已有仓 → **先平后开**（人工 adopt 同向仓除外） |
| **策略价格由 TV 指挥** | `price/regime/atr/tv_tp1~3/tv_sl` 由 Pine 下发；VPS 执行、挂单、雷达、对齐 |
| **VPS 独立 sizing** | OPEN：`margin = total_equity × REGIME_MARGIN` × 25×；忽略 TV `qty_ratio`；ADD = `base_qty × TV qty_ratio`；`tv_sl` **仅日志** |
| **逆势零容忍** | 实盘方向 ≠ `last_tv_side` → 哨兵/重启/空闲巡检 `FORCE_ALIGN` |
| **人工仓保护** | manual adopt 后：TV CLOSE 不强制全平；补挂 TP123 + TV SL + 雷达 |
| **全链路可审计** | 所有决策写 `trade_logs.detail_json`；关键动作钉钉 |
| **风控可门禁** | 暂停/绩效未缴/全局暂停 → 跳过建仓；**CLOSE\* 仍放行** |

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
       └─ UPDATE_SL → 记录日志并忽略（VPS 自主管理硬止损）
  → set_leverage(25×) → 市价开/平 → 挂 TP123 + TV SL + 雷达 → 启动哨兵
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
| 空仓 | VPS sizing 开仓 → TP123 + VPS 硬止损 + 哨兵 |
| 已有仓 · **工厂单** | **先平后开** |
| 已有仓 · **人工 adopt 同向** | 保留仓位，刷新 TP/雷达 |
| 反方向 | **先平后开** |

#### PYRAMID / PROFIT_ADD

| 规则 | 说明 |
|------|------|
| 数量 | `add_qty = base_qty × TV qty_ratio`（Pine v6.9.93 档位动态：R1=0/R2=0.3/R3=0.5/R4=0.7） |
| 次数上限 | 按档位：R1=1 / R2=2 / R3=2 / R4=3（`MAX_ADD_TIMES_REG*`） |
| 加仓后 | **核武清场重挂** TP123：按 TV 最新 `tv_tp1/2/3` 价格 + 新总头寸 × regime 比例重算分批；同步 TV 硬止损；**雷达按新 entry/TP1 距离重算并挂到新 qty**（四所相同 `_rebuild_defenses_after_tv_add`） |

#### CLOSE / CLOSE_PROTECT / CLOSE_TP3

工厂单 → 全平；manual adopt 同向 → 可跳过 CLOSE，刷新防线。空仓 `CLOSE_PROTECT` → 撤单复位。

#### UPDATE_SL

**VPS 忽略** — 硬止损由 **开仓价 × 档位%** 自主计算；雷达本地管理。仅写 `UPDATE_SL` 日志。

#### VPS 硬止损（四档 · 占开仓价百分比）

```
硬止损距离 = 开仓价 × regime_pct
Regime  pct      示例（ETH@1800 多）
  1     2.78%    ≈ 1700
  2     3.89%    ≈ 1730
  3     5.56%    ≈ 1700
  4     8.33%    ≈ 1650
```

TV `tv_sl`（ATR 紧止损）**仅记录日志**，实盘挂单用上表。  
执行：**Stop-Limit** 缓冲单（触发价=止损价；限价=触发价 ±0.15%）。  
优先级：`CLOSE_STOPLOSS` 立即市价全平 > VPS 缓冲止损触发 > 忽略 `UPDATE_SL`。

---

### 四、统一开仓 Sizing（VPS · 四所相同 · ETH+XAU）

实现：`tv_entry_sizing.py` · 品种精度：`symbol_registry.py`

```
margin_usd      = total_equity × REGIME_MARGIN_{1~4}   # R1 6% / R2 12% / R3 18% / R4 22%
notional_usd    = margin_usd × exchange_leverage（25×）
qty             = notional_usd / price   （DeepCoin 换算为合约张）
双品种硬顶       = (ETH名义 + XAU名义) ≤ total_equity × 11
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `LEVERAGE` / `OKX_*` / `GATE_*` / `DEEPCOIN_*` | **25** | 实盘杠杆 + 钉钉 `#币安25x` |
| `REGIME_MARGIN_1~4` | 6/12/18/22% | OPEN 保证金占 **总本金** 比例（短周期权重） |
| `MAX_COMBINED_NOTIONAL_MULT` | **11.0** | ETH+XAU 合计名义上限 |
| `TRADING_SYMBOLS` | ETHUSDT,XAUUSDT | 启用品种 |
| `ADD_RATIO_REG1~4` | 0 / 0.3 / 0.5 / 0.7 | TV 未传 qty_ratio 时的档位默认 |
| `MAX_ADD_TIMES_REG1~4` | 1 / 2 / 2 / 3 | 各档位最大加仓次数 |

`tv_sl` **不参与**张数计算，**不参与**硬止损挂单（仅日志参考）。

---

### 五、统一防线 · Route A

```
① VPS 硬止损          开仓价×档位% 四档呼吸空间，Stop-Limit 缓冲执行（忽略 TV tv_sl）
② 雷达保本 (radar)    TP1 三重验证后激活，6 阶段 ATR 追踪（Stage 0~5）
③ TP123               regime 比例 reduceOnly 限价
```

- **TP1 三重验证**（`tp_slice_guard.confirm_tp_tier_fill`）：价格达到 + TP 限价消失 + 数量减仓匹配；防止 R4 小切片误判
- **合并止损（Binance/OKX/Gate）：** LONG `max(vps_sl, radar)` / SHORT `min(...)`，Stop-Limit 优先
- **DeepCoin 双轨：** TV SL 与雷达条件单并行
- **STOP 安全钳制：** `clamp_stop_market_safe()` 防止 SL 高于 mark 瞬间全平

> 完整自查清单：**[`docs/VPS_LIVE_CHECKLIST.md`](docs/VPS_LIVE_CHECKLIST.md)**

---

### 六、Regime 参数（`tp_regime_ratios.py` · Pine v6.9.94 `qty_percent`）

与 `gemini止损_动态加仓.txt` 中 `strategy.exit("止盈1/2/3", qty_percent=tp1_p/2_p/3_p)` **逐档对齐**；四所共用 `build_regime_settings()` 单一数据源。

| Regime | 保证金 cap% | TP 分批 (%) | 雷达激活路径 | Trail ATR× |
|--------|-------------|-------------|--------------|------------|
| 1 | 15% | **25/35/40** | 85% | 0.75 |
| 2 | 25% | 20/35/45 | 88% | 1.00 |
| 3 | 35% | 18/32/50 | 90% | 1.35 |
| 4 | 50% | 5/20/75 | 95% | 1.80 |

钉钉开仓/加仓/重启明细会显示 `止盈比例 TP1/2/3 = xx/xx/xx%`。

---

### 七、重启接管 + 空闲巡检

**重启：** DB/Webhook/state 交叉验证 → `loss_shield` / `profit_radar` 分轨 → TP123 + TV SL + 雷达补挂 → 哨兵

**空闲巡检（10s，`monitoring=False`）：** 账本/实盘偏差收口 · 反向 FORCE_ALIGN · 同向 manual adopt · dust 扫尾

---

### 八、哨兵（~6s 自适应）

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
| `UPDATE_SL` | TV 紧止损参考（VPS **忽略**，仅日志） | 可选 |

### 开仓 JSON（v6.9.45）

```json
{
  "action": "LONG",
  "secret": "你的密码",
  "price": 3500,
  "regime": 1,
  "atr": 12.5,
  "tv_tp1": 3600,
  "tv_tp2": 3700,
  "tv_tp3": 3800,
  "tv_sl": 3400
}
```

> `tv_sl` 为 TV 硬止损价，VPS 挂 STOP 使用，**不参与 OPEN sizing**。`entry_type` 可选 `OPEN` / `PYRAMID` / `PROFIT_ADD`。

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

> **Pine 常见坑：** `CLOSE_PROTECT` JSON 里 `side`、`reason` **必须闭合引号**，否则 TV 报 400。Gemini 网关对 v6.9.30 类缺引号格式有兼容修复（`webhook_payload.py`）。

### 网关时序

| 阶段 | 行为 |
|------|------|
| 同步 | 校验 → **立即 HTTP 200**（通常 <50ms） |
| 异步 | `webhook-dispatch-*` 线程池广播（默认 20 并发） |
| 幂等 | 相同指纹在 `WEBHOOK_IDEMPOTENCY_TTL_SEC`（默认 120s）内 → `{ "status": "duplicate" }` |

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

### 用户实盘钉钉（`trading_alerts.py`）

按用户绑定交易所选 **GEMINI量化** 独立主题（与原版黑金币安单机系统 UI 区分）：

| 交易所 | 标签 | 主题色 | 品牌 |
|--------|------|--------|------|
| Binance | `#币安25x`（读 `LEVERAGE`） | 靛蓝 🔷 | GEMINI量化 · 币安合约实盘引擎 |
| DeepCoin | `#深币25x` | 翡翠绿 🟢 | GEMINI量化 · 深币 SWAP 实盘引擎 |
| OKX | `#OKX25x` | 紫罗兰 🟣 | GEMINI量化 · OKX 合约实盘引擎 |
| Gate | `#Gate25x` | 琥珀橙 🟠 | GEMINI量化 · Gate 合约实盘引擎 |

前端 API 绑定页交易所卡片使用同色主题（`exchange-picker-{exchange}`），便于与原版系统视觉区分。

**会推送：** `OPEN`、`CLOSE`、`CLOSE_TP3`、`CLOSE_PROTECT`、`SAME_DIR_TP_REFRESH`（同向智能持仓）、`SAME_DIR_REOPEN`（同向刷新换仓）、`STARTUP`、`STARTUP_FAIL`、`FORCE_ALIGN`、`POSITION_SIDE_FLIP`、`TP_OVER_COMMIT`、`ADJUST`、`MANUAL_ADJUST`、`DEFENSE_HEAL_FAIL`、`INSUFFICIENT_BALANCE`、`LOCK_TIMEOUT`、`TP_RETRY_FAIL`、`API_OFFLINE`、`SENTINEL_ERROR`、`severity=critical`

**同向智能筛选钉钉示例：**

| 类型 | 典型文案 |
|------|----------|
| `SAME_DIR_TP_REFRESH` | `ATR未变(12.5) 价差 0.14% < 0.20% → 忽略重复开仓，更新止盈 [3600,3700,3800] → [3610,3710,3810]` |
| `SAME_DIR_REOPEN` | `同方向ATR变化 12.5→18.0，刷新仓位先平后开` 或 `同方向档位变化 2→4，先平后开换仓` |

日志 `detail_json` 关键字段：`held_atr`、`new_atr`、`atr_changed`、`price_diff_pct`、`threshold_pct`、`decision`、`old_tv_tps`、`new_tv_tps`。

**不推送（仅 TradeLog）：** `TRAIL`、`DEFENSE_HEAL`、`DEFENSE_HEAL_OK`、`SIGNAL`、`TP_RETRY` 等过程类

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
| 雷达激活后瞬间全平 | 已修复：STOP 挂价高于 mark 会触发；现用 `clamp_stop_market_safe` |
| 同向重复信号仍平仓 | 工厂单 OPEN 设计为 **先平后开**；manual adopt 同向仓会 preserve |
| 同向信号应忽略但仍开仓 | 确认是否为工厂单；manual adopt 走不同分支 |
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
| Webhook + ETH/XAU 路由 | 🔴 P0 | `symbol` 必填，绝不串单 |
| OPEN sizing + 11× 名义 cap | 🔴 P0 | 总本金 × 档位% × 25× |
| VPS 硬止损 | 🔴 P0 | 忽略 TV `tv_sl` |
| TP1 三重验证 + 雷达 | 🟡 P1 | 价格主判 + 订单辅判 + 仓位参考 |
| 钉钉 | 🟢 P2 | 开/平/雷达/风控拦截 |

自动化验收（`backend/`）：

```bash
py -m pytest tests/test_dual_symbol.py tests/test_vps_dev_checklist.py tests/test_tp_slice_guard.py tests/test_vps_hard_sl.py -q
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
- [x] **25× 杠杆**全所统一；保证金预算与交易所杠杆解耦
- [x] **ETH + XAU 双品种**：独立 supervisor + 11× 名义 cap + 品种路由
- [x] **VPS 硬止损**：开仓价×档位%（非 TV ATR 紧止损）
- [x] **TP1 三重验证 + 6 阶段雷达**（TP1 成交后启动）
- [x] manual adopt：TV CLOSE 不误平同向人工仓；空闲巡检 10s
- [x] TV v6.9.45 字段解析 + 网关极速 200
- [x] 管理后台 Webhook/RPC/钉钉 可视化配置
- [x] 绩效费链上监控 + 自动确认 + 缴纳跟踪 UI
- [x] 实盘 TradeLog 全角色明细 + 钉钉按交易所主题
- [x] 分发风控：`risk_multiplier` 默认值、平仓信号暂停放行

### 规划中

- [ ] Bybit 多用户
- [ ] Regime 参数后台可配置

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。
