# Panda Quant Platform · 熊猫量化

多用户 AI 量化托管平台。**TradingView 发信号 → 平台统一广播 → 各用户币安合约独立执行。**

> **当前阶段仅支持币安（Binance）U 本位合约。** OKX / Bybit 等交易所 API 后续开放（各所下单接口不同，需单独适配）。

---

## 架构（强制理解）

```
TradingView Alert（策略大脑：算价、算档位、发 reason）
       ↓ POST /webhook
  SignalDispatcher（ThreadPool 多用户并发广播）
       ↓ 每用户独立 PositionSupervisor + BinanceClient
  User A → 币安 API    User B → 币安 API    ...
```

| 层级 | 职责 |
|------|------|
| **TradingView** | 策略逻辑、regime、atr、tv_tp1/2/3、CLOSE_PROTECT reason |
| **VPS 平台** | 接收警报、校验、并发分发、仓位管理、止盈网格、雷达锁润、先平后开、单向持仓、管理员告警 |
| **用户币安账户** | 各自 API Key 独立下单，资金互不影响 |

### 执行引擎（与成熟币安系统 1:1 对齐）

| 机制 | 行为 |
|------|------|
| **永远一手** | 单向持仓模式（One-Way），禁止双向对冲 |
| **先平后开** | 任何 LONG/SHORT 信号前先全平旧仓，同向/反向均洗场 |
| **四档自适应** | Regime 1~4 → 保证金 15/25/35/50% + TP 分批比例 + 雷达系数 |
| **TV 限价止盈** | 按 tv_tp1/2/3 挂 reduceOnly 限价单，价格由 TV 算好 |
| **雷达移动止损** | 价格越过 TP1 距离 45%/60% 激活，ATR×trail 推升物理 STOP_MARKET |
| **6s 哨兵** | 每 6 秒巡检：方向背离强制全平、人工加减仓自动重构防线 |
| **禁止逆势** | 实盘方向 ≠ TV 方向 → 立即全平 + critical 告警 |
| **状态持久化** | state/user_{id}.json 保存 tv_tps、SL、regime，VPS 重启自动接管 |
| **管理员告警** | 所有交易异常 → **仅推送管理员钉钉**（客户无任何推送） |

---

## VPS 部署（推荐 · 强制步骤）

### 1. 克隆 & 配置

```bash
git clone https://github.com/你的用户名/panda-quant-platform.git
cd panda-quant-platform

cp backend/.env.example backend/.env
nano backend/.env
```

### 2. 生产环境必改项（缺一不可）

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT 签名，≥32 位随机字符串 |
| `ENCRYPTION_KEY` | API Key 加密，≥32 位随机字符串 |
| `ADMIN_PASSWORD` | 管理员登录密码（禁用默认 admin123456） |
| `WEBHOOK_SECRET` | TradingView Webhook 密钥（禁用默认 528586） |
| `FRONTEND_URL` | 前端地址，如 `http://VPS_IP:6080` 或绑域名后的 HTTPS |
| `SMS_DEV_MODE` | 生产设为 `false`，并配置 `SMS_ALIYUN_*` |

可选安全加固：

| 变量 | 说明 |
|------|------|
| `WEBHOOK_ALLOWED_IPS` | TradingView 来源 IP 白名单，逗号分隔 |
| `WEBHOOK_RATE_LIMIT_PER_MIN` | Webhook 每分钟最大请求数（默认 120） |

### 3. 一键部署

```bash
chmod +x deploy.sh production_check.sh scripts/deploy_lib.sh
bash deploy.sh
```

**`deploy.sh` 智能部署流程：**

1. 停止旧容器，**强制杀死** 6080 / 8000 / 6010 端口残留进程  
2. `git fetch` + `reset --hard origin/main` 对齐 GitHub 最新代码（保留 `backend/.env`）  
3. Docker 构建启动，等待 backend healthy  
4. 验证账户接管（Supervisor 加载、雷达哨兵、持仓重建）  
5. 强制跑 `production_check.sh`，全部通过才算部署成功  
6. **推送 SYSTEM_RESTART 钉钉**给管理员（含接管汇总）

跳过 Git 拉取（本地调试）：`SKIP_GIT_PULL=1 bash deploy.sh`  
指定分支：`GIT_BRANCH=main bash deploy.sh`

### 4. 部署后强制验收（必跑）

```bash
# 全域健康检查
docker compose exec backend python scripts/check_system.py

# 确认日志中有账户接管审计
docker compose logs backend | grep "VPS STARTUP"
```

验收标准：

