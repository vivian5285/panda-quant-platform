# Gemini 阶段排查进展（2026-07-22 17:20 CST）

> 对应汇总清单；**不推送 GitHub**（按指令）。

## 1. 杠杆显示：治标还是根治？

（结论不变：治标；详见上一版。）

## 1b. IP ban（2026-07-22）

| 项 | 结论 |
|----|------|
| 原因 | 后端 **rebuild 启动风暴**：多用户×双 symbol 连续 REST（position/orders/trades/klines），触发币安 `-1003 Way too many requests` |
| 解封 | **自动解封**，无需人工；日志 `banned until 1784711514057` ≈ **09:11:54 UTC**（启动后约 5 分钟） |
| 现状 | 09:26 UTC 探测：`fapi ping OK`，ban 已过期（left_s 为负） |
| 影响 | ban 期间任何仓位观察/对账 **不可信**；且旧 `get_position→None` 会误当空仓 |

## 1c. get_position 失败误判空仓（本轮已修）

原则：API 失败 **绝不**当空仓；保留账本；钉钉 `EXCHANGE_QUERY_FAIL`；暂停该 symbol 自动空仓判断；查询恢复后 `EXCHANGE_QUERY_OK`。

覆盖：Binance/OKX/Gate/DeepCoin 客户端 + supervisor startup flat reconcile + sentinel。

## 6. 归因四项（本轮已修 + 单测）

见 `test_attribution_evidence_gates.py` / `test_position_query_fail_safe.py`。

**观察纪律：** 本批代码一次性部署后，B1–B3 观察期 **禁止 rebuild**，直至窗口结束。

### 明确回答

**混合，尚未根治。**

| 路径 | 数据源 | 现状 |
|------|--------|------|
| 开仓钉钉正文 / `detail["leverage"]` / 标题里的 `档位·N×` | **执行上下文**：`_resolve_entry_leverage()` → `FIXED_LEVERAGE=5`，写入 `detail` 再 `resolve_exchange_theme(..., leverage=detail.leverage)` | 与真实下单杠杆一致 |
| 钉钉头部 `#币安Nx` / `· N×`（`theme['leverage']`） | **优先** `detail.leverage`；**缺失时**回落 `exchange_leverage()`（现硬编码 `FIXED_LEVERAGE`） | 缺 detail 时仍是「独立主题层」，只是默认被钉死成 5 |
| `BinanceClient.trading_leverage` 初始值 | `settings.LEVERAGE`（env，可与 FIXED 脱节） | 开仓前靠 `_bind_tv_leverage` 纠正；工厂日志 `@ 5x` 来自 `exchange_leverage` |

结论：与「钉钉档位仍显示 R3」**同类架构问题**——播报主题层有独立 fallback，不是「永远只读本笔执行快照」。本次把 fallback 改成 5 / 硬编码 FIXED，是**治标**；真正根治应让主题层禁止静默 fallback，或强制从 supervisor 快照取值。

### 建议改造（评估，未改代码）

1. `push_trading_alert`：无 `detail.leverage` 时 **不**调用 `exchange_leverage`，改为省略杠杆或标 `—`，并打 warning  
2. 或：所有 `_alert` 统一注入 `detail` 快照字段：`leverage / regime / risk_pct / sizing_mode / symbol / side / qty / entry / current_sl`  
3. 开仓文案去掉误导性「TV杠杆」（实为 FIXED 5×）

### 钉钉双数据源字段排查（同类风险）

| 字段 | 播报侧 | 执行侧 | 风险 |
|------|--------|--------|------|
| **leverage** | theme ← detail 或 `exchange_leverage()` | `FIXED_LEVERAGE` / `self.leverage` | **已出过事故**；fallback 仍独立 |
| **regime / 档位** | 标题用 `self.regime`；通用明细 `detail.regime`→`R{n}`；缺省时主题不带档位 | `self.regime`（信号写入） | 若某告警未传 regime，用户只看旧标题/缓存会误解；CAP 文案用 detail.regime，一般来自执行 |
| **symbol** | theme 由 registry + detail.symbol 生成原生符号 | `self.symbol` / canonical | 低：缺 symbol 时退回主题默认 ETH 合约名 |
| **qty / entry / stop** | 妈妈版正文读 detail | 执行写入 detail | 低（有 detail 时同源） |
| **risk / 权益** | `equity`/`sizing_base` 来自 detail | 开仓 sizing_meta | 低 |
| **平仓原因** | `format_close_detail_cn` / attribution | `diagnose_flat_close` | **见 §6**；文案层可能把任意 `reason` 说成「反转保护」 |
| **Client 初始 leverage** | — | `settings.LEVERAGE` | 与 FIXED 可脱节，直到 bind |

