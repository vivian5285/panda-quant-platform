# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

| 生产域名 | [https://twinstar.pro](https://twinstar.pro) |
|----------|---------------------------------------------|
| **TV Webhook（Gemini）** | `https://twinstar.pro/gemini/webhook` |
| 仓库 | [github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform) |
| 默认交易对 | ETH 永续（Binance `ETHUSDT` / OKX·Gate·DeepCoin 各所符号见 `.env`） |

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

# 执行铁律（PositionSupervisor）
rules:
  - 永远一手、单向持仓 One-Way
  - 同向/反向新 TV 信号：一律先平后开（cancel all → 市价全平 → 再开仓）
  - 开仓后挂限价止盈 TP1/2/3（reduceOnly）+ 雷达移动止损
  - 禁止与 TV 反向持仓：哨兵检测背离 → FORCE_ALIGN 全平
  - 人工加减仓：识别、重构防线、对齐 TV、钉钉报告
  - 未结清绩效账单 → Dispatcher 跳过该用户

# 策略对接（Pine v6.9.45 双系统）
tv_actions: [LONG, SHORT, CLOSE, CLOSE_PROTECT, CLOSE_TP3]
entry_fields: [action, secret, price, regime, atr, tv_tp1, tv_tp2, tv_tp3]
close_fields: [action, secret, regime, price, atr, side, reason, pnl_pct?]
note: TP1/TP2 策略内部记账不发 TV 警报；仅 TP3 与保护性全平各发一条

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
engine: backend/app/core/position_supervisor.py
exchange_factory: backend/app/core/exchange_factory.py
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
6. [交易执行引擎（实盘逻辑全集）](#交易执行引擎实盘逻辑全集)
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
24. [技术栈与路线图](#技术栈与路线图)

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
| **Gemini 多用户（本仓库）** | 8000 / 6010 / 6080 | `/gemini/webhook` | SaaS、结算、推广、多交易所 |
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
│  跳过：用户暂停 / 未结清绩效 / 全局暂停 / API 未激活 / 交易所未开放  │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 每用户一把锁 + FIFO 信号队列（最长等 120s）
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  PositionSupervisor    PositionSupervisor    ...
  + Binance/OKX/Gate/DeepCoin Client
  + 6s 哨兵（方向背离、人工异动、雷达推止损、TP 成交识别）
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
         钉钉（按交易所 GEMINI 主题 #币安20x / #深币20x / #OKX20x / #Gate20x，仅关键动作）
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
│   │   │   ├── position_supervisor.py      # ★ 币安执行大脑
│   │   │   ├── position_supervisor_deepcoin.py
│   │   │   ├── exchange_factory.py         # 多交易所 Client/Supervisor 工厂
│   │   │   ├── binance_client.py / okx_client.py / gate_client.py / deepcoin_client.py
│   │   │   ├── position_manager.py
│   │   │   └── symbol_precision.py         # ETH tick 0.01
│   │   ├── models/__init__.py      # User, Trade, TradeLog, Settlement, ...
│   │   ├── schemas/__init__.py     # Pydantic 出入参
│   │   └── services/
│   │       ├── dispatcher.py             # Supervisor 池 + 广播
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

## 交易执行引擎（实盘逻辑全集）

实现核心：`backend/app/core/position_supervisor.py`（币安）；DeepCoin 有平行实现。经 `exchange_factory.py` 按用户 `User.exchange` 选型。

### 铁律一览

| 规则 | 实现 |
|------|------|
| 永远一手 | 单向持仓 One-Way；不加仓叠单；开仓量按四档保证金公式计算 |
| 先平后开 | LONG/SHORT 前 `cancel_all` + 市价全平旧仓，同向/反向均如此 |
| 四档 Regime | TV 传 `regime` 1~4 → 保证金比例 + TP 分批 + 雷达激活距离 |
| TV 限价止盈 | 按 `tv_tp1/2/3` 挂 reduceOnly 限价单（tick 0.01） |
| 雷达保本 | 价格朝 TP1 推进达激活比例后，ATR×trail 推升 STOP_MARKET |
| 6s 哨兵 | 方向背离、人工加减仓、TP 成交、防线漂移 |
| 禁止逆势 | 实盘 ≠ `last_tv_side` → `FORCE_ALIGN` 全平 + 钉钉 |
| 结算门禁 | `settlement` 待支付 → `dispatcher` 跳过 |
| 交易所门禁 | 管理员「平台开放设置」未勾选 → 不加载 Supervisor |

### Regime 参数（代码内置 `regime_settings`）

**开仓数量公式（全交易所统一）：**

```
qty = (可用余额 × margin_pct × 20×杠杆) / 当前价格
```

| Regime | 保证金占可用余额 | TP 分批 | 雷达激活（至 TP1 路径比例） | Trail ATR 倍数 |
|--------|------------------|---------|---------------------------|----------------|
| 1 | 15% | 25% / 35% / 40% | 40% | 0.40 |
| 2 | 25% | 20% / 35% / 45% | 50% | 0.60 |
| 3 | 35% | 18% / 32% / 50% | 60% | 0.90 |
| 4 | 50% | 5% / 20% / 75% | 70% | 1.30 |

杠杆：**全交易所统一 20×**（`LEVERAGE` / `OKX_LEVERAGE` / `GATE_LEVERAGE` / `DEEPCOIN_LEVERAGE` 默认均为 20）。实盘 `set_leverage` 与钉钉标签一致。

实现位置：
- 币安 / OKX / Gate → `position_supervisor.py` `_open_position()`
- 深币 → `position_supervisor_deepcoin.py`（合约面值换算后取整，仍按同四档 margin）

### 三重平仓把关

1. **新 TV 方向到达** → 先平后开（换防）
2. **CLOSE_PROTECT / CLOSE_TP3 / CLOSE** → 带 `reason` 全平，撤光挂单
3. **雷达 + 限价 TP** → 行情推进过程中锁润；TP3 可由 TV 警报触发终极收网

### 人工异动处理

| 场景 | 行为 |
|------|------|
| 人工加仓 | 识别数量变化 → 重构 TP/SL → `ADJUST` 日志 + 钉钉 |
| 人工减仓 | 同左，按新数量重算防线 |
| 人工全平 | 更新仓位状态 → 与 TV 对齐检查 → 钉钉 |
| 人工开反向单 | 哨兵检测 → `FORCE_ALIGN` 强平 → 等待下次 TV |

### 止盈防线：对齐 · 补挂 · 智能 heal

| 场景 | 行为 |
|------|------|
| 已对齐 | **跳过**，不 cancel（防重启叠单） |
| 缺 TP/SL/数量比例错/重复 TP | `_aggressive_heal_defenses()`：多轮 cancel 验证 → 重挂 |
| 单笔补挂失败 | 最多 `TP_RETRY_MAX=3` 次 → `TP_RETRY_FAIL` 钉钉 |

`DEFENSE_HEAL` 日志 `detail_json` 含 `live_audit`、`before_summary`、`after_summary`、`aligned`。

### VPS 重启接管（`recover_on_startup`）

对每个 **API 已激活** 且交易所仍开放的用户：

1. `radar_context.build_radar_recovery_context()` — OPEN Trade + 最新 TradeLog + 最近成功 Webhook 交叉验证
2. 读 `state/user_{id}.json` + 交易所实盘持仓
3. 有仓 → 恢复 `best_price`、`current_sl`、`consumed_tp_levels`（不盲目重置 entry）
4. `_ensure_defenses()` — 对齐跳过，否则 heal
5. 启动哨兵 → `STARTUP` TradeLog + 钉钉（有持仓时）

审计 API：`GET /api/admin/startup-audit`；日志关键字：`VPS STARTUP`、`账户接管`。

### 信号队列与锁

- 每用户 Supervisor 内 **FIFO 队列**，锁忙时最多等待 **120s**（`SIGNAL_QUEUE_TTL`）
- 超时 → `LOCK_TIMEOUT` 日志 + 钉钉
- 空仓 `CLOSE_PROTECT` → 撤单复位 `CLOSE_PROTECT_EMPTY`

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
| `LONG` | 开多（先平后开） | ✅ |
| `SHORT` | 开空（先平后开） | ✅ |
| `CLOSE` | 换防清场全平 | 可选 |
| `CLOSE_PROTECT` | 保护性全平（带 reason、pnl_pct） | ✅ |
| `CLOSE_TP3` | TP3 终极收网全平 | ✅ |

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
  "tv_tp3": 3800
}
```

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
| Binance | `#币安20x` | 靛蓝 🔷 | GEMINI量化 · 币安合约实盘引擎 |
| DeepCoin | `#深币20x` | 翡翠绿 🟢 | GEMINI量化 · 深币 SWAP 实盘引擎 |
| OKX | `#OKX20x` | 紫罗兰 🟣 | GEMINI量化 · OKX 合约实盘引擎 |
| Gate | `#Gate20x` | 琥珀橙 🟠 | GEMINI量化 · Gate 合约实盘引擎 |

前端 API 绑定页交易所卡片使用同色主题（`exchange-picker-{exchange}`），便于与原版系统视觉区分。

**会推送：** `OPEN`、`CLOSE`、`CLOSE_TP3`、`CLOSE_PROTECT`、`STARTUP`、`STARTUP_FAIL`、`FORCE_ALIGN`、`ADJUST`、`MANUAL_ADJUST`、`DEFENSE_HEAL_FAIL`、`INSUFFICIENT_BALANCE`、`LOCK_TIMEOUT`、`TP_RETRY_FAIL`、`API_OFFLINE`、`SENTINEL_ERROR`、`severity=critical`

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
| `CLOSE` | 全平 |
| `CLOSE_TP3` / `CLOSE_PROTECT` | 分类全平（钉钉分标签） |
| `CLOSE_PROTECT_EMPTY` | 空仓保护撤单复位 |
| `TRAIL` | 雷达推止损 |
| `DEFENSE_HEAL` / `DEFENSE_HEAL_OK` / `DEFENSE_HEAL_FAIL` | 止盈对齐 |
| `STARTUP` / `STARTUP_FAIL` | 重启接管 |
| `ADJUST` / `MANUAL_ADJUST` | 人工异动 |
| `FORCE_ALIGN` | 方向背离强平 |
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
| `LEVERAGE` | 20 |
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
| TV 无成交 | 用户 `api_status`、绩效门禁、全局暂停、`enabled_exchanges`、Webhook 日志 |
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
- [ ] 钉钉收到 OPEN/CLOSE/STARTUP，不被 TRAIL 刷屏

### 基础设施

- [ ] `bash production_check.sh` 通过
- [ ] `backend/data` `backend/state` 卷持久化
- [ ] HTTPS 证书有效；6379 不暴露

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

- [x] 多交易所多用户执行（Binance/OKX/Gate/DeepCoin）
- [x] TV v6.9.45 字段解析 + 网关极速 200
- [x] 管理后台 Webhook/RPC/钉钉 可视化配置
- [x] 绩效费链上监控 + 自动确认 + 缴纳跟踪 UI
- [x] 实盘 TradeLog 全角色明细 + 钉钉按交易所主题
- [x] VPS 智能接管 + 止盈 heal + 人工异动对齐

### 规划中

- [ ] Bybit 多用户
- [ ] Regime 参数后台可配置
- [ ] 多交易对

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。