- [ ] 端口 6080 / 6010 / 8000 可访问
- [ ] `/api/health` 返回 `active_supervisors` ≥ 已绑定 API 的用户数
- [ ] 日志出现 `[VPS STARTUP] 账户接管审计` 每个用户一条
- [ ] 无 `Security` 默认密钥警告
- [ ] Webhook `/health` 返回 ok

### 5. 防火墙

```bash
ufw allow 6080    # 前端
ufw allow 6010    # TradingView Webhook
ufw allow 8000    # REST API（生产建议仅内网或 Nginx 反代）
```

---

## 端口规划

| 端口 | 用途 | 访问 |
|------|------|------|
| **6080** | 前端网页 | `http://VPS_IP:6080` |
| **6010** | TradingView Webhook | `http://VPS_IP:6010/webhook` |
| **8000** | REST API | `http://VPS_IP:8000/docs` |

> 已避开 5002 / 5003 / 5004。

---

## TradingView Webhook（策略对接 · 强制格式）

**URL:** `http://你的VPS_IP:6010/webhook`

### 支持的 action

| action | 说明 |
|--------|------|
| `LONG` | 开多（先平后开） |
| `SHORT` | 开空（先平后开） |
| `CLOSE` | 换防清场全平 |
| `CLOSE_PROTECT` | 保护性全平（带 reason） |
| `CLOSE_TP3` | TP3 终极收网全平 |

### 开仓信号示例（LONG / SHORT 必填字段）

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

### 平仓信号示例

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

### VPS 执行参数（与 v6.9 策略对齐）

| 项目 | 值 |
|------|-----|
| 交易对 | ETHUSDT（`.env` 可改 `SYMBOL`） |
| 杠杆 | 15x（`LEVERAGE=15`） |
| Regime 1~4 保证金 | 15% / 25% / 35% / 50% |
| TP 分批 | 各档位独立 ratios |
| 哨兵周期 | 6 秒 |
| 雷达追踪 | 基于 TV 的 TP1 距离 + ATR |

---

## VPS 自启 · 账户接管（强制机制）

容器/进程启动时，对每个已绑定 API 的用户**强制执行**：

1. 从 `state/user_{id}.json` 恢复 `last_tv_side`、`tv_tps`、`current_sl` 等
2. 查询币安实盘持仓
3. **有持仓** → 重建限价 TP 防线 → 启动 6s 哨兵监控
4. **方向背离**（实盘 vs TV）→ 哨兵强制对齐平仓
5. 写入 `trade_logs` 事件 `STARTUP`，并在日志打印审计横幅

查看方式：

```bash
docker compose logs backend | grep "账户接管"
curl http://127.0.0.1:8000/api/health
# 管理员 JWT → GET /api/admin/startup-audit
```

---

## 用户 API 绑定（币安 · 强制安全）

用户在「API 管理」页绑定 **币安合约 API**：

| 权限 | 要求 |
|------|------|
| 合约交易（Futures） | **必须开启** |
| 提现（Withdraw） | **必须关闭**（安全提现） |
| IP 白名单 | 强烈建议开启 |

API Key 使用 Fernet 加密存储，平台无法替用户提现。

---

## 安全防攻击清单

| 措施 | 实现 |
|------|------|
| Webhook secret 校验 | POST body `secret` 必须匹配 `WEBHOOK_SECRET` |
| Webhook IP 白名单 | 可选 `WEBHOOK_ALLOWED_IPS` |
| Webhook 频率限制 | 每 IP 每分钟上限（默认 120） |
| Payload 校验 | action 白名单；LONG/SHORT 必填 regime/atr/price/tv_tp1~3 |
| 登录/SMS 防刷 | 每账号每分钟 20 次 |
| JWT 鉴权 | 所有用户 API 需 Bearer Token |
| 管理员隔离 | `/api/admin/*` 需 admin 角色 |
| API Key 加密 | `ENCRYPTION_KEY` + Fernet |
| 生产密钥自检 | 启动时检测默认密钥并 WARN |
| CORS | 仅允许 `FRONTEND_URL` |

---

## 通知策略

| 对象 | 方式 |
|------|------|
| **管理员（你）** | 所有交易异常 → 钉钉 Webhook（配置 `DINGTALK_WEBHOOK` + `DINGTALK_SECRET`） |
| **客户** | 不推送钉钉/短信/邮件通知（交易过程静默） |

## 用户认证与安全

| 场景 | 验证方式 |
|------|----------|
| **注册** | 邮箱或手机 + 验证码 + 密码 |
| **登录** | 密码登录，或邮箱/手机验证码登录 |
| **安全操作** | 邮箱 + 手机**双重验证码**（须先绑定两种联系方式） |

需双重验证的操作：

