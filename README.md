# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20USDT--M%20Only-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为成熟的 **TradingView 信号 → 平台广播 → 币安 U 本位合约独立执行** 架构。

> **当前阶段（Gemini 多用户）仅支持币安（Binance）U 本位永续合约，默认 `ETHUSDT` × `15×` 杠杆。**  
> OKX / Bybit / Deepcoin 等需单独适配，列为二期。  
> 同机可共存 **单账户币安大脑（:5003）** 与 **Deepcoin（:5004）** 等 legacy 服务，端口与 Gemini 互不冲突。

**生产域名示例：** [https://twinstar.pro](https://twinstar.pro)  
**Gemini Webhook：** `https://twinstar.pro/gemini/webhook`

---

## 目录

- [产品定位](#产品定位)
- [商业模式](#商业模式)
- [角色与数据权限](#角色与数据权限)
- [系统架构](#系统架构)
- [项目结构](#项目结构)
- [交易执行引擎](#交易执行引擎)
- [实盘核实交易日志](#实盘核实交易日志)
- [通知策略：钉钉 vs 平台日志](#通知策略钉钉-vs-平台日志)
- [绩效结算与交易门禁](#绩效结算与交易门禁)
- [推广分润与下级审计](#推广分润与下级审计)
- [管理后台能力](#管理后台能力)
- [用户端功能](#用户端功能)
- [安全体系](#安全体系)
- [API 参考（精选）](#api-参考精选)
- [交易日志事件类型](#交易日志事件类型)
- [环境变量说明](#环境变量说明)
- [本地开发](#本地开发)
- [VPS 部署](#vps-部署)
- [HTTPS 与 twinstar.pro](#https-与-twinstarpro)
- [TradingView Webhook](#tradingview-webhook)
- [运维与自检](#运维与自检)
- [故障排查](#故障排查)
- [生产就绪清单](#生产就绪清单)
- [技术栈](#技术栈)
- [路线图](#路线图)

---

## 产品定位

| 维度 | 说明 |
|------|------|
| **对外叙事** | AI 量化决策引擎：用户绑定交易所 API，由 AI 策略托管交易 |
| **对内实现** | TradingView 策略发信号 → VPS 统一接收 → 多用户并发下单 |
| **资金隔离** | 每位用户独立币安 API Key，资金与仓位互不影响 |
| **收费模型** | 周期净盈利 × 25% 作为 **AI 绩效服务费**；推广人从服务费池分润 |
| **结算周期** | 优先 7 天；无盈利或仍有持仓延至 10 天；须全平仓后结算 |
| **审计原则** | 所有交易动作 **实盘核实后写入 TradeLog**；用户/管理员/推广者在线查看明细；钉钉仅抄送关键动作 |

### Gemini 与 Legacy 单账户系统

| 系统 | 端口 | 用途 |
|------|------|------|
| **Gemini 多用户（本项目）** | 8000 / 6010 / 6080 | 多用户 SaaS、绩效结算、推广、日志审计 |
| 币安单账户大脑 | 5003 | 独立 VPS 服务，`/binance/webhook` |
| Deepcoin 单账户 | 5004 | 独立 VPS 服务，`/deepcoin/webhook` |

Gemini **只读取用户绑定的币安 API**，不接入 Deepcoin 多用户托管。

---

## 商业模式

### 费用与分润

| 项目 | 默认比例 | 说明 |
|------|----------|------|
| AI 绩效服务费 | 25% | 自用户周期 **净盈利** 计提（`.env` → `PLATFORM_FEE_RATE`） |
| 一级推广奖励 | 10% | 从平台服务费池分给直接邀请人（`REFERRAL_L1_RATE`） |
| 二级推广奖励 | 5% | 分给邀请人的邀请人（`REFERRAL_L2_RATE`） |

### 完整资金闭环

```
TradingView 信号 → 用户币安账户交易 → 周期结束且全平仓
    → 系统生成绩效结算账单（25% 服务费）
    → 用户向 **专属 HD 充值子地址** 转 USDT（或手动提交 TxHash / 申诉）
    → 链上监控自动匹配结算 · 管理员确认收款
    → （可选）子地址 USDT 自动归集至冷钱包
    → 初始本金重置 + L1/L2 推广奖励入账
    → 推广人可提现（热钱包链上打款）或平台内 UID/邮箱/手机转账
```

### 结算门禁（未缴费则暂停交易）

存在 **待支付 / 待确认** 的绩效账单时，系统将：

- 暂停该用户的新信号执行（Dispatcher 跳过）
- 前端展示 **绩效结算横幅**（Dashboard / 交易 / 风控 / 结算页）
- 管理员确认收款后恢复交易，并重置初始本金快照

---

## 角色与数据权限

| 角色 | 交易日志 | 账户信息 | 说明 |
|------|----------|----------|------|
| **普通用户** | 仅本人，`GET /api/users/logs` | 本人 Dashboard / Profile | 成交页可展开 **实盘核实明细** |
| **管理员** | 全站任意用户 + 系统 Tab 全域日志 | 用户详情全字段 | `/admin` → 用户详情 / 系统 → 全域交易日志 |
| **推广者（L1/L2）** | 仅直接/间接下级 | 下级权益、持仓、结算状态 | 推广中心 → **查看日志** 弹窗 |

推广者 **不能** 查看非下级用户数据；越权访问返回 `403`。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        TradingView 策略                          │
│         （算价、Regime、TP 档位、CLOSE_PROTECT reason）           │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /gemini/webhook (6010)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Webhook 网关 · SignalDispatcher（ThreadPool 多用户并发广播）     │
│  校验 secret / IP / 频率 · 幂等去重 · 跳过：暂停/未结算/全局暂停   │
└────────────────────────────┬────────────────────────────────────┘
                             │ 每用户独立实例
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  PositionSupervisor   PositionSupervisor   ...
  + BinanceClient      + BinanceClient
  + 6s 哨兵             + state/user_{id}.json
         │                   │
         ▼                   ▼
    用户 A 币安 API      用户 B 币安 API
         │                   │
         └─────────┬─────────┘
                   ▼
         TradeLog（实盘核实 detail_json）
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
  用户端日志    管理端日志    推广者下级日志
  （详细）      （详细）      （详细）
                   │
                   ▼
         钉钉（仅关键动作摘要 → 管理员）
```

| 层级 | 职责 |
|------|------|
| **TradingView** | 策略逻辑、regime、atr、tv_tp1/2/3、CLOSE_PROTECT reason |
| **VPS 平台** | 接收警报、校验、并发分发、仓位管理、止盈网格、雷达锁润、智能止盈对齐修复、先平后开、单向持仓、结算门禁 |
| **用户币安账户** | 各自 API Key 独立下单，密钥 Fernet 加密存储 |
| **Redis** | 运行时配置缓存、全局交易暂停标记、Webhook 幂等（限流为进程内内存） |
| **SQLite / MySQL** | 用户、交易、TradeLog、结算、推广、审计等业务数据 |

### Docker 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `frontend` | **6080** → 80 | React 静态站 + Nginx 反代 `/api/` |
| `backend` | **8000** | FastAPI REST API |
| `backend` | **6010** | TradingView Webhook（Flask 线程） |
| `redis` | 6379 | 缓存（**勿对公网开放**） |

持久化卷（部署必挂载）：

| 路径 | 内容 |
|------|------|
| `backend/data/` | SQLite、platform_runtime.json、幂等键 |
| `backend/state/` | `user_{id}.json` 雷达/止盈/Regime 状态 |
| `backend/logs/` | 应用日志 |
| `backend/.env` | 环境变量（Docker 只读挂载至 `/app/.env`） |

---

## 项目结构

```
panda-quant-platform/
├── backend/
│   ├── app/
│   │   ├── api/                    # REST 路由
│   │   │   ├── auth.py             # 注册/登录/JWT
│   │   │   ├── users.py            # 用户资料、成交、日志
│   │   │   ├── admin.py            # 管理员用户/结算/控制
│   │   │   ├── referrals.py        # 推广 + 下级日志/账户 API
│   │   │   ├── wallet.py           # 充值/提现/转账
│   │   │   └── system.py           # 管理端系统 Tab（全域日志等）
│   │   ├── core/
│   │   │   ├── binance_client.py   # 币安 REST + 精度格式化
│   │   │   ├── position_manager.py # 持仓查询封装
│   │   │   ├── position_supervisor.py  # ★ 核心执行引擎
│   │   │   └── symbol_precision.py # ETHUSDT tick 0.01
│   │   ├── models/                 # SQLAlchemy 模型
│   │   ├── schemas/                # Pydantic（含 TradeLogOut.detail）
│   │   └── services/
│   │       ├── dispatcher.py       # Supervisor 池 + 信号广播
│   │       ├── radar_context.py    # 重启接管：OPEN 日志 + 最新 TV 交叉验证
│   │       ├── trade_logger.py     # TradeLog 写入 + live_verified 元数据
│   │       ├── trading_alerts.py   # 钉钉关键动作过滤
│   │       ├── alert_service.py    # notify_admin / notify_system
│   │       ├── settlement.py       # 绩效结算
│   │       ├── webhook_idempotency.py
│   │       ├── binance_sync.py     # 币安成交同步 → BINANCE_FILL 日志
│   │       └── …
│   ├── tests/                      # pytest（supervisor / radar / logs）
│   ├── scripts/check_system.py     # 生产自检
│   ├── scripts/backup_data.sh
│   └── .env.example
├── frontend/
│   └── src/
│       ├── pages/                  # 用户页 + Landing + Admin
│       ├── pages/admin/tabs/       # 14 个懒加载管理 Tab
│       ├── components/
│       │   ├── TradeLogDetailPanel.tsx   # 实盘核实明细展示
│       │   └── DownlineLogsModal.tsx     # 推广者下级日志弹窗
│       ├── api/index.ts
│       └── i18n/                   # 中/英
├── deploy/                         # Nginx、HTTPS、UFW 脚本
├── docker-compose.yml
├── deploy.sh
└── production_check.sh
```

---

## 交易执行引擎

`PositionSupervisor` 是多用户版成熟币安执行大脑，与单账户 `position_supervisor_binance.py` 行为对齐并增强。

### 核心机制

| 机制 | 行为 |
|------|------|
| **永远一手** | 单向持仓（One-Way），禁止双向对冲 |
| **先平后开** | 任何 LONG/SHORT 前先全平旧仓 + cancel all |
| **四档自适应** | Regime 1~4 → 保证金 15/25/35/50% + TP 分批比例 + 雷达系数 |
| **TV 限价止盈** | 按 tv_tp1/2/3 挂 reduceOnly 限价单（精度 tick 0.01） |
| **雷达移动止损** | Regime 激活比例（40%/50%/60%/70%）+ ATR×trail 推升 STOP_MARKET |
| **6s 哨兵** | 每 6 秒巡检：方向背离强制全平、人工加减仓重构防线、TP 成交识别 |
| **禁止逆势** | 实盘方向 ≠ TV 方向 → 立即全平 + `FORCE_ALIGN` 关键告警 |
| **状态持久化** | `state/user_{id}.json` 保存 tv_tps、SL、regime、consumed_tp_levels |
| **结算门禁** | 有未结清绩效账单 → Dispatcher 跳过该用户 |

### Regime 参数表（代码内置）

| Regime | 保证金 | TP 分批比例 | 雷达激活（至 TP1 距离） | Trail ATR 倍数 |
|--------|--------|-------------|-------------------------|----------------|
| 1 | 15% | 25% / 35% / 40% | 40% | 0.40 |
| 2 | 25% | 20% / 35% / 45% | 50% | 0.60 |
| 3 | 35% | 18% / 32% / 50% | 60% | 0.90 |
| 4 | 50% | 5% / 20% / 75% | 70% | 1.30 |

环境变量 `SYMBOL=ETHUSDT`、`LEVERAGE=15` 见 `.env.example`。

### 止盈防线：扫描 · 补挂 · 智能撤销重挂

| 场景 | 行为 |
|------|------|
| 防线 **已对齐** | 跳过，**不 cancel、不重复挂单**（避免重启叠单） |
| 缺 TP / 缺 SL / 数量比例错 / 重复 TP | `_aggressive_heal_defenses()`：验证 cancel（5 轮）→ 全量重挂 TP1/2/3 + SL |
| 单笔补挂 | `_place_missing_defenses()`，最多重试 3 次（`TP_RETRY_MAX`） |
| 实盘扫描 | `_scan_open_defenses()` 检测 duplicate / missing / qty_mismatch / orphan |

修复过程写入 `DEFENSE_HEAL` 日志，`detail_json` 含 `live_audit`、`before_summary`、`after_summary`、`aligned` 等字段。

### VPS 自启 · 智能账户接管

容器启动时 `UserSupervisorPool.load_active_users()` 对每个 **API 已激活** 用户：

1. **`radar_context.build_radar_recovery_context()`** — 合并：
   - 数据库 OPEN 状态 Trade
   - 最新 OPEN 类型 TradeLog
   - 平台最近一次成功 TV Webhook
2. **`recover_on_startup()`** — 读取 `state/user_{id}.json` + 币安实盘持仓
3. **有持仓** → 恢复 `best_price`、`current_sl`、`consumed_tp_levels`（**不**盲目重置为 entry）
4. **`_ensure_defenses()`** — 对齐则跳过；不对齐则 heal
5. 启动 6s 哨兵线程
6. 写入 `STARTUP` TradeLog + 管理员钉钉（有持仓时）

```bash
# 查看接管汇总
docker compose logs backend | grep "VPS STARTUP"
docker compose logs backend | grep "账户接管"

# API 审计
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
# 管理员 JWT → GET /api/admin/startup-audit
```

### 信号处理流程（LONG/SHORT）

```
Webhook LONG/SHORT
  → 获取用户锁（10s 超时 → LOCK_TIMEOUT 日志）
  → cancel all + 市价全平旧仓
  → 按 Regime 保证金计算数量 → 市价开仓
  → 写 Trade 行 + OPEN 日志（含滑点、tv_tps、regime）
  → _place_all_defense_orders（TP1/2/3 + SL）
  → 启动哨兵
```

---

## 实盘核实交易日志

### 设计原则

1. **一切用户可见的交易动作均入库** `trade_logs` 表  
2. Supervisor 写日志时自动附加核实元数据（`trade_logger.enrich_detail`）  
3. 前端统一用 `TradeLogDetailPanel` 展示：核实 badge、关键字段、完整 JSON  
4. **钉钉不替代日志** — 管理员看摘要，用户/推广者看全量明细  

### detail_json 标准字段

| 字段 | 说明 |
|------|------|
| `live_verified` | `true` 表示来自 Supervisor 实盘核实（非纯信号文本） |
| `verified_at` | ISO8601 核实时间（UTC） |
| `source` | `platform_supervisor` 或 `binance_exchange_sync` |
| `side` / `qty` / `entry` | 持仓方向与数量 |
| `live_audit` | 止盈扫描结果（aligned、duplicate_tps、missing_tps 等） |
| `aligned` / `healed` / `skipped` | 防线对齐状态 |
| `before_summary` / `after_summary` | 修复前后摘要文本 |
| `pnl` / `funding_fee` / `exit_price` | 平仓相关 |

### 查看入口（前端）

| 页面 | 路径 | 能力 |
|------|------|------|
| 用户 · 交易日志 | `/trades?tab=logs` | 点击行展开明细；可同步币安 ETHUSDT 成交 |
| 管理 · 用户详情 | `/admin` → 用户 → 日志 | 每条日志内嵌明细面板 |
| 管理 · 系统 | `/admin` → 系统 → **全域交易日志** | 全站日志 + 展开明细 |
| 推广 · 下级 | `/referrals` → 查看日志 | 弹窗：账户汇总 + 下级日志列表 |

### 后端 API

| 端点 | 角色 | 说明 |
|------|------|------|
| `GET /api/users/logs` | 用户 | 本人日志，`TradeLogOut` 含 `detail` |
| `GET /api/admin/users/{id}/logs` | 管理员 | 指定用户日志 |
| `GET /api/admin/system/trade-logs` | 管理员 | 全站日志（可按 user_id 过滤） |
| `GET /api/referrals/downline/{id}/logs` | 推广者 | L1/L2 下级日志 |
| `GET /api/referrals/downline/{id}/account` | 推广者 | 下级账户实盘汇总 |
| `GET /api/referrals/downline/{id}/trades` | 推广者 | 下级成交记录 |
| `POST /api/users/sync-exchange-logs` | 用户 | 拉取币安成交 → `BINANCE_FILL` 日志 |

查询参数：`limit`、`offset`、`start`、`end`（日期 `YYYY-MM-DD`）。

---

## 通知策略：钉钉 vs 平台日志

### 管理员钉钉（关键动作抄送）

配置 `DINGTALK_WEBHOOK` + `DINGTALK_SECRET`。  
实现见 `trading_alerts.py` → `should_push_trading_dingtalk()`。

**会推送：**

| 类型 | 含义 |
|------|------|
| `OPEN` / `CLOSE` | 开平仓完成 |
| `STARTUP` / `STARTUP_FAIL` | VPS 接管成功/失败 |
| `DEFENSE_HEAL_FAIL` | 止盈撤销重挂后仍不对齐 |
| `FORCE_ALIGN` | 方向背离强制全平 |
| `ADJUST` / `MANUAL_ADJUST` | 人工加减仓 |
| `INSUFFICIENT_BALANCE` / `LOCK_TIMEOUT` | 无法开仓 / 锁超时 |
| `TP_RETRY_FAIL` / `SL_RETRY_FAIL` | 补挂失败 |
| `API_OFFLINE` / `SENTINEL_ERROR` | API 不可用 / 哨兵异常 |
| 任意 `severity=critical` | 兜底 |

**不推送（仅写 TradeLog）：**

`TRAIL`、`DEFENSE_HEAL`、`DEFENSE_HEAL_OK`、`DEFENSE_AUDIT`、`TP_RETRY`、`SIGNAL` 等过程类事件。

### 平台级钉钉（`notify_system`）

| 类型 | 场景 |
|------|------|
| `SYSTEM_RESTART` | deploy.sh 部署完成 |
| `SYSTEM_INIT_FAIL` | 初始化失败 |
| `DISPATCH_*` | 信号分发异常 |
| `SETTLEMENT_APPEAL` | 缴纳申诉 |

### 用户通知

- 交易过程：**不推钉钉/短信**，请用户查看 **交易日志**  
- 提现到账、结算状态等：站内通知 / 邮件（按配置）

---

## 绩效结算与交易门禁

### 结算周期逻辑

1. 用户绑定 API 或上次确认结算后，开始 **7 天周期**（`SETTLEMENT_PRIMARY_DAYS`）
2. 到期扫描：若 **无净盈利** 或 **仍有持仓** → 延长至 **10 天**（`SETTLEMENT_EXTENDED_DAYS`）
3. 满足条件且全平仓 → 生成结算单，状态 `pending`
4. 用户向专属地址转账或提交 TxHash → `submitted`（须管理员确认，**不可**自助激活）
5. 链上监控匹配或 **缴纳申诉** → 管理员审核
6. 管理员确认 → `paid`/`confirmed`：本金重置、推广奖励入账、恢复交易

### 专属充值地址（HD）与公共备用

| 模式 | 说明 |
|------|------|
| **HD 专属地址（推荐）** | 管理后台 **钱包中心 → HD 充值** 配置 BIP39 助记词；每用户独立 USDT 地址 |
| **公共备用地址** | HD 未配置时在结算页展示 |
| **手动 / 申诉** | 监控失败时提交 TxHash 或 **缴纳申诉** |

### 子地址 USDT 归集（冷钱包）

```env
DEPOSIT_SWEEP_AUTO_ENABLED=false
DEPOSIT_SWEEP_MIN_USDT=1
DEPOSIT_SWEEP_INTERVAL_SEC=3600
```

归集成功/失败可推送钉钉（平台级）。

### 用户 API 绑定要求

| 权限 | 要求 |
|------|------|
| 合约交易（Futures） | **必须开启** |
| 提现（Withdraw） | **必须关闭** |
| IP 白名单 | **强烈建议**绑定 VPS 出口 IP |

---

## 推广分润与下级审计

### 推广关系

- 注册链接：`{FRONTEND_URL}/register?ref=PANDA-XXXXXXXX`
- 管理员确认结算后，L1/L2 奖励自动记入推广人 **奖励账户**

### 推广中心数据（`/referrals`）

| 列 | 数据来源 |
|----|----------|
| 初始本金 / 权益 / 周期盈亏 | `referral_stats.build_downline_stats()` 实盘拉取 |
| 持仓 / 结算状态 | Supervisor 或 DB 交叉验证 |
| 我的奖励 | `ReferralReward` 汇总 |

### 下级日志审计（推广者专属）

推广者在 L1/L2 表格点击 **「查看日志」**：

1. 调用 `GET /referrals/downline/{user_id}/account` 展示账户快照  
2. 调用 `GET /referrals/downline/{user_id}/logs` 加载详细 TradeLog  
3. 每条日志可展开 `TradeLogDetailPanel`（与用户端一致）

权限校验：目标用户必须是当前推广者的 **一级或二级** 下级，否则 `403`。

### 提现分级（门槛可后台热改）

| 金额区间 | 处理 |
|----------|------|
| < 最低额（默认 $10） | 拒绝 |
| ≤ 秒到额度（默认 $100） | 免审核；可 **自动链上打款** |
| 介于两者之间 | 待管理员审核 |
| ≥ 审核门槛（默认 $500） | 须管理员审核 |

秒到自动打款配置见 `.env.example` 中 `PAYOUT_*` 与 RPC 变量。

---

## 管理后台能力

访问：登录 **admin 角色** → `/admin`

| Tab | 功能 |
|-----|------|
| **概览** | 用户数、待结算、待提现、在线、生产自检 |
| **用户** | 列表筛选、详情（交易/**日志明细**/推广/本金）、交易控制、币安成交同步 |
| **信号** | TV 模板、测试下发、Webhook 接收日志 |
| **执行** | WebSocket 监控、Supervisor 状态 |
| **风控** | 风险告警、暂停 |
| **分析** | 平台 PnL |
| **审计** | 操作审计 |
| **财务 / 结算** | 账单、确认/驳回 |
| **缴纳日志** | 链上到账、申诉、归集 |
| **推广** | L1/L2 总览 |
| **提现** | 审核队列、秒到、TxHash |
| **钱包中心** | HD / 冷钱包 / 热钱包 / 公共地址 / 链上余额 |
| **系统** | 健康、Redis、Webhook 统计、钉钉配置、**全域交易日志（可展开明细）**、启动接管审计 |

默认管理员（首次启动自动创建）：

```
邮箱: admin@twinstar.pro（见 ADMIN_EMAIL）
密码: 见 backend/.env → ADMIN_PASSWORD（部署前必须修改）
```

---

## 用户端功能

| 页面 | 路径 | 说明 |
|------|------|------|
| 官网落地页 | `/` | Framer 风格产品介绍 |
| 帮助 / 隐私 / 条款 | `/help` `/privacy` `/terms` | 合规静态页 |
| 注册/登录 | `/register` `/login` | 邮箱验证码；密码显示/隐藏 + 二次确认 |
| 仪表盘 | `/dashboard` | 账户概览、绩效结算横幅 |
| API 管理 | `/api` | 绑定币安合约 API |
| 交易 | `/trading` | 交易控制、持仓状态 |
| 成交记录 | `/trades` | AI 执行记录 + **交易日志（实盘明细）** |
| 风控 | `/risk` | 风险参数、暂停 |
| 绩效结算 | `/settlements` | 账单、专属地址、申诉 |
| 本金快照 | `/snapshots` | 周期权益双重审计 |
| 推广 | `/referrals` | 邀请、下级、**查看下级日志** |
| 提现 | `/withdraw` | 地址簿、分级提现、内部转账 |
| 分析 | `/analytics` | 个人 PnL |
| 个人中心 | `/profile` | 密码、提现密码、2FA |

### 认证与安全操作

| 场景 | 验证 |
|------|------|
| 注册 | 邮箱 + 验证码 + 密码（二次确认） |
| 登录 | 邮箱密码 或 验证码 |
| 敏感操作 | 邮箱验证码 +（提现）提现密码 |

开发模式：`EMAIL_DEV_MODE=true` 时验证码输出至 API 响应与日志。

---

## 安全体系

| 措施 | 实现 |
|------|------|
| Webhook secret | body `secret` 必须匹配 `WEBHOOK_SECRET` |
| Webhook 幂等 | 指纹 TTL 内（默认 120s）只执行一次 |
| Webhook IP 白名单 | 可选 `WEBHOOK_ALLOWED_IPS` |
| Webhook 频率限制 | 每 IP 每分钟上限（默认 120） |
| Payload 校验 | action 白名单；LONG/SHORT 必填 regime/atr/price/tv_tp1~3 |
| JWT 鉴权 | 用户 API 需 Bearer Token |
| 管理员隔离 | `/api/admin/*` 需 admin 角色 |
| 推广者隔离 | 下级 API 校验 referrer 关系 |
| API Key 加密 | Fernet（`ENCRYPTION_KEY`） |
| 生产密钥自检 | `PRODUCTION_STRICT=1` 拒绝默认密钥 |
| 结算门禁 | 未缴费用户无法接收新信号 |
| TxHash 防重复 | 同一链上 TxHash 不可复用 |
| 审计日志 | 钱包/门槛/打款等关键操作留痕 |

---

## API 参考（精选）

基础 URL：`https://twinstar.pro/api` 或 `http://VPS_IP:8000/api`

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康与 `production_ready` |
| `POST /auth/register` | 注册 |
| `POST /auth/login` | 登录 |
| `GET /users/logs` | 用户交易日志（含 `detail`） |
| `POST /users/sync-exchange-logs` | 同步币安成交 |
| `GET /referrals/downline/{id}/logs` | 推广者下级日志 |
| `GET /admin/overview` | 管理概览 |
| `GET /admin/users/{id}/logs` | 管理员查用户日志 |
| `GET /admin/system/trade-logs` | 全站交易日志 |
| `GET /admin/startup-audit` | VPS 接管审计 |
| `GET /admin/wallet/overview` | 钱包链上余额 |
| `POST /webhook`（6010） | TradingView 信号入口 |

Swagger（内网）：`http://127.0.0.1:8000/docs`（`PRODUCTION_STRICT=1` 时关闭）

---

## 交易日志事件类型

| event_type | 来源 | 说明 |
|------------|------|------|
| `SIGNAL` | Supervisor | 收到 TV 信号、准备开仓 |
| `OPEN` | Supervisor | 开仓成功，含滑点与 tv_tps |
| `CLOSE` | Supervisor | 全平，含 pnl / funding_fee |
| `TRAIL` | Supervisor | 雷达保本推升止损 |
| `DEFENSE_HEAL` | Supervisor | 止盈撤销重挂（成功/失败摘要） |
| `DEFENSE_AUDIT` | Supervisor | 防线实盘扫描/补挂 |
| `TP_RETRY` | Supervisor | 单笔 TP/SL 补挂成功 |
| `STARTUP` | Supervisor | VPS 自启接管审计 |
| `STARTUP_FAIL` | Supervisor | 接管异常 |
| `ADJUST` | Supervisor | 人工加减仓识别 |
| `LOCK_TIMEOUT` | Supervisor | 信号锁等待超时 |
| `ERROR` | Supervisor / Dispatcher | API 失败、余额不足等 |
| `BINANCE_FILL` | binance_sync | 从交易所同步的历史成交 |

---

## 环境变量说明

完整模板：[backend/.env.example](backend/.env.example)

### 必填（生产）

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT 签名，≥32 位随机 |
| `ENCRYPTION_KEY` | API Key Fernet 加密 |
| `ADMIN_PASSWORD` | 管理员密码 |
| `WEBHOOK_SECRET` | TradingView Webhook 密钥 |
| `FRONTEND_URL` | 前端地址（CORS、邀请链接） |
| `API_PUBLIC_URL` | 公网 API 基址 |

### 交易

| 变量 | 默认 | 说明 |
|------|------|------|
| `SYMBOL` | ETHUSDT | 交易对 |
| `LEVERAGE` | 15 | 杠杆 |
| `PRODUCTION_STRICT` | 0 | `1` = 拒绝弱密钥 + 关闭 `/docs` |

### 业务与结算

| 变量 | 默认 | 说明 |
|------|------|------|
| `PLATFORM_FEE_RATE` | 0.25 | 绩效服务费 |
| `REFERRAL_L1_RATE` | 0.10 | 一级推广 |
| `REFERRAL_L2_RATE` | 0.05 | 二级推广 |
| `SETTLEMENT_PRIMARY_DAYS` | 7 | 主结算周期 |
| `SETTLEMENT_EXTENDED_DAYS` | 10 | 延长周期 |

### 钉钉

| 变量 | 说明 |
|------|------|
| `DINGTALK_WEBHOOK` | 机器人 Webhook URL |
| `DINGTALK_SECRET` | 加签 Secret |

### 邮件（生产）

```env
EMAIL_DEV_MODE=false
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=587
SMTP_TLS=true
SMTP_USER=noreply@twinstar.pro
SMTP_PASSWORD=...
SMTP_FROM=noreply@twinstar.pro
```

---

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env
uvicorn app.main:app --reload --port 8000
```

Webhook 随 backend 在 **6010** 端口启动。

### 前端

```bash
cd frontend
npm install
npm run dev      # 开发 http://localhost:5173
npm run build    # 生产构建
```

开发代理：Vite → `http://localhost:8000/api`

### 测试

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -q
```

覆盖：supervisor 接管、TP 重试、radar 上下文、钉钉过滤、日志 enrich。

---

## VPS 部署

### 1. 克隆与配置

```bash
git clone https://github.com/vivian5285/panda-quant-platform.git
cd panda-quant-platform
cp backend/.env.example backend/.env
nano backend/.env
```

**生产必改：** `SECRET_KEY`、`ENCRYPTION_KEY`、`WEBHOOK_SECRET`、`ADMIN_PASSWORD`、`FRONTEND_URL`、`API_PUBLIC_URL`、`EMAIL_DEV_MODE=false`、SMTP、钉钉。

### 2. 一键部署

```bash
chmod +x deploy.sh production_check.sh scripts/deploy_lib.sh
bash deploy.sh
```

`deploy.sh`：停旧容器 → `git pull`（保留 `.env`）→ Docker build → 健康检查 → 账户接管验证 → `production_check.sh` → 钉钉 `SYSTEM_RESTART`。

| 变量 | 说明 |
|------|------|
| `SKIP_GIT_PULL=1` | 跳过拉代码 |
| `GIT_BRANCH=main` | 指定分支 |

### 3. 手动更新（日常）

```bash
git pull origin main
docker compose up -d --build backend frontend
docker compose logs -f backend | grep -E "VPS STARTUP|账户接管"
```

### 4. 部署后验收

```bash
docker compose ps
docker compose exec backend python scripts/check_system.py --strict
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
PRODUCTION_STRICT=1 bash production_check.sh
```

### 5. 防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

| 端口 | 公网 |
|------|------|
| 80 / 443 | ✅ |
| 6080 | ⚪ 内测 |
| 6010 / 8000 | ❌ 走 Nginx |
| 6379 | ❌ 禁止 |

### 6. Nginx 路由（同机多系统）

| 路径 | 转发 |
|------|------|
| `/gemini/webhook` | `127.0.0.1:6010/webhook` |
| `/binance/webhook` | `127.0.0.1:5003/webhook` |
| `/deepcoin/webhook` | `127.0.0.1:5004/webhook` |
| `/` | `127.0.0.1:6080` |

配置示例：`deploy/nginx-vps.conf.example`、`deploy/nginx-twinstar.pro.ssl.conf`

---

## HTTPS 与 twinstar.pro

### DNS

| 记录 | 值 |
|------|-----|
| A `@` | VPS IP |
| A `www` | VPS IP |

### 一键 HTTPS

```bash
sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh
# 证书已存在仅重装 Nginx：
sudo bash deploy/setup-https-twinstar.sh --nginx-only
```

### .env（HTTPS 生产）

```env
FRONTEND_URL=https://twinstar.pro
API_PUBLIC_URL=https://twinstar.pro
```

### TradingView Webhook URL

```
https://twinstar.pro/gemini/webhook
```

Body 中 `secret` 与 `WEBHOOK_SECRET` 一致。

### Docker 挂载 .env

`docker-compose.yml` 已挂载 `./backend/.env:/app/.env:ro`，修改 `.env` 后：

```bash
docker compose up -d --force-recreate backend
```

---

## TradingView Webhook

**生产 URL：** `https://twinstar.pro/gemini/webhook`  
**内测直连：** `http://VPS_IP:6010/webhook`

### 支持的 action

| action | 说明 |
|--------|------|
| `LONG` | 开多（先平后开） |
| `SHORT` | 开空（先平后开） |
| `CLOSE` | 换防清场全平 |
| `CLOSE_PROTECT` | 保护性全平（带 reason） |
| `CLOSE_TP3` | TP3 终极收网全平 |

### 开仓 JSON 示例

```json
{
  "secret": "你的WEBHOOK_SECRET",
  "action": "LONG",
  "regime": 3,
  "atr": 30.0,
  "price": 3500.0,
  "tv_tp1": 3550.0,
  "tv_tp2": 3600.0,
  "tv_tp3": 3700.0,
  "reason": "趋势信号"
}
```

### 架构说明（与币安单账户系统独立）

| 服务 | 端口 | Nginx 路径 | 说明 |
|------|------|------------|------|
| 币安单账户大脑 | **5003** | `/binance/webhook` | 独立 legacy 服务，与 Gemini **互不共用** |
| Deepcoin | **5004** | `/deepcoin/webhook` | 独立 legacy 服务 |
| **Gemini 多用户** | **6010** | `/gemini/webhook` | 本仓库 webhook 服务，下文优化均针对此路径 |

### 平仓 JSON 示例

```json
{
  "secret": "你的WEBHOOK_SECRET",
  "action": "CLOSE_PROTECT",
  "regime": 3,
  "side": "LONG",
  "reason": "ADX衰减/波动率保护",
  "pnl_pct": -1.25
}
```

> **Pine Script 注意（v6.9.30 常见 Bug）**  
> `CLOSE_PROTECT` 的 JSON 字符串里 `side`、`reason` 字段**必须闭合引号**，否则 TradingView 会收到 **400 Invalid JSON**：
>
> ```pine
> // ❌ 错误（缺引号，TV 显示 Webhook 400 Bad Request）
> ',"side":"' + posSide + ',"reason":"' + exitReason[1] + ',"pnl_pct":'
>
> // ✅ 正确
> ',"side":"' + posSide + '","reason":"' + str.replace(exitReason[1], '"', '') + '","pnl_pct":'
> ```
>
> Gemini `:6010` 已对上述 Pine 缺引号格式做兼容修复；币安 `:5003` 由独立服务维护，互不影响。

### Gemini Webhook 加固（仅 `/gemini/webhook`）

| 能力 | 说明 |
|------|------|
| **极速 200** | 校验通过后立即响应 TV，写库 + 广播下单放后台线程 |
| **字段归一化** | `pnl_pct` 字符串、中文 `reason`、`regime` 整型等自动兼容 |
| **缺引号修复** | v6.9.30 类 malformed CLOSE_PROTECT JSON 自动修补 |
| **可观测** | 响应头 `X-Webhook-Latency-Ms` 记录网关校验耗时 |
| **Nginx** | `proxy_buffering off`、读超时 30s（仅 gemini location） |

### Webhook 响应时序

| 阶段 | 行为 |
|------|------|
| HTTP 同步 | 校验 secret / JSON / action → **立即返回 200**（通常 &lt;50ms） |
| 后台线程 | `webhook-dispatch-*` 广播至全部活跃 Supervisor 并行执行 |
| 平仓类 | `CLOSE_PROTECT` / `CLOSE_TP3` 与开仓同等优先级入队，日志线程名 `webhook-close-*` |

TradingView 只关心 HTTP 200；实际下单在后台 `ThreadPoolExecutor`（默认 20 并发）完成。

### 幂等

相同 `(action, regime, price, tv_tp*)` 指纹在 `WEBHOOK_IDEMPOTENCY_TTL_SEC`（默认 120s）内重复投递 → 返回 `{ "status": "duplicate" }`，不重复下单。

---

## 运维与自检

```bash
# 实时日志
docker compose logs -f backend

# 数据备份（SQLite + state/）
bash backend/scripts/backup_data.sh

# 优雅关停（SIGTERM 停止所有 Supervisor 哨兵）
docker compose stop backend

# 重建
docker compose down && docker compose up -d --build

# 全域自检
bash production_check.sh
docker compose exec backend python scripts/check_system.py --strict

# Webhook 无 secret 应 403
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:6010/webhook \
  -H "Content-Type: application/json" -d '{"action":"LONG"}'
```

### 定期任务

| 任务 | 建议频率 |
|------|----------|
| `backup_data.sh` | 每日 |
| `production_check.sh` | 每次部署后 |
| 检查 `trade_logs` / 钉钉 | 每日巡检 |
| Let's Encrypt 续期 | certbot 自动 |

---

## 故障排查

| 现象 | 排查 |
|------|------|
| 信号未执行 | 用户 `api_status`、结算门禁、全局暂停、Dispatcher 日志 |
| 重启后 TP 叠单 | 查 `DEFENSE_HEAL` 日志；应对齐则 `skipped:true` |
| 止盈不对齐 | 查 `live_audit`；应触发 heal 或 `DEFENSE_HEAL_FAIL` 钉钉 |
| Webhook 403 | `secret` 不匹配或未传 |
| Webhook duplicate | 正常幂等；检查 TV 是否重复告警 |
| 用户看不到日志 | 确认 `TradeLog` 表有记录；前端 Network 查 `/users/logs` |
| 推广者 403 | 目标非 L1/L2 下级 |
| SMTP 发信失败 | 查 `EMAIL_DEV_MODE`、Hostinger SMTP、容器内 `.env` 挂载 |
| HTTPS 502 | `docker compose ps`、Nginx `proxy_pass` 6080/8000 |

---

## 生产就绪清单

### 用户端

- [ ] 注册/登录 SMTP 真实送达（`EMAIL_DEV_MODE=false`）
- [ ] API 绑定：合约开、提现关
- [ ] `/trades?tab=logs` 可展开实盘明细
- [ ] 绩效结算 + 门禁横幅正常
- [ ] 提现双重验证 + 分级正确

### 管理端

- [ ] 用户详情日志 + **系统 Tab 全域日志** 可展开明细
- [ ] 钱包中心 HD / RPC / 热钱包就绪
- [ ] 钉钉收到 OPEN/CLOSE/STARTUP/CRITICAL，**不**被 TRAIL 刷屏
- [ ] 结算仅确认 `paid` 状态

### 执行引擎

- [ ] 重启后 `GET /admin/startup-audit` 有接管记录
- [ ] 有持仓时防线对齐或 heal 成功
- [ ] TradingView → `/gemini/webhook` 端到端开仓

### 基础设施

- [ ] `PRODUCTION_STRICT=1 bash production_check.sh` 通过
- [ ] `backend/data` `backend/state` 持久卷
- [ ] HTTPS `twinstar.pro` 证书有效
- [ ] 6379 不对公网开放

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 API | FastAPI, SQLAlchemy, Pydantic, python-binance |
| 执行引擎 | PositionSupervisor, threading 哨兵 |
| Webhook | Flask 独立线程 :6010 |
| 链上 | tronpy（TRC20）, web3（EVM） |
| 缓存 | Redis 7 |
| 前端 | React 18, Vite, TypeScript, Framer Motion, ECharts |
| i18n | 中/英双语 |
| 部署 | Docker Compose, Nginx, Certbot, `restart: unless-stopped` |

---

## 路线图

### 已完成

- [x] 币安 U 本位多用户执行引擎（ETHUSDT 15×）
- [x] VPS 智能接管 + `radar_context` 交叉验证
- [x] 止盈对齐扫描 + 智能撤销重挂（防重启叠单）
- [x] **实盘核实 TradeLog + 全站/用户/推广者明细 UI**
- [x] **钉钉关键动作过滤（过程类仅写日志）**
- [x] 推广者 L1/L2 下级日志与账户 API
- [x] 绩效结算 7/10 天 + 结算门禁
- [x] HD 专属充值 + 链上监控 + 申诉 + 归集
- [x] 推广 L1/L2 + 分级提现 + 地址簿 + 自动打款
- [x] 管理端 14 Tab + 钱包中心 + 启动审计
- [x] 官网 Framer 落地页 + HTTPS twinstar.pro
- [x] 响应式 UI + 注册密码二次确认

### 规划中

- [ ] OKX / Bybit 多用户 API 适配
- [ ] Regime 参数后台可配置（当前代码内置）
- [ ] 日志导出 PDF / 长周期归档
- [ ] 多交易对支持

---

## 许可证

**私有项目。** 部署前请修改全部默认密钥与管理员密码。  
仓库：[github.com/vivian5285/panda-quant-platform](https://github.com/vivian5285/panda-quant-platform)
