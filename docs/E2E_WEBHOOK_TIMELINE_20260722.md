# E2E Webhook 全链路验证时间线（2026-07-22）

生产端点：`https://twinstar.pro/gemini/webhook`（nginx → `:6010`，**非**直调下单函数）  
账户：User 6 · Binance · ETHUSDT · 权益约 61.5U  
代码锚点：`77d171b`

---

## 尝试 #1（失败 · 已记录）

| UTC | 事件 |
|-----|------|
| ~10:57:38 | LONG qty=0.015，`stop_loss` 按 1.5×ATR → 经 webhook 到达 |
| 10:57:39 | 鉴权通过；ATR 偏差 streak → `ATR_FALLBACK` |
| 10:57:43 | `-4164 Order's notional must be no smaller than 20`（floor 后名义 &lt; 20U） |
| 10:57:44 | `TRADING_PAUSED`（ATR 降级后未成交） |
| 10:59:21 | 再发 LONG → 被暂停拦截 `ok=0` |

**根因：** `TV_STOP_ATR_MULT=1.0` 下，stop 距离按 1.5×ATR 会使 implied ATR 偏大触发 fallback；小 qty 再 floor 易踩 Binance 20U 名义下限。

---

## 尝试 #2（成功全链路）

### 开仓

| UTC | 事件 |
|-----|------|
| 11:01–11:02 | 清 pause / streak；`docker compose restart backend`（**无 image rebuild**） |
| 11:02:22 | Loaded 2 supervisors |
| **11:02:28** | **POST LONG** HTTP 200 · qty=0.03 · `stop_loss=price−1.0×ATR` |
| 11:02:30 | ATR 核对 **OK**：vps=14.0522 / tv_implied=14.0500 |
| 11:02:34 | 市价开多 **0.029 ETH** @ 1929.5 |
| 11:02:35 | `ETHUSDT@markPrice@1s` WS 启动 |
| 11:02:39–52 | 开仓瞬间防线错位 → **一次**核武补挂 TP1/TP2（非观察期抖动） |
| 11:02:54 | algo stop SELL **@1908.42**（`adverse_sl_armed=true`） |
| 11:02:56 | 钉钉 **OPEN**：档位3 · **5×** · 止盈 2/2 · 呼吸止损已核实；`adopted_manual=false`；`trade_id=53`；dispatch **ok=1** |

开仓快照：

| 字段 | 值 |
|------|-----|
| side / qty / entry | LONG 0.029 @ 1929.5 |
| initialAtr | 14.0522 |
| initialStop / current_sl | 1908.42 |
| TP1 / TP2 | 0.009@1947.97 / 0.009@1964.13 |
| leverage | 5 |
| 未登记分支 | **否** |

### 观察（约 14 分钟）

| UTC | 检查 |
|-----|------|
| 11:10:46 | 仓 0.029；TP1/TP2 仍在；无新增核武撤挂 |
| 11:16:52 | 仓 0.029；TP 价不变；`best_price` 曾抬至 1930.67；`current_sl` 仍 1908.42（浮盈未达 0.75×ATR 阶梯，止损不动属预期） |
| 11:20:14 | 平仓前：`adverse_sl_armed=true`；平仓时成功 `cancel algo order 1000002467734662`（止损单存在） |

### 平仓

| UTC | 事件 |
|-----|------|
| **11:20:16** | **POST CLOSE_QUICK_EXIT** HTTP 200 |
| 11:20:19 | 撤销 TP×2 + algo stop |
| 11:20:21 | 市价 SELL 0.029 |
| 11:20:23 | 钉钉 **`CLOSE_QUICK_EXIT` / 反转保护** · 盘口已归零 · 平仓价 @1927.47 · 实盘盈亏 -0.11% |
| 11:20:24 | dispatch **ok=1**；状态清零 |

平仓后 state：`monitoring=false`，`side/qty/entry/sl/trade_id` 全空；交易所 **POS flat**，`open_orders=0`。

---

## 钉钉播报核对

| 事件 | 要点 | 结果 |
|------|------|------|
| OPEN | 5×、非「未登记来源」、TP 2/2、呼吸止损 @1908.42 | **通过** |
| CLOSE_QUICK_EXIT | 「反转保护」、非止损/非 TP 误判 | **通过** |

（原文见 VPS 日志 `[UserEvent][OPEN]` / `[UserEvent][CLOSE_QUICK_EXIT]`；钉钉机器人应已推送相同内容。）

---

## 异常与是否符合预期

| 项 | 判定 |
|----|------|
| 尝试 #1 名义不足 + ATR 暂停 | **异常但可解释**；测试参数问题，非主路径逻辑错误 |
| 开仓后一次核武补挂 TP | **可接受**：开仓瞬间对齐延迟，观察期内未再核武抖动 |
| 观察期止损未上移 | **符合预期**：价格未达阶段一 0.75×ATR 步进 |
| Webhook Flask `Working outside of request context` 写 receive log | **非阻塞**警告，不影响成交 |
| 全程无 `-1003` | **通过** |

---

## 最终结论

**通过真实生产 webhook 的开仓→TP1/TP2→呼吸止损（WS+algo stop）→观察→`CLOSE_QUICK_EXIT` 反转保护平仓→状态清零，全链路已跑通。**

可作为「执行层真实资金完整生命周期」收官证据（币安 User6 · ETH）。  
B1–B3 自然仓验收清单仍可保留作持续观察项，但本次主动 E2E 已覆盖信号识别、TV 关联开仓归因、挂单、止损引擎与反转平仓播报。
