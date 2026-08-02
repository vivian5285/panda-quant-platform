# GEMINI AI · 双子星 AI 量化

[![Stack](https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Binance%20%7C%20OKX%20%7C%20Gate%20%7C%20DeepCoin-yellow)]()
[![Domain](https://img.shields.io/badge/Production-twinstar.pro-green)]()

多用户 **AI 量化决策引擎 SaaS** 平台。用户侧呈现为 AI 托管叙事；底层为 **TradingView 策略信号 → VPS 网关 → 多交易所 U 本位永续独立执行** 架构。

> **文档同步（2026-08-02 · TP3雷达管理 · DingTalk已清除 · 雷达守卫启动）**  
> 凡与本文冲突的旧描述（「TP3 挂限价并与雷达互斥」「VPS 独立拉 1h ATR / 场景切换」「雷达扫出=失败离场」「查不到单就盲补」「硬止损=TV原价」「硬=ATR地板+滑点垫」「日亏熔断默认开」「杠杆/仓位永远硬编码不可改」「激活→entry±0.5ATR」「ADX 85/80/70 写反」「ADX 70%~90% 连续插值」）**一律作废**。  
> 权威：`docs/VPS_SYSTEM_SPEC_GEMINI_MULTIUSER.md`（与桌面《VPS完整系统规格_Gemini多用户版》同步）· `docs/SMART_REENTRY_CLOSED_LOOP.md` · 部署：`docs/VPS_DEPLOY.md`  
> **事故对照（优先）**：`docs/SYSTEM_ISSUE_FIX_LOG.md` — 现象→根因→修复→复查点；含 **v16.4.2-incident-harden** + **pipeline-ledger-v1**（TradeLedger 状态机 / 岗位交接 / 督察官 / REST 阀门）+ **marathon-radar-fee-be**。

### 当前实盘一句话

**硬止损是底线，雷达是骑士。** TP1/TP2 限价兑现 10%/20%；**TP3（70%）永不挂限价**，全程雷达管理、无价格天花板。ATR **一律用 webhook `atr`（TV）**，VPS 不再独立拉取交易所 ATR。雷达启动=ADX **离散 70%/80%/90%**×(1.35×ATR)（&lt;20→70%早 · 20–30→80% · &gt;30→90%晚；**弱早强晚**）；**激活=手续费保本（fee+tick）**，非 entry±0.5ATR；TP 后只缩止损数量、不改价。重入最多一次。本地挂单标签 + 挂单硬帽≤5 + ETH/XAU 隔离。  
开仓链路按 **流水线岗位** 交接：信号官 → 准入官 → 仓位稽查 → 执行官（TP 自检≈30%）→ 督察官（VERIFIED）→ 通讯官（**TG**）；账本 `data/supervisor/ledgers/`。暂停/冷却时哨兵**禁止 REST**，优先读账本/缓存。  
**两次 TV 只有三条路**：①TP1/TP2 止盈（+雷达兑现剩余）②雷达 BE/微赚扫出→更优价再入（≤1 次）③硬止损认输不重入。  
验收必须以：交易所空仓零挂单 + 本地/GitHub/VPS **三方 commit 同数字** + 日志/订单 JSON / **TG** 为准。

### 开发推送与 VPS 部署工作流

```
本地修改代码
    ↓
bash _push_github.sh          ← 本地自检 (模块语法 + TV webhook 连通性)
    ↓ (自动推送到 GitHub main)
VPS: ssh 后执行:
    ↓
cd ~/panda-quant-platform
bash deploy.sh                 ← 拉取 + 构建 + 启动 + 全域自检
```

**TV Webhook 生产地址：** `https://twinstar.pro/gemini/webhook`

**自检三件套：**

| 脚本 | 用途 | 运行位置 |
|------|------|---------|
| `_push_github.sh` | 本地推送前自检：模块语法 + TV webhook 连通性 | 本地开发机 |
| `production_check.sh` | VPS 部署后全域检查：端口/容器/HTTP/TV webhook/账户接管 | VPS |
| `scripts/selfcheck.sh` | VPS 快速巡检：TV webhook + 内网/外网连通性 | VPS |



### 多交易所实盘对齐（2026-07-27 · 可候命真实 TV）

| 交易所 | 品种 | 监督器 | 开关 | 说明 |
|--------|------|--------|------|------|
| **Binance** | **ETH + XAU** | `PositionSupervisor` + `AdverseRadarMixin` | `/admin` `enabled_exchanges` | 唯一执行 XAU TV 的所；XAU 只分发给绑定币安 API 的用户 |
| **OKX** | **ETH only** | 同 Binance 共享 `PositionSupervisor` | 同上 | 不创建 XAU supervisor；收到 XAU → `symbol_not_on_exchange` 跳过 |
| **Gate** | **ETH only** | 同上 | 同上 | 同上 |
| **DeepCoin** | **ETH only** | `DeepcoinPositionSupervisor`（共享 mixin；合约张数 min=1） | 同上 | 先平后开+TP12+硬止损+雷达与币安同逻辑；张/精度按深币规则；**强制 APP 开平仓/双向**（绑定探测；不自动切）+ 无菌闸全侧净场 |

**仓位权重 + 杠杆（全所同一公式）**：`名义 = 权益 × margin_pct × leverage`（默认 20%×5x=1×权益；`/admin` 按用户覆盖）。分发时写入 `margin_pct_frac` / `entry_leverage`，币安/OKX/Gate/DeepCoin 同一套解析。

**对齐铁律（全所同一套）**：
1. **先平后开** → 净场核实撤单（含深币再核）→ 开仓 → **TP1/TP2 + 硬止损(1.15)**（Stage0 仅硬止损上簿；雷达待 ADX 70/80/90%×1.35ATR 激活后再挂）  
2. **10s 开平铁律**（无 TV 时间戳比较）：  
   - 同窗 **CLOSE 先 / 同时** → 执行一次平仓再开仓 → **最终必有持仓**  
   - 同窗 **OPEN 先** 或 OPEN 已成交后 **10s 内又到 CLOSE** → **自动忽略平仓**（防「先开又秒平」）  
   - 单独迟到的平仓（>10s）才真正平仓  
3. TP 全成/部分成交 → 雷达/硬止损数量跟 **实时残仓**（REST cool 排队，结束 flush）  
4. 限流共享 180s cool；哨兵 cool/pause **禁 REST**  
5. 深币 TP1 ≥ **1 张**；整数切片自检允许偏离严格 30%（但禁止吃光雷达余仓）  
6. **深币持仓模式（对齐单系统 v13.91.6-hedge-sterile）**：APP **必须「开平仓 / 双向」**（`posSide=long/short` + `mrgPosition=merge`）；**禁止「买卖 / 单向」**；代码**不自动切模式**。绑定 API 时探测双向，未通过则拒绑；开仓前再闸。平仓/先平后开：**batch-close + 两侧 reduceOnly**；撤单扫 `IsMergeMode=1/0/-1`；开仓前仓=0 且限价+条件单=0，否则 **拒开**（防反向/蚂蚁/幽灵）

**管理员决策**：是否对某所「开放交易」只在后台开闸；代码侧须先保证逻辑已对齐、门禁不误拦、分发不串所。  
事故复盘权威：`docs/SYSTEM_ISSUE_FIX_LOG.md`（§8 全所 harden · §10 XAU 仅币安 · §11 深币挂单 · §12 10s 忽略迟到平仓 · §13 深币双向净场 · §14 深币绑定强制开平仓双向 · §15 TV跳过/秒平）。
### 生产流水线验收清单（pipeline-ledger-v1 · 防今日复现）

> 对照桌面《全域生产级工作流架构方案》+ `docs/SYSTEM_ISSUE_FIX_LOG.md` §9。  
> 模块：`trade_ledger.py` · `pipeline_officers.py` · `rest_throttle_valve.py`（Binance/OKX/Gate + DeepCoin 同编制）。

#### A. 今日事故 → 闸门（必须全绿）

| 今日问题 | 闸门 | 代码锚点 |
|----------|------|----------|
| TP1+TP2 吞整仓 | 执行官 `self_check_tp_slices` ≈30% 拒挂；督察再验 | `_compute_tp_slices` / `ExecutionOfficer` |
| 假 TP3 drift | `PLACEABLE_TP_LEVELS={1,2}`；consumed 不含 3 | `tp_regime_targets` / consumed 同步 |
| `initial_qty` 压扁 | `_set_open_qty_baseline` 监控中只升不降；持仓督察查压缩 | `adverse_radar_guard` / `ChiefAuditor.recheck_live` |
| 限流后仍 REST | `sentinel_may_rest` + `acquire_rest_permit` + cool **180s** `_GLOBAL` | `rest_throttle_valve` / `ip_rest_cooldown` / book cache |
| 空仓后仍暂停 | FLAT 自动清：`chief_auditor_fail` / `open_orders_gt_5` / `open_book_dirty` / ATR应急 / 方向 / 先平后开失败 | `should_auto_unpause_on_flat` |
| 雷达余仓量不对 | 缩量优先 `watched_qty`/实盘，公式影子最后手段 | `_boost_radar_after_tp_fill` |
| OPEN 抢跑 TG | 通讯官门禁；DeepCoin **先督察再 OPEN**；held 可 flush | `CommunicationsOfficer` |

#### B. 岗位交接（状态机）

```
SIGNAL_RECEIVED → PENDING_CLEAR → CLEARED → ENTRY_SUBMITTED
  → ENTRY_CONFIRMED → ORDERS_PLACED → VERIFIED → REPORTED → (hold) → FLAT
失败 → FAILED（暂停新开）  卡住超阈 → PIPELINE_STALL critical
```

| 检查项 | 期望 |
|--------|------|
| 账本键 | `用户-交易所-品种` → `data/supervisor/ledgers/ledger_*.json` |
| 禁止跳步 | `TradeLedger.advance` 无 `force` 时不可越级 |
| 阶段卡住 | `PHASE_STALL_SEC`；哨兵 `check_phase_stall` → `PIPELINE_STALL` |
| 开仓后督察 | `run_post_open_pipeline` → VERIFIED 才 REPORTED |
| 持仓再督察 | TP 成交后 `ChiefAuditor.recheck_live`（硬止损公式 / 基线压缩 / 双TP后≈70%余仓） |
| 硬止损复查 | `fill±(|TV.e−SL|×1.15)` 容差内 **或** 已 hung |
| 准入官 | dispatcher：`api_status=active` 且有密钥，否则不进流水线 |

#### C. 上线前自检口令

1. `git rev-parse --short HEAD` 本地 = GitHub `main` = VPS **同数字**  
2. `pytest backend/tests/test_pipeline_workflow.py` 全绿  
3. 币安/OKX/Gate/DeepCoin：空仓 + 挂单 0；无 `trading_paused` 残留  
4. 当面最小资金 LONG：硬1 + 雷达1 + TP 仅 1/2；账本相位到 `REPORTED`；TG OPEN 在督察后  
5. 人为 cool / pause：哨兵与空闲巡检 **无新 REST**  
6. TP 自检故意算错：拒挂 + `CHIEF_AUDITOR_FAIL` 暂停  

#### D. 残余风险收口状态（2026-07-27 harden-2）

| 项 | 状态 |
|----|------|
| 对账 REST 阀门 | OKX/Gate/DeepCoin `_request` 限流即 `note_rate_limit`；读入口 `require_rest_or_transient`；预算 **40/min** → 180s cool |
| WS 限流根因 | **已绝**：`_radar_ws_fast_tick` 零 REST；哨兵 20–45s；缓存 TTL 15/25s |
| `TP_FILLED` / `TRAIL` | 纳入通讯官：`TP_FILLED` 仅持仓相位；`BREATH_TRAIL`/`TRAIL` **90s** 节流 |
| 雷达公式影子 | **已禁用** — 无 live/watched 则 `RADAR_RESIZE_SKIPPED` 拒挂，不发明数量 |

### 生产代码锚点

| 项 | 值 |
|----|-----|
| 三方 commit | `git rev-parse --short HEAD` 本地 = GitHub `main` = VPS **肉眼同数字** |
| VPS 路径 | `/home/panda/panda-quant-platform` |
| Webhook | `https://twinstar.pro/gemini/webhook` → `:6010` |
| 交易对 | **币安 ETH+XAU**；**OKX/Gate/DeepCoin 仅 ETH**（`trading_symbols_for_exchange`；`TRADING_SYMBOLS` 仍可写 ETH,XAU，非币安自动滤掉 XAU） |
| 再入场开关 | `SMART_REENTRY_ETH_ENABLED` / `SMART_REENTRY_XAU_ENABLED`（默认 True） |
| E2E | 生产必须 `E2E_FORCE_NOTIONAL_USD=0`（烟雾后立刻还原） |
| 日亏熔断 | **`DAILY_LOSS_CIRCUIT_ENABLED=False`（生产关闭）** — 曾误熔断挡真实 TV |

### 智能再入场闭环（白皮书 v3.0 · 2026-07-25）

**理念**：策略方向已验证；执行层过早干预才是利润杀手。雷达从「主动锁利」转为「被动跟随、守护趋势」。入场靠评分，利润兑现靠 TP，雷达防止趋势被过早打断。

| 步骤 | 规则 |
|------|------|
| ① 归零清场 | 仓位=0 后：撤销全部限价/条件单，确认盘口空、持仓零（最多 3 轮）。失败 → TG critical，**拒挂再入限价** |
| ② 重入判断 | 仅雷达轨 + 平仓价在保本~微赚区（ETH 0.5×ATR / XAU 0.3×ATR）+ **窗口内**（ETH 2×90m / XAU 3×45m）+ 累计重入=0。硬止损/亏损 → 永不重入 |
| ③ 双保险价 | 多 `min(5m低+tick, TV×0.997)`；空 `max(5m高−tick, TV×1.003)`；须优于 TV **且** 优于上次开仓价 → 否则终止 |
| ④ 挂限价 | **先查本地标签**；标签占用 → 绝对拒挂。`newClientOrderId` 幂等。TTL 5min |
| ⑤ 成交保护 | fill 为原点：硬止损=`fill±(|TV.e−TV.SL|×**1.15**)` + **仅 TP1/TP2** 限价(10/20) + 雷达（ATR=`TV.atr`；arm=ADX 70/80/90%×1.35ATR）。TG `SMART_REENTRY_PROTECTED` |
| ⑥ 档位 | ADX 弱/中/强（0/1/2，可选 webhook `tier`）；重入成功雷达 trail +1 档（封顶 2）、arm 改为 1.00；**最多重入 1 次** |
| ⑦ 新 TV | 先清场归零，重置档位/标签/计数器，再开新方向 |

**红色硬闸（击穿实盘级）**  
| 闸 | 规则 |
|----|------|
| 本地标签 | `order_place_guard.PendingOrderRegistry`：reentry/tp/hard/radar 任一 in-flight → **禁止再挂**，盘口空也不例外 |
| 挂单硬帽 | 单品种未成交挂单总数 **≤5**（限价+止损合计）；超限 → critical + 暂停开仓 |
| 退出所有权 | `exit_ownership`=NONE/TP3_LIMIT/RADAR_STOP；先成交锁定，拒操作另一腿；竞态 → 强制对账 |
| 查单失败 | open-orders / pos 查询异常或 `None` → **fail-closed 拒挂**（禁止 `except: pass` 后盲挂） |
| 单周期单挂 | 同一品种同时只允许一笔再入场开仓限价；超时先 `release` 旧标签再新标签 |
| 延迟启动 | `_close_all` 先 **plan** 快照 → purge → **commit** 启动 worker（避免 cancel_all 误杀刚挂的再入限价） |

模块：`trend_tier_params.py` · `smart_reentry.py` · `smart_reentry_mixin.py` · `order_place_guard.py`

### 事故与修复日志（查历史优先）

| 文档 | 用途 |
|------|------|
| **`docs/SYSTEM_ISSUE_FIX_LOG.md`** | **主入口**：2026-07-26 硬帽/`-1003`/TG 风暴、基线压扁、假 TP3、暂停 REST 等；对齐币安单系 **v16.4.2-incident-harden** |
| `docs/TP_DUPLICATE_INCIDENT_20260722.md` | 重复限价止盈专项 |
| `docs/KNOWN_ISSUES.md` | 滚动已知项（非叙事对照） |

### 事故纪要 · 重复限价止盈 / 幽灵单（2026-07-23）

**现象（交易所截图）**  
- 持仓 ETH 多 + XAU 多时，基础单出现**成对 1 秒间隔**的同向限价止盈；ETH 甚至出现 **BUY 只减仓**限价（多仓正确平仓方向应为 SELL）。  
- 条件单同时可见 **两笔接近但不等的 STOP**（仅 Stage1+ 激活后：硬止损=`fill±(|TV.e−SL|×buffer)` + 雷达；**Stage0 开仓后应只有硬止损 1 笔**）。**不是**「TV 原价硬止损」或「ATR 地板+滑点垫」。  
- 仓位已归零仍残留限价/条件单 → **幽灵单**，下一笔 OPEN 前必须净场。  
- 历史极端：同一价格限价止盈可叠到约 **50 笔** → 实盘击穿风险，**灾难级**（见下方硬闸，坚决杜绝）。

**根因（已修）**  
1. `_place_limit_with_retry` / 缺失 TP 补挂：超时返回 `None` 后**盲重试**，未先验盘口是否已成交受理 → 风暴。  
2. `current_side` 为空时 `else → LONG → BUY`：多仓错挂 BUY 只减仓。  
3. 平仓净场 mop 轮次不足 / 限流下 leftover≠0 仍只告警 → 幽灵单。  
4. 雷达 `_ensure_radar_sl`：cancel→place 窗口无「盘口已有≥2 笔 STOP」硬帽。  
5. **(2026-07-25)** 再入场路径曾对 `get_open_orders` 异常 `pass` 后继续挂 → 升级为本地标签 + fail-closed。

**硬闸（必须永久保留）**  
| 闸 | 规则 |
|----|------|
| 限价幂等 | 下单前/重试前：同价已有 reduce-only LIMIT → **视为成功，禁止再挂**；盘口不可读 → **拒挂**（不得当「没有」盲挂） |
| **本地标签** | 品种+种类 in-flight 标签存在 → **绝对拒挂**（防查单失败风暴，最后一道） |
| 限价硬帽 | 盘口 reduce-only LIMIT ≥ `max(期望档数, 3)` → **拒挂 + 同价去重** |
| LIMIT≥6 熔断 | 盘口 ≥6 张 reduce-only LIMIT → **仅轻量同价去重（每价留 1），禁止再挂/核武盲补** |
| 方向 | 平仓方向优先读交易所 `positionAmt`；未知方向 → **拒挂**（永不默认 LONG→BUY） |
| 无仓拒挂 | 交易所 qty=0 → **禁止任何 TP/雷达补挂**，只走净场 |
| STOP 硬帽 | 双轨最多 **2** 笔 STOP（硬 + 雷达）；≥2 或簿记未知 → **拒挂雷达** |
| 硬止损确认 | 挂单不可读且无盘口实证 → **不得谎称已有**（本地 oid 不算证明）；开仓链路 fail-closed 撤仓 |
| 撤 TP | 查单失败 → **禁止 cancel_all**（防误撤 STOP、加剧 -1003）；只按可读清单逐笔撤 |
| 核武/重建 | 盘口不可读 → **中止撤挂与盲补**；可读时先 **轻量同价去重** 再核武 |
| 平仓净场 | mop≥5 轮 + 额外 cancel_all；leftover≠0 → TG critical + dirty 标记，开仓门禁拒绝脏盘 |

#### 开仓链路（ETH / XAU 同一套）

```
TV 入队 → 解析 → ATR=webhook.atr → RISK20×5 算仓 → 市价开
  → 永久硬止损 fill±(|TV.e−SL|×**1.15**) + TP1/TP2(10/20)（TP3 不挂限价）
  → 雷达武装(TV atr；arm=ADX 70/80/90%×1.35×ATR)
```

不可读盘口时：**禁止再挂 TP/Stop、禁止 cancel_all、禁止把未知当已保护**。

**自查口令（独立于文字汇报）**  
1. GitHub / 本地 / VPS `git rev-parse --short HEAD` 三数字一致。  
2. 币安：仓位(0) + 当前委托(0) + 条件委托(0)。  
3. 代码原样：`PLACEABLE_TP_LEVELS={1,2}`；`resolve_open_atr` 恒用 TV atr；`MAX_REENTRY=1`；`HARD_STOP_BUFFER_FIXED=1.15`。  
4. 当面最小资金 LONG：Stage0 应见 **硬止损1 + TP限价仅 TP1+TP2（无 TP3 限价、无休眠雷达）**；ADX arm 后才出现雷达 STOP；TG杠杆为该用户配置值（默认 **5×**）。

### 三层防线永久共存（核心，不得误解）

| 层 | 规则 |
|----|------|
| **① 硬止损（永久防线）** | `dist=\|TV.price−TV.stop_loss\|×**1.15**`（全品种全档位固定）。挂单=`fill±dist`。无 ATR 地板、无滑点垫。至 flat：**禁止**收紧/撤销。雷达不碰硬止损。**缺 SL 或距&lt;5 ticks → 拒开仓**。 |
| **② 雷达止损（骑士守卫）** | ATR **仅用 TV webhook `atr`**。启动阈值=`fill±(1.35×ATR×ADX比例)`：ADX&lt;20→70%、20–30→80%、&gt;30→90%（离散·弱早强晚；**不依赖 TP1 是否已成交**）。**激活瞬间→手续费保本**（entry±(1 tick + fee×0.15%)）；之后按档位步长/跟进/呼吸空间被动抬止损。**取消** entry±0.5ATR / TP1 强制底线。第二层追踪 `trailDistanceMultiplier`（ATR 比值）独立、不改。启动前仅硬止损保护。 |
| **③ TP 限价** | **仅 TP1/TP2** 挂 TV 价 **10%/20%**。**TP3（70%）永不挂限价**，完全交雷达管理（无价格天花板）。历史若曾挂过 TP3，开仓/退出路径必须撤掉遗留单。 |
| 部分平仓 | TP 成交后仓位变 90%/70%/0：硬止损与雷达止损**数量同步收缩**，价格不变。 |
| 归零清理 | 任一止损触发或全部 TP 成交 → 立即撤销其余挂单，不留孤儿单。 |

#### 开仓瞬间（规格最终修正对齐）

1. **挂硬止损**（fill ± TV距×**1.15**；永冻）— 先于一切，禁止裸奔  
2. **挂 TP1+TP2**（10/20）；若盘口仍有旧 TP3 限价 → **立刻撤掉**  
3. **用 TV atr 武装雷达参数**（不拉交易所 ATR、无场景切换）；再确认硬止损仍在。**Stage0 不额外挂雷达 STOP**——价格走到 ADX 比例后再挂。  

#### Cursor 最易犯的错误（代码已闸）

| 错误 | 正确 |
|------|------|
| 先撤硬止损再挂雷达 | 硬始终在；Stage0 不上雷达，arm 后再挂 |
| 雷达改单时同步改硬止损 | 硬只读，不触碰价格 |
| 雷达更优就撤硬 | 两笔共存直到 flat |
| recover/加仓无脑 `force_replace` 撤硬 | 仅当数量真变才 qty-resize；同量跳过 |

### 关键参数

| 项 | 现行值 |
|----|--------|
| TV action | 仅 `LONG` / `SHORT` / `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT`；**无 qty 字段** |
| 算仓 | `qty = 合约本金 × 保证金占比 × 杠杆 / 价`；默认 **20% × 5x**（≈本金×1 名义）；**管理员可按用户改**；忽略 TV qty |
| 10s 铁律 | OPEN 先到 → 10s 内 CLOSE **丢弃**；CLOSE 先到 → **先平后开**；>10s CLOSE 独立平仓 |
| 净场 | 开仓前无仓无挂单；平仓后立即撤该 symbol 全部挂单；反手一律先平 |
| ATR | **优先**交易所原生 1h；失败用 TV atr；雷达/开仓**不用** 90m 合成 |
| 呼吸 / 雷达 | 启动=ADX 70%/80%/90%×(1.35×ATR) 弱早强晚；trail 档位弱/中/强；激活→fee+tick 保本；步长/跟进见 `trend_tier_params` |
| TV 图表 | ETH **90m** / XAU **45m**（VPS「1h ATR」仅为波动率 oracle） |
| 杠杆 | 默认 `FIXED_LEVERAGE=5`；**`/admin` 用户详情可按账户改**（1–125，受交易所上限约束） |
| 加仓 | **禁用**；同向亦先平后开 |
| 重入 | 最多 **1** 次；窗口 ETH 2 根 / XAU 3 根；成功后雷达 +1 档 |

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
code_anchor: see git HEAD (anti-dup TP/stop hard gates)
deploy_status: must verify empty book + three-way hash before real TV

services:
  frontend:6080
  backend:8000
  backend:6010   # TV webhook
  redis:6379

rules:
  - hard_stop = fill ± (|TV.price−TV.stop_loss| × 1.15); NO ATR floor / slip pad
  - missing SL or distance < 5 ticks → reject open
  - TP always 10/20/70 (TP1+TP2+TP3); TP3 ↔ radar mutex
  - radar arm Layer-1 = fill ± (1.35×ATR × ADX 70/80/90); activate → fee+tick BE; Layer-2 trail = ATR-ratio trailDistanceMultiplier (unchanged)
  - max reentry = 1; window ETH 2×90m / XAU 3×45m; reentry loosens trail +1 ADX tier (arm still ADX-driven)
  - local PendingOrderRegistry tag → refuse place even if book empty (anti 50× LIMIT)
  - OPEN_ORDERS_HARD_CAP=5 → critical + pause symbol opens
  - DAILY_LOSS_CIRCUIT_ENABLED=False in prod (false trips blocked real TV)
  - REST: price/fills via WS; position reconcile ~45s; symbol REST gap ≥100ms; shared-account gap 2s; on -1003: cool **180s** + `_GLOBAL`
  - on rate-limit (any exchange): note_rate_limit in client `_request`; budget **40**/min → full 180s cool
  - WS tick: **no REST** (trail on watched_qty only); adverse/book audit ≥30s
  - SENTINEL_POLL: normal 45 / arming·radar 20; ORDER_AUDIT 30; RADAR_WS_TICK_MIN 2.0
  - book cache TTL: pos 15s / orders·algo 25s
  - sizing = equity * margin_pct * leverage / price; default 0.20×5; admin per-user override; ignore TV qty
  - admin_sizing: /admin → user detail → margin% + leverage (next open)
  - pipeline: Signal→Admission→Auditor→Execution(TP≈30% self-check)→ChiefAuditor→Comms; ledger under data/supervisor/ledgers/
  - pipeline_stall: PHASE_STALL_SEC → critical PIPELINE_STALL; mid-trade ChiefAuditor.recheck_live on TP fill
  - flat_auto_unpause: chief_auditor_fail / open_orders_gt_5 / open_book_dirty / ATR应急 / 方向 / 先平后开失败
  - REST valve: rest_throttle_valve; sentinel_may_rest blocks pause/cool/**budget**; book cache prefers stale
  - E2E_FORCE_NOTIONAL_USD=0 in production; wait real TV
  - three-way commit: local = GitHub = VPS

modules:
  sizing: backend/app/core/tv_entry_sizing.py
  ledger: backend/app/core/trade_ledger.py
  officers: backend/app/core/pipeline_officers.py
  rest_valve: backend/app/core/rest_throttle_valve.py
  trend_tiers: backend/app/core/trend_tier_params.py
  hard_sl: backend/app/core/breathing_stop.py::compute_temp_tv_stop
  open_atr: backend/app/core/open_atr_scenario.py
  radar: backend/app/core/adverse_radar_guard.py + breathing_stop.py
  reentry: backend/app/core/smart_reentry.py + smart_reentry_mixin.py
  tp: backend/app/core/tp_regime_targets.py
  place_guard: backend/app/core/order_place_guard.py
  rate_cool: backend/app/core/ip_rest_cooldown.py
  rest_pace: backend/app/core/rest_symbol_pace.py
  daily_loss: backend/app/core/daily_loss_circuit.py
  coalesce: backend/app/services/webhook_symbol_coalesce.py
  supervisor: backend/app/core/position_supervisor.py
```

### 交易所 API 限流（Binance −1003 · 白皮书 §8）

| 项 | 规则 |
|----|------|
| WS vs REST | 价格监控 / 订单成交 → **WebSocket**；下单改撤 + 持仓对账 → REST |
| 持仓对账 | REST 约 **每 45s**（`SENTINEL_POLL_NORMAL=45`）；近 TP / 雷达期 **20s**；WS tick **禁止 REST** |
| 单品种间隔 | `rest_symbol_pace`：同品种连续 REST **≥100ms**；全账户共享端点 **≥2s** |
| 共享冷静 | `ip_rest_cooldown`：ETH+XAU 共用 IP 级冷却，默认 **180s** + `_GLOBAL`；预算耗尽同冷 |
| 预算阀门 | `rest_throttle_valve`：**40 次/分钟/账户**；超限 → 立刻 180s cool，拒绝新 REST |
| 缓存 TTL | 持仓 **15s** / 挂单·algo **25s**；拒绝刷新时优先 stale |
| 触发 | REST 返回 `-1003` / 限流文案 → `note_rate_limit`；哨兵/补挂读 `remaining_sec` 跳过，禁止硬撞 |
| 盘口不可读 | **禁止** `cancel_all`、禁止盲补 TP/Stop（防误撤 STOP + 加剧限流） |
| TG | 限流抖动去重，避免刷屏 |
| 烟雾注意 | 双品种连续开平会逼近权重；脚本内已插 sleep；限流中途失败 → 等冷却再净场，勿循环重试 |

### 日亏损熔断（生产关闭）

| 项 | 现行 |
|----|------|
| 开关 | `DAILY_LOSS_CIRCUIT_ENABLED=False`（`Settings` / `.env`；模块默认亦 False） |
| 设计意图 | UTC 日累计已实现亏损 ≥ equity×5.5% → 暂停该品种开仓 |
| 为何关 | 实盘曾因 PnL 归属/过小 `equity_ref` **误熔断**，挡住真实 TV 开仓 |
| 运维 | 勿在未审计记账前重新打开；误触发残留可用 `clear_user_symbol` / `_vps_clear_daily_loss.sh` 清文件 |
| 与「挂单硬帽暂停」区别 | 硬帽≤5 超限 → **仍会** critical + 暂停开仓（防 50 笔风暴）；日亏熔断是另一条且当前旁路 |


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
10. [TG 通知策略](#tg-通知策略)
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
        ├─ LONG/SHORT → 先平后开 → RISK20 算仓 → 开仓 → TP1/2/3(10/20/70) + 硬/雷达
        ├─ CLOSE_QUICK/RSI → 反转保护全平
        ├─ 引擎 tick → 90m ATR/ADX → 呼吸改止损价 / 触及全平
        └─ 未登记实盘仓 → 市价 ATR 接管（不编造 TV 历史）
        │
        ▼
trade_logs + TG关键摘要（执行快照杠杆 5× · 按交易所主题）
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

> **杠杆 / 仓位权重：** 默认 `FIXED_LEVERAGE=5` + `margin_pct=0.20`（`tv_entry_sizing`）。管理员可在 `/admin` 用户详情覆盖；Dispatcher 注入 `margin_pct_frac` / `entry_leverage`，开仓 `_resolve_entry_leverage` / `_resolve_entry_margin_pct` 读取。

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
│   │   ├── tv_entry_sizing.py               # ★ default 20%×5x; admin per-user override
│   │   ├── breathing_stop.py                # ★ 呼吸止损 + 市价 TP 阶梯
│   │   ├── adverse_radar_guard.py           # ★ 止损挂/改/触发 + TP后数量收缩
│   │   ├── market_engine.py / market_indicators.py
│   │   ├── tp_regime_targets.py             # PLACEABLE_TP_LEVELS={1,2} · 10/20 + TP3雷达
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
├── _push_github.sh                           # ★ 本地推送前自检（含 TV webhook 连通性）
├── deploy.sh                                # ★ VPS 一键部署
├── production_check.sh                       # ★ VPS 部署后全域自检
├── scripts/
│   ├── deploy_lib.sh                        # 部署公共函数
│   ├── selfcheck.sh                         # ★ VPS 快速巡检（TV webhook + 网络连通性）
│   ├── deploy_local.sh                      # ★ VPS 本地快速部署（git pull + 重启）
│   └── check_system.py                      # 后端 Python 全域自检
├── frontend/  deploy/  docker-compose.yml
└── backend/
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
| 杠杆 | 默认 **`FIXED_LEVERAGE=5`**；管理员可在 `/admin` 按用户覆盖（`UserTradingState.margin_pct_frac` + `leverage`） |
| 加仓路径 | 返回 `add_disabled` / qty=0 |
| 开仓日志 | 记录 `notional_target`、`binding=margin{N}_lev{L}`、`atr_source=tv_webhook` |
| TV `qty`/`qty1-3` | **完全忽略**（可缺省；不参与算仓/TP 数量） |
| 管理员改仓 | `/admin` 用户详情：「下单权重 · 杠杆」；保存后热更新 supervisor，**下次开仓**生效 |

### 四、开仓后挂单

| 订单 | 行为 |
|------|------|
| TP1 | 限价；数量=实盘总仓 **10%**；价格=`tp1` |
| TP2 | 限价；数量=实盘总仓 **20%**；价格=`tp2` |
| TP3 | 限价；数量=实盘总仓 **70%**；价格=`tp3`；与雷达并行互斥 |
| 硬止损 | `fill±(|TV.price−TV.stop_loss|×buffer)`；永冻 |
| 雷达止损 | ATR 武装后额外 STOP；不改硬 |

~20U 烟雾：TP1/TP2 常因交易所最小名义失败；引擎会把不足 `min_tp_notional`（默认 5U）的档位折入后续档（通常 TP3），保证至少一笔可挂限价。满仓资金下仍为完整 10/20/70 三档。

### 五、TP 成交后（订单监控 → 引擎）

1. 确认成交，更新 `remainingQtyPct`（TP1→**90%**，TP2→**70%**）  
2. **通知**呼吸引擎：按剩余数量 + 当前 `currentStop` 重挂硬/雷达数量（价格不变）  
3. **不**因 5 分钟超时误撤「现价未到」的健康 TP；rebuild 前检查盘口是否已有匹配单  
4. TG：成交价、剩余比例、当前止损  

### 六、已删除 / 禁止的行为

完整清单见 [docs/LEGACY_PURGE_LIST_20260722.md](docs/LEGACY_PURGE_LIST_20260722.md)。

| 类别 | 删除项 |
|------|--------|
| 算仓 | 用 TV.qty / 止损距反推仓位当权威 |
| 止盈 | 旧「TP3 挂限价/与雷达互斥」、VPS 拉 ATR 场景切换（已反转为：TP3 永不挂限价、ATR 仅 TV） |
| 硬止损 | ATR 地板 + 滑点垫公式 |
| 旧雷达 | `activated`、0.85×TP1 激活、0.5/0.3 步进、固定 2.0×ATR 挂单价 |
| 加仓 | PYRAMID / PROFIT_ADD / 加权均价重挂 |
| 自主平仓 | `CAP_ALIGN` 市价减仓（detect-only） |
| Webhook | `CLOSE_TP` / `CLOSE_TRAIL` / `CLOSE_SL_*` / `CLOSE_PROTECT` / `leg` |
| 日亏熔断 | 生产默认开启（现强制关闭至记账审计完成） |
| TG杠杆 | 独立于执行层的第二配置源（曾显示 25×） |

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
| `qty1` / `qty2` / `qty3` | **忽略**（TP 数量由 10/20/70 算） | **否** |
| TV `stop_loss` | 与 `price` 算硬止损距；**缺则拒开仓** | 距×buffer 挂于 fill |
| `tp1` / `tp2` / `tp3` | TP 限价价格（数量固定 10/20/70） | **否** |
| `tp3` | **挂限价**（70%）；与雷达互斥 | **否** |
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

开仓时：TV `atr` → 冻结 `initialAtr` → 呼吸阶梯基准 `initialStop = entry ± 1.5×initialAtr`（**非**交易所硬止损挂单价）。  
**硬止损挂单** = `fill ± (|TV.price−TV.stop_loss| × buffer)`（默认 1.2；无 ATR 地板 / 无滑点垫）。  
运行中：`ratio = atr_1h / initialAtr` → SMA(3) → **连续线性插值** `trailDistanceMultiplier`（非离散档）。

| 参数 | ETH | XAU |
|------|-----|-----|
| coef 区间 (minMult~maxMult) | 1.2 ~ 2.5 | 1.2 ~ 2.5（再入场档位覆写） |
| 冷启动（ratio=1.0） | **1.525** | **1.525** |
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

阶段一阶梯 / 手续费保本激活 **只用锁定 `initialAtr`（激活本身用 fee+tick）**，不含呼吸系数。

```
激活保本: 触及 ADX 启动线 → 止损抬到 entry±(1 tick + entry×FEE_BUFFER)   # 马拉松；非 0.5ATR
雷达启动: ADX<20→70%早 · 20–30→80% · >30→90%晚 × (1.35×initialAtr)；与 TP1 成交无关
追踪 coef: Layer-2 ATR比值插值（ETH 2.0~2.5 中档 / XAU 1.8~2.2；floor/ceil 0.6/2.2）
step_count = floor(max(0, |price−entry| − arm_dist) / (step_trigger × initialAtr))
step_stop  = fee_BE ± step_count × step_advance × initialAtr
candidate  = max/min(currentStop, step_stop, fee_BE, trail)   # 只朝盈利（激活后）

# 已取消：TP1/TP2 强制 ATR 底线（旧 entry±0.5 / ±1.5ATR）
若浮盈 ≥ 3.0×ATR → phase2 连续 trail（trailDistanceMultiplier）
```

### 阶段二（自适应追踪）

```
trail_dist = initialAtr × trailDistanceMultiplier(smoothedRatio)   # = coef；无额外 tighten
currentStop = max/min(currentStop, extreme ∓ trail_dist)
```

新止损价必须**严格优于**当前止损才改单，避免无意义频繁撤挂。

### 触发与失败兜底

- 价格触及 `currentStop` → 市价全平 → 统一状态清零 → TG（标明阶段一/二 + `[ETH]`/`[XAU]`）  
- TP1/TP2 成交 → 通知引擎按 90%/70% **重挂数量**（价格仍用当前 `currentStop`）  
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

## TG 通知策略（仅 Telegram · DingTalk 已清除）

配置：`.env` `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`。动作级去重，避免刷屏。TG = 全部业务事件（排除过噪内部类型）；critical/异常走 TG 告警级别。

### ADX 趋势档位（TV 新增 · 文案必带）

TV 入场时按 ADX 分三档（可选 webhook `tier`=0/1/2；缺省 VPS 用 ADX / 止损距反推），**TG 关键告警须带品种标签 + 当前档位**：

| 档位 | ADX | 含义 | 通知影响 |
|------|-----|------|----------|
| 0 弱趋势 | &lt;20 | 震荡，雷达步长/跟进收紧 | 文案 `档位·弱趋势`；**禁止**雷达扫出后重入 |
| 1 中趋势 | 20–30 | 标准参数 | 文案 `档位·中趋势`；禁止重入 |
| 2 强趋势 | &gt;30 | 雷达放宽 | 文案 `档位·强趋势`；允许最多 1 次限价重入 |

硬止损呼吸垫全档位固定 **1.15**（不分档）。图例函数：`format_trend_tier_intro()` / `format_breathing_legend()`。

### 执行快照原则（本轮根治）

| 字段 | 来源 |
|------|------|
| 杠杆 | `_alert` **强制**写入 `_resolve_entry_leverage()` → 用户配置或默认 5×；theme 种子亦对齐 |
| 方向 / 数量 / 入场 / 止损 | supervisor 本笔状态（缺省时由 `_alert` 注入） |
| **档位** | `_alert` 注入 `trend_tier` + `tier_label`（弱/中/强）；开仓 detail 同步写入 |
| 平仓归因 | `close_attribution`：证据不足就承认不足；maker≠TP 价不判止盈；查询失败不报「已空仓」 |

### 事件清单（现行）

| 事件 | 内容要点 |
|------|----------|
| 开仓 | 品种、方向、价格、数量、**当前档位**、硬止损、`TP1/TP2`、权益、杠杆 |
| 雷达激活 | 首次/重入、阈值、触发价、止损上移、**档位** |
| 止损移动 / 阶段切换 | 新止损、极值、浮盈%、**档位** |
| 先平后开 | 检测到已有持仓，已市价全平并撤单，准备执行新开仓 |
| 未登记接管 | **「未登记来源仓位·系统接管（来源待核实）」** — 不编造 TV 关联 |
| TP1/TP2 成交 | 成交价、剩余 90%/70%、当前止损、**档位** |
| 止损触发 / 全平 | 触发价、来源、盈亏、**档位** |
| 重入尝试/成交/放弃 | 原因、价格、窗口、**档位**（仅强趋势可尝试） |
| 反转保护 | `CLOSE_QUICK_EXIT` / `CLOSE_RSI_EXIT` |
| 查询失败 | `EXCHANGE_QUERY_FAIL` / 恢复后 `EXCHANGE_QUERY_OK` |
| 重启 / FORCE_ALIGN | 恢复详情或方向不一致已全平（含档位） |
| 异常 | 改单失败、对账不一致、挂单超时、`CAP_ALIGN` 仅告警等 |

### 已删除文案

「极限逃顶/逃底」「风控拦截」「TP3限价止盈成交」（余仓由雷达追踪）、「加仓成交」「首仓」「中势推升」、旧 **R1/R2/R3 regime 档位** 标题等。

主题标签仍按交易所+品种区分（`#双子星·币安5x·ETH` / `#OKX5x·XAU` 等）。

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
2. 读持久化呼吸状态；**旧 schema**（`activated`/`stepCount` 且无 `initialAtr`）→ TG告警 + **暂停**该 symbol  
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
- **按用户下单权重**：用户详情可改 **保证金占权益 %**（1–100）与 **杠杆**（1–125）；默认 20% × 5x；按 UID / 昵称 / 交易所 / 脱敏 API Key 区分账户；保存后立即对**下次开仓**生效（已持仓不变）  
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
# 推送后 VPS ssh 进入，执行以下两行：
cd /home/panda/panda-quant-platform

# 方式一：完整部署（含代码拉取 + 构建 + 自检，推荐）
bash scripts/deploy_local.sh

# 方式二：快速拉取 + 重启（仅代码已对齐时）
git pull origin main
docker compose build backend && docker compose up -d backend

# 部署后快速巡检
bash scripts/selfcheck.sh

# 完整自检
bash production_check.sh
```

HTTPS：`sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh`  
Nginx：`/gemini/webhook` → `127.0.0.1:6010`；`/` → `6080`。仅开放 80/443。

> **生产已验收通过后**：避免无必要 rebuild 即可（`-1003` 风险仍在）。见 [docs/OBSERVATION_WINDOW_20260722.md](docs/OBSERVATION_WINDOW_20260722.md)。

---

## 运维自检与故障排查

```bash
# 快速巡检（推荐，每次部署后执行）
bash scripts/selfcheck.sh

# 完整全域自检
bash production_check.sh

# TV Webhook 端到端检查（生产最关键）
curl -sf https://twinstar.pro/gemini/webhook/health
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://twinstar.pro/gemini/webhook \
  -H "Content-Type: application/json" \
  -d '{"action":"LONG"}'

# VPS 本地快速部署（推送后执行）
bash scripts/deploy_local.sh

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
- [x] TG杠杆恒为 **5×**；未登记仓位文案诚实  
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