---

## 3. TP 重复观察（B1）

| 项 | 结果 |
|----|------|
| 修复后早期窗口 | 此前热更后约 **~25min** 盘口保持 2LIMIT+1STOP，未见核武重挂（会话记录） |
| 满 30–60min 连续窗 | **未闭环**：随后多次 rebuild（git sync / 5×热更）清空了 docker 日志连续性 |
| 当前 12h 容器日志 | `核武=0`，但容器自 **09:07 UTC** 才启动；此前证据不在现日志内 |
| cancel_algo / place_stop | 现日志无法统计有效次数（启动后大量 `-1003` IP ban，REST 失败） |

**结论：B1 不能判通过。** 仓位已平，无法在同一仓上续观察。

---

## 4. 真实资金生命周期（B2/B3）

| 项 | 结果 |
|----|------|
| User6 ETH 状态 | **已空仓**：`watched_qty=0`，`monitoring=false`，`leverage=5`（state） |
| 是否捕获 TP/止损/反转 | **否** — 现容器日志无 `TP_FILLED` / `CLOSE_` / `0.033` / `breathing_stop` |
| 启动时 | `flat reconcile: book had 0.0 None, exchange flat`；同时大量 `get position/orders/trades failed: -1003` IP ban |
| 完整时间线 | **无法提供**（旧容器日志随 recreate 丢失；成交查询被 ban） |

**结论：B2/B3 未完成。** 需等下一笔自然仓位；期间应避免无必要 rebuild，并处理 Binance IP ban（否则重启对账/归因不可靠）。

注意：`get_position()` 失败返回 `None` 会被当成空仓进入 flat reconcile——若本地账本仍有仓而 REST 被 ban，存在**误清状态**风险（本次日志显示本地已是 0.0 None，更像仓已先平，但仍属架构隐患）。

---

## 6. Gemini 平仓归因 review（中）

文件：`backend/app/core/close_attribution.py` + `close_alert_utils.py` / `format_close_detail_cn`

### 偏「无依据却确定性」的点

1. **`format_close_detail_cn`**：`if "QUICK" in action or "RSI" in action or reason:` — 只要有任意 `reason` 字符串就输出「反转保护平仓」，即使实际是止损/扫尾。  
2. **全为 maker 的成交** → 直接 `exchange_limit_tp`「限价挂单成交」，**未要求**匹配 TP 价。  
3. **`peak_hit_tp3 and radar_active`** → 直接 TP3 雷达收网标题，不要求成交价近 TP3。  
4. **接近开仓价 + 雷达未激活** → `manual_exchange`（文案有「疑为」，但 `close_origin` 已落成确定性枚举）。  
5. **`had_position_before_close=True` 默认分支** → `platform_market`，可能掩盖交易所先平、平台后发现的情况。  
6. **startup flat + 成交拉取失败**（如本次 -1003）→ 易落到 `exchange_already_flat` / unknown，证据不足却仍推钉钉。

### 相对谨慎之处

- 多处 human_reason 含「疑为」；`anomaly` 标记 unknown / already_flat  
- TP 价匹配有自适应 tol；stop 与 TP1 冲突时优先 stop 分支  

### 建议（未改代码）

- 钉钉标题区分 **确证 / 推断 / 证据不足**  
- 修正 `format_close_detail_cn` 的 `or reason` 过宽分支  
- maker-only 不得升格为 TP，除非价匹配  
- REST 失败时禁止「交易所已空」强结论，应 pause + 告警  

---

## 优先级表更新

| # | 事项 | 状态 |
|---|------|------|
| 1 | 杠杆架构 | **已回答：治标；建议根治双源** |
| 2 | DeepCoin TP 缺口 | 已修复（不跟进） |
| 3 | TP 重复观察 B1 | **未满窗；仓已平；现日志无核武** |
| 4 | 生命周期 B2/B3 | **未捕获；等下一笔** |
| 5 | OKX/Gate 测试网 | 搁置 |
| 6 | 归因 review | **已完成代码审查；有过宽断言** |

**不推送 GitHub。**
