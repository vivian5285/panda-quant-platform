# GEMINI AI · 双子星AI量化

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为成熟的 **TradingView 信号 → 平台广播 → 币安 U 本位合约独立执行** 架构。

> **当前阶段仅支持币安（Binance）U 本位永续合约（默认 ETHUSDT）。** OKX / Bybit 等需单独适配下单接口，列为二期。

---

## 目录

- [产品定位](#产品定位)
- [商业模式](#商业模式)
- [系统架构](#系统架构)
- [项目结构](#项目结构)
- [交易执行引擎](#交易执行引擎)
- [绩效结算与交易门禁](#绩效结算与交易门禁)
- [推广分润与提现](#推广分润与提现)
- [管理后台能力](#管理后台能力)
- [用户端功能](#用户端功能)
- [安全体系](#安全体系)
- [环境变量说明](#环境变量说明)
- [本地开发](#本地开发)
- [VPS 部署](#vps-部署)
- [TradingView Webhook](#tradingview-webhook)
- [运维与自检](#运维与自检)
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

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        TradingView 策略                          │
│              （算价、Regime、TP 档位、平仓 reason）               │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /webhook (6010)
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
         │                   │
         ▼                   ▼
    用户 A 币安 API      用户 B 币安 API
```

| 层级 | 职责 |
|------|------|
| **TradingView** | 策略逻辑、regime、atr、tv_tp1/2/3、CLOSE_PROTECT reason |
| **VPS 平台** | 接收警报、校验、并发分发、仓位管理、止盈网格、雷达锁润、先平后开、单向持仓、结算门禁、管理员告警 |
| **用户币安账户** | 各自 API Key 独立下单，密钥 Fernet 加密存储 |
| **Redis** | 运行时配置缓存、全局交易暂停标记（限流为进程内内存） |
| **SQLite / MySQL** | 用户、交易、结算、推广、审计等业务数据 |

### Docker 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `frontend` | **6080** → 80 | React 静态站 + Nginx 反代 `/api/` |
| `backend` | **8000** | FastAPI REST API |
| `backend` | **6010** | TradingView Webhook（Flask 线程） |
| `redis` | 6379 | 缓存（勿对公网开放） |

> 与同机 **币安(5003) / 深币(5004)** 端口不冲突；推荐 Nginx 80 统一反代，见 [deploy/nginx-vps.conf.example](deploy/nginx-vps.conf.example)。

---

## 项目结构

```
panda-quant-platform/
├── backend/
│   ├── app/
│   │   ├── api/              # REST 路由（auth, users, admin, wallet, …）
│   │   ├── core/             # BinanceClient、PositionSupervisor
│   │   ├── models/           # SQLAlchemy 模型
│   │   ├── schemas/          # Pydantic 请求/响应
│   │   ├── services/         # 业务逻辑层
│   │   │   ├── dispatcher.py       # 信号广播 + 优雅关停
│   │   │   ├── webhook_idempotency.py  # Webhook 幂等去重
│   │   │   ├── settlement.py       # 绩效结算
│   │   │   ├── wallet.py           # 奖励账户、提现
│   │   │   ├── chain_payout.py     # 链上自动打款
│   │   │   ├── auto_payout.py      # 秒到提现后台任务
│   │   │   ├── deposit_monitor.py    # 专属地址链上充值监控
│   │   │   ├── deposit_sweep.py      # 子地址 USDT 归集冷钱包
│   │   │   ├── wallet_overview.py    # 管理端钱包余额汇总
│   │   │   ├── settlement_appeal.py # 缴纳申诉
│   │   │   ├── platform_runtime.py # 可热改提现门槛 / 加密密钥
│   │   │   ├── trading_control.py  # 用户/全局交易暂停
│   │   │   ├── audit.py            # 审计日志
│   │   │   └── …
│   │   └── main.py
│   ├── data/                 # SQLite、platform_runtime.json（持久卷）
│   ├── state/                # user_{id}.json 交易状态（持久卷）
│   ├── logs/
│   ├── scripts/check_system.py
│   ├── scripts/backup_data.sh    # data/ + state/ 备份
│   └── .env.example
├── frontend/
│   └── src/
│       ├── pages/            # 用户页 + 官网 Landing + Admin.tsx
│       ├── pages/admin/      # 管理后台 14 个懒加载 Tab
│       ├── api/              # axios 封装
│       └── i18n/             # 中英文
├── deploy/                   # Nginx、UFW 示例
├── docker-compose.yml
├── deploy.sh
└── production_check.sh
```

---

## 交易执行引擎

与成熟币安执行系统对齐的核心机制：

| 机制 | 行为 |
|------|------|
| **永远一手** | 单向持仓（One-Way），禁止双向对冲 |
| **先平后开** | 任何 LONG/SHORT 前先全平旧仓 |
| **四档自适应** | Regime 1~4 → 保证金 15/25/35/50% + TP 分批 + 雷达系数 |
| **TV 限价止盈** | 按 tv_tp1/2/3 挂 reduceOnly 限价单 |
| **雷达移动止损** | 按 Regime 激活比例（40%/50%/60%/70%）+ ATR×trail 推升 STOP_MARKET |
| **6s 哨兵** | 每 6 秒巡检：方向背离强制全平、人工加减仓重构防线 |
| **禁止逆势** | 实盘方向 ≠ TV 方向 → 立即全平 + critical 告警 |
| **状态持久化** | `state/user_{id}.json` 保存 tv_tps、SL、regime，重启自动接管 |
| **结算门禁** | 有未结清绩效账单 → 跳过信号分发 |

### VPS 自启 · 账户接管

容器启动时对每个已绑定 API 的用户强制执行：

1. 从 `state/user_{id}.json` 恢复 `last_tv_side`、`tv_tps`、`current_sl`
2. 查询币安实盘持仓
3. **有持仓** → 恢复 state、启动 6s 哨兵（**不**在启动时重建限价 TP，与单账户一致）
4. **方向背离** → 哨兵强制对齐平仓
5. 写入 `trade_logs` 事件 `STARTUP`，日志打印审计横幅

```bash
docker compose logs backend | grep "账户接管"
curl http://127.0.0.1:8000/api/health
# 管理员 JWT → GET /api/admin/startup-audit
```

### 执行参数（默认）

| 项目 | 值 |
|------|-----|
| 交易对 | ETHUSDT（`SYMBOL`） |
| 杠杆 | 15x（`LEVERAGE`） |
| Regime 1~4 保证金 | 15% / 25% / 35% / 50% |
| Regime 1~4 雷达激活 | TP1 距离 × 40% / 50% / 60% / 70% |
| Regime 1~4 trail ATR 倍数 | 0.40 / 0.60 / 0.90 / 1.30 |
| 哨兵周期 | 6 秒 |

---

## 绩效结算与交易门禁

### 结算周期逻辑

1. 用户绑定 API 或上次确认结算后，开始 **7 天周期**（`SETTLEMENT_PRIMARY_DAYS`）
2. 到期扫描：若 **无净盈利** 或 **仍有持仓** → 延长至 **10 天**（`SETTLEMENT_EXTENDED_DAYS`）
3. 满足条件且全平仓 → 生成结算单，状态 `pending`（待用户支付）
4. 用户向专属地址转账或提交 TxHash → 状态 `submitted`（待管理员确认；**不会**自助激活）
5. 自动监控匹配或用户 **缴纳申诉** → 管理员审核
6. 管理员确认 → 状态 `paid`/`confirmed`：本金重置、推广奖励入账、恢复交易

### 专属充值地址（HD）与公共备用

| 模式 | 说明 |
|------|------|
| **HD 专属地址（推荐）** | 管理后台 **钱包中心 → HD 充值** 配置 BIP39 助记词；每用户独立 USDT 地址，链上到账自动关联结算 |
| **公共备用地址** | HD 未配置时在结算页展示；可在 **钱包中心 → 公共备用** 维护地址与二维码 |
| **手动 / 申诉** | 自动监控失败时用户提交 TxHash 或 **缴纳申诉**，管理员在 **缴纳日志** 审核 |

### 子地址 USDT 归集（冷钱包）

配置 **钱包中心 → 冷钱包/归集** 后，后台可将子地址 USDT 转至冷钱包（Gas 由热钱包或独立资助钱包支付）。归集成功/失败推送钉钉。

```env
DEPOSIT_SWEEP_AUTO_ENABLED=false   # 或后台开启
DEPOSIT_SWEEP_MIN_USDT=1
DEPOSIT_SWEEP_INTERVAL_SEC=3600
```

### 平台收款地址（历史/备用）

- 管理员在 **钱包中心 → 公共备用** 配置多公链 USDT 地址（TRC20 / ERC20 / BEP20 / ARBITRUM / POLYGON / SOL）
- 每条地址可上传 **钱包收款二维码**（PNG/JPEG/WebP，≤2MB）
- 用户配置 HD 后优先看到 **专属子地址**；公共地址为 fallback

### 用户 API 绑定要求

| 权限 | 要求 |
|------|------|
| 合约交易（Futures） | **必须开启** |
| 提现（Withdraw） | **必须关闭** |
| IP 白名单 | 强烈建议绑定 VPS 出口 IP |

---

## 推广分润与提现

### 推广关系

- 注册链接：`{FRONTEND_URL}/register?ref=PANDA-XXXXXXXX`
- 管理员确认结算后，L1/L2 奖励自动记入推广人 **奖励账户**

### 提现分级（门槛可后台热改）

管理员在 **钱包中心 → 提现门槛** 随时修改 **秒到额度** 与 **审核门槛**（持久化至 `data/platform_runtime.json` + Redis）：

| 金额区间 | 处理 |
|----------|------|
| &lt; 最低额（默认 $10） | 拒绝 |
| ≤ 秒到额度（默认 $100） | **免审核**；可配置 **自动链上打款** |
| 介于两者之间 | 待管理员审核 |
| ≥ 审核门槛（默认 $500） | 须管理员审核通过后链上打款 |

### 秒到自动链上打款

配置热钱包后，≤ 秒到额度的提现提交即触发后台链上 USDT 转账：

```env
PAYOUT_AUTO_ENABLED=true
PAYOUT_TRC20_PRIVATE_KEY=你的Tron热钱包私钥
PAYOUT_EVM_PRIVATE_KEY=你的EVM热钱包私钥
ETH_RPC_URL=https://...
BSC_RPC_URL=https://...
ARBITRUM_RPC_URL=https://...
POLYGON_RPC_URL=https://...
TRON_API_URL=https://api.trongrid.io
TRON_API_KEY=可选
```

| 能力 | 说明 |
|------|------|
| 支持公链 | TRC20、ERC20、BEP20、ARBITRUM、POLYGON（SOL 须人工） |
| TxHash | 自动写入提现记录，用户与管理员均可点击区块浏览器查看 |
| 失败回退 | 保持秒到队列，管理员可手动补打款 |
| 审计 | `withdrawal.auto_payout` / `withdrawal.auto_payout_failed` |

未启用 `PAYOUT_AUTO_ENABLED` 时，秒到订单进入队列，管理员手动填写 TxHash 完成。

### 地址簿与内部转账

- 提现须先绑定 **地址簿**（多链 USDT 地址 + 双重验证）
- 提交提现另需 **提现密码** + 邮箱/手机验证码
- **内部转账**：UID / 邮箱 / 手机号，免手续费、实时到账

---

## 管理后台能力

访问路径：登录管理员账号 → `/admin`（需 `admin` 角色）

| 模块 | 功能 |
|------|------|
| **概览** | 用户数、待结算、**待处理提现**、在线指标、生产自检摘要 |
| **财务** | 结算单、收款确认/驳回 |
| **用户** | 列表、详情（交易/日志/推广/本金历史）、交易控制、币安成交同步 |
| **结算** | 批量扫描结算、确认/驳回付款（仅 `paid` 可确认） |
| **缴纳日志** | 链上到账记录、**缴纳申诉**队列、**归集记录** |
| **推广** | L1/L2 总览、奖励统计 |
| **信号** | TV 模板管理、测试下发、分发日志 |
| **钱包中心** | **总览链上余额**；HD 助记词；冷钱包+自动归集；热钱包打款+Gas；公共备用地址；提现门槛 |
| **提现** | 审核队列、秒到队列、手动/自动 TxHash |
| **风控** | 风险告警、用户暂停 |
| **执行** | 实时 WebSocket 监控、Supervisor 状态 |
| **分析** | 平台级 PnL、用户分布 |
| **审计** | 全站操作审计（含钱包/门槛变更详情） |
| **系统** | 健康指标、Redis、Webhook 统计、**钉钉配置**、管理员改密、启动接管审计 |

默认管理员（首次启动自动创建）：

```
邮箱: admin@twinstar.pro
密码: 见 backend/.env → ADMIN_PASSWORD（部署前必须修改）
```

---

## 用户端功能

| 页面 | 路径 | 说明 |
|------|------|------|
| **官网落地页** | `/` | Framer 风格产品介绍、FAQ、注册入口 |
| 帮助 / 隐私 / 条款 | `/help` `/privacy` `/terms` | 官网合规与说明页 |
| 注册/登录 | `/register` `/login` | 邮箱/手机验证码注册与登录 |
| 仪表盘 | `/dashboard` | 账户概览、绩效结算横幅 |
| API 管理 | `/api` | 绑定币安合约 API |
| 交易 | `/trading` | 交易控制、持仓状态 |
| 成交记录 | `/trades` | 自定义日期筛选、币安 ETHUSDT 成交同步 |
| 风控 | `/risk` | 风险参数、暂停状态 |
| 绩效结算 | `/settlements` | 账单、**专属充值地址**、到账日志、**缴纳申诉** |
| 本金快照 | `/snapshots` | 周期权益与交易盈亏双重审计历史 |
| 推广 | `/referrals` | 邀请码、下级、奖励 |
| 提现 | `/withdraw` | 地址簿、分级提现、内部转账、TxHash 历史 |
| 分析 | `/analytics` | 个人 PnL 图表 |
| 个人中心 | `/profile` | 密码、提现密码、双重验证绑定 |

### 认证与安全操作

| 场景 | 验证 |
|------|------|
| 注册 | 邮箱 + 验证码 + 密码 |
| 登录 | 邮箱密码 或 邮箱验证码 |
| 安全操作 | 邮箱验证码 |

需双重验证：改登录密码、设/改提现密码、绑定/删除提现地址、提交链上提现。

开发模式：`EMAIL_DEV_MODE=true` 时验证码输出至 API 响应与服务器日志（短信通道已停用，无需配置阿里云 SMS）。

---

## 安全体系

| 措施 | 实现 |
|------|------|
| Webhook secret | body `secret` 必须匹配 `WEBHOOK_SECRET`（无硬编码默认值） |
| Webhook 幂等 | 相同 payload 指纹在 TTL 内（默认 120s）只执行一次；重复请求返回 `duplicate` |
| Webhook IP 白名单 | 可选 `WEBHOOK_ALLOWED_IPS` |
| Webhook 频率限制 | 进程内滑动窗口，每 IP 每分钟上限（默认 120） |
| Payload 校验 | action 白名单；LONG/SHORT 必填 regime/atr/price/tv_tp1~3 |
| JWT 鉴权 | 用户 API 需 Bearer Token |
| 管理员隔离 | `/api/admin/*` 需 admin 角色 |
| API Key 加密 | Fernet（`ENCRYPTION_KEY`） |
| 生产密钥自检 | 启动 WARN；`PRODUCTION_STRICT=1` 时默认密钥 **拒绝启动** |
| CORS | `FRONTEND_URL` + 本地开发 localhost 源 |
| 结算门禁 | 未缴费用户无法接收新信号 |
| TxHash 防重复 | 同一链上 TxHash 不可重复提交或跨结算单复用 |
| 双重盈利审计 | 重启同步 Binance 成交 + 权益快照；结算仅按交易订单盈亏 |
| 审计日志 | 收款地址、提现门槛、打款等关键操作留痕 |

### 通知策略

| 对象 | 方式 |
|------|------|
| **管理员** | 交易异常 → 钉钉（`DINGTALK_WEBHOOK` + `DINGTALK_SECRET`） |
| **客户** | 交易过程静默；提现到账等通过站内通知 |

---

## 环境变量说明

完整模板见 [backend/.env.example](backend/.env.example)。

### 必填（生产）

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT 签名，≥32 位随机字符串 |
| `ENCRYPTION_KEY` | API Key 加密，≥32 位 |
| `ADMIN_PASSWORD` | 管理员密码 |
| `WEBHOOK_SECRET` | TradingView Webhook 密钥 |
| `FRONTEND_URL` | 前端地址（CORS、邀请链接） |
| `API_PUBLIC_URL` | 公网 API 基址（Webhook、回调等） |

### 业务与结算

| 变量 | 默认 | 说明 |
|------|------|------|
| `PLATFORM_FEE_RATE` | 0.25 | 绩效服务费比例 |
| `REFERRAL_L1_RATE` | 0.10 | 一级推广 |
| `REFERRAL_L2_RATE` | 0.05 | 二级推广 |
| `SETTLEMENT_PRIMARY_DAYS` | 7 | 主结算周期 |
| `SETTLEMENT_EXTENDED_DAYS` | 10 | 延长结算周期 |
| `WITHDRAW_AUTO_MAX_USD` | 100 | 秒到额度初值（可被后台覆盖） |
| `WITHDRAW_REVIEW_MIN_USD` | 500 | 审核门槛初值 |
| `WITHDRAW_MIN_USD` | 10 | 最低提现 |

### 交易

| 变量 | 默认 | 说明 |
|------|------|------|
| `SYMBOL` | ETHUSDT | 交易对 |
| `LEVERAGE` | 15 | 杠杆 |
| `PRODUCTION_STRICT` | 0 | 设为 `1` 时 insecure 密钥拒绝启动，并关闭 `/docs` OpenAPI |
| `ENABLE_BACKGROUND_SCHEDULERS` | true | 结算周期扫描 + 链上充值监控后台任务 |
| `DEPOSIT_HD_MNEMONIC` | — | BIP39 助记词（**也可在管理后台 → 钱包中心 → HD 充值**，后台优先于 env） |
| `DEPOSIT_SCAN_INTERVAL_SEC` | 180 | 充值监控轮询间隔（秒） |
| `DEPOSIT_SWEEP_AUTO_ENABLED` | false | 子地址 USDT 自动归集（也可后台开启） |
| `DEPOSIT_SWEEP_MIN_USDT` | 1 | 最低归集金额 |
| `DEPOSIT_SWEEP_INTERVAL_SEC` | 3600 | 归集扫描间隔 |
| `ETH_RPC_URL` | — | ERC20 充值监控 / EVM 打款 |
| `BSC_RPC_URL` | — | BEP20 充值监控 / BSC 打款 |
| `ARBITRUM_RPC_URL` | — | Arbitrum USDT 充值监控 |
| `POLYGON_RPC_URL` | — | Polygon USDT 充值监控 |
| `TRON_API_URL` / `TRON_API_KEY` | — | TRC20 充值监控 |
| `WEBHOOK_IDEMPOTENCY_TTL_SEC` | 120 | Webhook 幂等窗口（秒） |

### 自动链上打款

见 [推广分润与提现](#秒到自动链上打款) 一节。

### 充值监控（专属地址）

| 链 | 自动到账 | 说明 |
|----|----------|------|
| TRC20 | ✅ | 需 `TRON_API_URL` |
| ERC20 | ✅ | 需 `ETH_RPC_URL` |
| BEP20 | ✅ | 需 `BSC_RPC_URL` |
| Arbitrum | ✅ | 需 `ARBITRUM_RPC_URL` |
| Polygon | ✅ | 需 `POLYGON_RPC_URL` |
| SOL 等 | ❌ | 仅展示公共备用地址，须手动提交 TxHash |

用户端「专属地址」与结算支付表单仅展示**已监控链**；`GET /api/deposit-chains` 返回当前监控链与 RPC 就绪状态。

---

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 后启动
uvicorn app.main:app --reload --port 8000
```

Webhook 随 backend 进程在 `6010` 端口启动。

### 前端

```bash
cd frontend
npm install
npm run dev      # 开发
npm run build    # 生产构建
```

开发时前端通常代理至 `http://localhost:8000/api`。

---

## VPS 部署

### 1. 克隆与配置

```bash
git clone https://github.com/你的用户名/panda-quant-platform.git
cd panda-quant-platform
cp backend/.env.example backend/.env
nano backend/.env
```

### 2. 一键部署

```bash
chmod +x deploy.sh production_check.sh scripts/deploy_lib.sh
bash deploy.sh
```

`deploy.sh` 流程：停旧容器 → 拉取最新代码（保留 `.env`）→ Docker 构建 → 健康检查 → 账户接管验证 → `production_check.sh` → 钉钉 SYSTEM_RESTART 通知。

| 环境变量 | 说明 |
|----------|------|
| `SKIP_GIT_PULL=1` | 跳过 Git 拉取（本地调试） |
| `GIT_BRANCH=main` | 指定分支 |

### 3. 部署后验收

```bash
docker compose exec backend python scripts/check_system.py --strict
docker compose logs backend | grep "VPS STARTUP"
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```

验收清单：

- [ ] 容器 `backend` / `frontend` / `redis` healthy
- [ ] `/api/health` → `production_ready: true`
- [ ] `PRODUCTION_STRICT=1 bash production_check.sh` 全部通过（含 RPC / 助记词 / 调度器 / 官网路由）
- [ ] `backend/.env`：`EMAIL_DEV_MODE=false`，并配置 `SMTP_*`（仅邮箱注册/登录，无需短信）
- [ ] `SECRET_KEY` / `ENCRYPTION_KEY` / `WEBHOOK_SECRET` / `ADMIN_PASSWORD` 已改为强随机值
- [ ] `FRONTEND_URL` / `API_PUBLIC_URL` 为公网域名或 VPS IP（**非** `localhost` / `0000:6080`）
- [ ] **钱包中心**：HD 助记词、冷钱包、热钱包（按需）、各监控链 RPC / Tron API
- [ ] `ENABLE_BACKGROUND_SCHEDULERS=true`（结算扫描 + 充值监控 + 归集）
- [ ] 用户端 **专属充值地址**、**本金快照**、**缴纳申诉** 流程可用
- [ ] 结算确认仅接受 `paid` 状态（不可从 `pending` 直接确认）
- [ ] 秒到/审核门槛、钉钉 Webhook 已按业务设定
- [ ] （可选）`PAYOUT_AUTO_ENABLED` 与热钱包已配置
- [ ] 官网 `/` `/help` `/privacy` `/terms` 可访问

### 4. 防火墙（UFW）

推荐仅开放 **80 / 443**，三系统 Webhook 与 Gemini 网页均走 Nginx：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
# 或: sudo bash deploy/ufw-firewall.sh.example
```

| 端口 | 公网放行 |
|------|----------|
| 80 / 443 | ✅ 推荐 |
| 6080 | ⚪ 仅内测直连 |
| 6010 / 8000 | ❌ 走 Nginx 反代 |
| 6379 | ❌ 禁止 |

### 5. Nginx 与同机共存

| 路径 | 转发 |
|------|------|
| `/binance/webhook` | `127.0.0.1:5003/webhook` |
| `/deepcoin/webhook` | `127.0.0.1:5004/webhook` |
| `/gemini/webhook` | `127.0.0.1:6010/webhook` |
| `/` | `127.0.0.1:6080` |

反代后 `.env`：

```env
FRONTEND_URL=http://你的VPS_IP
API_PUBLIC_URL=http://你的VPS_IP
```

TradingView URL：`http://你的VPS_IP/gemini/webhook`

---

## TradingView Webhook

**推荐 URL：** `http://你的VPS_IP/gemini/webhook`  
**内测直连：** `http://你的VPS_IP:6010/webhook`

### 支持的 action

| action | 说明 |
|--------|------|
| `LONG` | 开多（先平后开） |
| `SHORT` | 开空（先平后开） |
| `CLOSE` | 换防清场全平 |
| `CLOSE_PROTECT` | 保护性全平（带 reason） |
| `CLOSE_TP3` | TP3 终极收网全平 |

### 幂等与重复投递

TradingView 或网络可能重复 POST 同一信号。平台对 `(action, regime, price, tv_tp*)` 计算指纹：

- 首次：正常分发，返回 `dispatch_id`
- TTL 内重复：跳过执行，返回 `{ "status": "duplicate", "dispatch_id": "..." }`
- 持久化：Redis SETNX + DB 表 `webhook_idempotency_keys`（Redis 不可用时降级）

### 开仓示例

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

### 平仓示例

```json
{
  "secret": "你的WEBHOOK_SECRET",
  "action": "CLOSE_PROTECT",
  "regime": 3,
  "atr": 28.5,
  "price": 3480.0,
  "reason": "ADX衰减/波动率保护"
}
```

---

## 运维与自检

```bash
# 实时日志
docker compose logs -f backend

# 数据备份（SQLite + state/）
bash backend/scripts/backup_data.sh

# 优雅关停（SIGTERM 时停止所有 Supervisor 哨兵）
docker compose stop backend

# 重启 / 重建
docker compose restart
docker compose down && docker compose up -d --build

# 全域自检
bash production_check.sh
docker compose exec backend python scripts/check_system.py --strict

# Webhook 无 secret 应 403
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:6010/webhook \
  -H "Content-Type: application/json" -d '{"action":"LONG"}'
```

### 常用 API

| 端点 | 说明 |
|------|------|
| `GET /api/health` | 健康与 production_ready |
| `GET /api/admin/overview` | 管理概览 |
| `GET /api/admin/startup-audit` | VPS 接管审计 |
| `GET /api/admin/system/audit-logs` | 审计日志 |
| `GET /api/admin/wallet/overview` | 钱包中心链上余额汇总（管理员） |
| `GET /api/admin/sweep/logs` | USDT 归集记录 |
| `GET /api/wallet/my-deposit-addresses` | 用户专属充值地址 |
| `POST /api/wallet/settlements/{id}/appeal` | 用户缴纳申诉 |
| `GET /api/wallet/deposit-addresses` | 公共备用收款地址 |
| `GET /api/deposit-addresses/{id}/qr` | 收款地址钱包二维码图片 |
| `POST /api/admin/deposit-addresses/{id}/qr-image` | 管理员上传二维码（multipart） |
| `DELETE /api/admin/deposit-addresses/{id}/qr-image` | 管理员删除二维码 |
| `GET /api/wallet/withdraw/settings` | 提现门槛与链费用 |

Swagger（仅内网）：`http://127.0.0.1:8000/docs`（`PRODUCTION_STRICT=1` 时关闭）

---

## 生产就绪清单

上线前按 **用户端 → 管理端 → 官网 → 基础设施** 逐项验收：

### 用户端

| 项 | 生产要求 |
|----|----------|
| 注册/登录 | `EMAIL_DEV_MODE` = false，SMTP 真实验证码送达 |
| API 绑定 | 合约开、提现关；IP 白名单建议开启 |
| 绩效结算 | 专属 HD 地址展示；到账自动匹配或申诉通道 |
| 结算门禁 | 未缴费用户 Dashboard/交易页横幅 + 信号暂停 |
| 提现 | 双重验证 + 提现密码；秒到/审核分级正确 |
| 本金快照 | `/snapshots` 周期权益与盈亏可对账 |

### 管理端

| 项 | 生产要求 |
|----|----------|
| 钱包中心 | HD、冷钱包、热钱包、RPC 就绪；**刷新链上余额** 正常 |
| 缴纳日志 | 到账记录、申诉审核、归集记录可见 |
| 结算 | 仅确认 `paid`；TxHash 不可重复 |
| 钉钉 | Webhook + Secret；交易异常 / 归集 / 重启可收到 |
| 审计 | 钱包与门槛变更有日志 |

### 官网

| 项 | 生产要求 |
|----|----------|
| `/` | 落地页、注册/登录 CTA、中英 i18n |
| `/help` `/privacy` `/terms` | 静态页 HTTP 200 |
| SEO | `index.html` meta / og 标签已配置 |
| 演示视频 | 可选 `VITE_DEMO_VIDEO_URL` |

### 基础设施

| 项 | 命令 / 标准 |
|----|-------------|
| 全域自检 | `bash production_check.sh` |
| 严格模式 | `PRODUCTION_STRICT=1 bash production_check.sh` |
| Python 自检 | `docker compose exec backend python scripts/check_system.py --strict` |
| 密钥 | 无默认 `admin123456` / 空 `SECRET_KEY` |
| 数据持久化 | `backend/data` `backend/state` 已挂载卷 |
| 备份 | `bash backend/scripts/backup_data.sh` 定期执行 |

---

## 绑域名（后续）

1. 域名 A 记录 → VPS IP  
2. Nginx 反代 + HTTPS  
3. `FRONTEND_URL` / `API_PUBLIC_URL` 改为 `https://…`  

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 API | FastAPI, SQLAlchemy, Pydantic, python-binance |
| Webhook | Flask（独立线程，6010） |
| 链上打款 / 归集 | tronpy（TRC20）, web3（EVM 系） |
| 缓存 | Redis |
| 前端 | React 18, Vite, TypeScript, Framer Motion, ECharts |
| 官网 | Framer 风格 Landing + Help/Privacy/Terms |
| i18n | 中/英双语 |
| 部署 | Docker Compose, Nginx, `restart: unless-stopped` |

---

## 路线图

- [x] 币安 U 本位多用户执行引擎
- [x] VPS 自启账户接管 + 状态持久化
- [x] Webhook 安全校验 + TV action 适配
- [x] 绩效结算（7/10 天）+ 结算门禁
- [x] 多公链 USDT 收款地址（管理员热配置 + 审计）
- [x] 推广 L1/L2 分润 + 分级提现 + 地址簿
- [x] 秒到额度后台热改 + 自动链上打款（热钱包）
- [x] 管理员全域后台（用户/财务/信号/审计/执行监控）
- [x] 币安 ETHUSDT 成交同步、手机/邮箱验证码登录
- [x] 钉钉管理员交易告警
- [x] HD 专属充值地址 + 链上自动到账匹配
- [x] 缴纳申诉 + 缴纳日志 + TxHash 防重复
- [x] 子地址 USDT 自动归集冷钱包 + 钉钉告警
- [x] 管理端钱包中心（链上余额 / 分类配置）
- [x] 用户本金快照双重审计页
- [x] 官网 Framer 落地页 + 合规静态页
- [ ] OKX / Bybit 等交易所 API 适配（二期）
- [ ] 域名 HTTPS 一键脚本

---

## 许可证

私有项目。部署前请修改全部默认密钥与管理员密码。