- 修改登录密码
- 设置/修改提现密码
- 绑定/删除提现钱包地址
- 提交链上提现（另需提现密码）

开发模式：`SMS_DEV_MODE=true` / `EMAIL_DEV_MODE=true` 时在 API 响应和服务器日志中可见验证码。

---

## 默认管理员

```
邮箱: admin@pandaquant.com
密码: 见 .env ADMIN_PASSWORD（部署前必须修改）
```

---

## 生产级全域自检（上线前必跑）

### 一键自检

```bash
bash deploy.sh                    # 部署
bash production_check.sh          # 生产级全域自检（推荐）
```

### 分项检查

```bash
# 后端 9 项自检（--strict 有 WARN 也失败）
docker compose exec backend python scripts/check_system.py --strict

# 健康接口应 production_ready=true
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool

# VPS 账户接管日志
docker compose logs backend | grep "VPS STARTUP"

# Webhook 无 secret 应 403
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:6010/webhook -H "Content-Type: application/json" -d '{"action":"LONG"}'
```

### 自检清单（全部打勾才可上线）

**基础设施**

- [ ] Docker 容器 `backend` / `frontend` 均为 healthy
- [ ] 端口 6080 / 6010 / 8000 可访问
- [ ] `restart: unless-stopped` 生效（VPS 重启自启）

**安全配置**

- [ ] `SECRET_KEY` / `ENCRYPTION_KEY` / `WEBHOOK_SECRET` / `ADMIN_PASSWORD` 已改
- [ ] `FRONTEND_URL` 为真实域名或 VPS IP
- [ ] `SMS_DEV_MODE=false` + 阿里云短信已配
- [ ] `EMAIL_DEV_MODE=false` + SMTP 已配
- [ ] `DINGTALK_WEBHOOK` + `DINGTALK_SECRET` 已配
- [ ] `/api/health` → `"production_ready": true`

**交易引擎**

- [ ] 日志有 `[VPS STARTUP] 账户接管审计`（有 API 用户时）
- [ ] Webhook 测试 LONG 信号能广播（带 secret）
- [ ] 用户绑定币安 API：开合约 / 关提现
- [ ] `state/user_*.json` 目录可写

**业务配置**

- [ ] 管理后台已添加 USDT 收款地址
- [ ] TradingView Webhook URL 指向 `:6010/webhook`
- [ ] TV 策略 action 与平台一致（LONG/SHORT/CLOSE/CLOSE_PROTECT/CLOSE_TP3）

**用户安全**

- [ ] 注册/登录验证码正常
- [ ] 安全操作双重验证（改密码、绑地址、提现）正常

---

## 分润 & 结算

| 项目 | 比例 |
|------|------|
| 平台分成 | 25% |
| 一级推广 | 10%（从平台分成） |
| 二级推广 | 5%（从平台分成） |

- **结算周期**：优先 7 天；无盈利或仍有持仓 → 延至 10 天；须全平仓后结算
- **付款**：用户手工 USDT 转账 → 提交 TxHash → 管理员确认
- **邀请链接**：`{FRONTEND_URL}/register?ref=PANDA-XXXXXXXX`

---

## 奖励提现

| 金额 | 处理 |
|------|------|
| ≤ $100 | 自动通过 |
| $100 ~ $500 | 待审核 |
| ≥ $500 | 人工审核 |

公链：TRC20 / ERC20 / BEP20 / ARBITRUM / POLYGON / SOL  
内部转账：UID/邮箱/手机，**免手续费**

---

## 常用运维命令

```bash
docker compose logs -f backend          # 后端 + Webhook 日志
docker compose restart                  # 重启
docker compose down && docker compose up -d --build   # 更新重建
docker compose exec backend python scripts/check_system.py --strict
bash production_check.sh
```

---

## 绑域名（后续）

1. 域名 A 记录 → VPS IP
2. Nginx 反代 `:6080` → `https://panda.yourdomain.com`
3. 修改 `FRONTEND_URL=https://panda.yourdomain.com`
4. Webhook 可经 Nginx 转发到 6010，或独立子域名

---

## 技术栈

- **后端**: FastAPI, SQLAlchemy, python-binance, Flask (Webhook)
- **前端**: React 18, Vite, Framer Motion, ECharts
- **部署**: Docker Compose（`restart: unless-stopped`）

---

## 路线图

- [x] 币安 U 本位合约多用户执行
- [x] VPS 自启账户接管 + 状态持久化
- [x] Webhook 安全校验 + 策略 action 适配
- [x] 管理员交易告警（人工干预/方向背离/雷达锁润）
- [ ] OKX / 其他交易所 API 适配（二期）
- [x] 钉钉通知（可选，配置 DINGTALK_WEBHOOK）
