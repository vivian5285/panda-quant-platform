# 计数/清场乐观继续 · 污染窗口评估（2026-07-23）

与「阶段一固定倍数」同类：验证记录可能因**系统 bug**显得正常，需降级采信。

## 三个问题的存在时间窗口

| # | 问题 | 引入/放大锚点 | 实质性修复 |
|---|---|---|---|
| A | 开仓前清场用**过滤计数**，幽灵 LIMIT 可带入开仓 | 先平后开/`_ensure_book_clean_before_open` 起（约 `8f1dd6d`/`aa18eab` 起）+ `get_open_orders` 失败当空簿 | 2026-07-23：raw leftover 硬门 + `BookFetchError` fail-closed |
| B | 呼吸 STOP **同价叠单**（档位过滤漏数 + 空簿乐观下单） | 合并呼吸止损 `383bcbe` 起；连续版 `aab2e41` 后 tick 更频；TP resize thrash 放大 | 2026-07-23：全量 STOP 计数 + 未知拒挂 + 客户端空簿失败抛错 |
| C | TP **同价补挂风暴** | 哨兵 heal/nuclear 家族；`TP_DUPLICATE_INCIDENT_20260722` 已证实；`2a64d61` 仅堵超时环，`_place_all_defense_orders`/patch 仍缺硬 max-1 | 2026-07-23：同价已存在跳过 + 撤后校验 + 重复不核武 + book_unknown 跳过对齐 |

**共同根因（贯穿 A/B/C）**：`BinanceClient.get_open_orders` / algo list **失败返回 `[]`**，上层「空=干净」全部变成乐观继续。该行为至少自 REST book cache（`786f0e7`）起即存在。

## 哪些历史验证可能受干扰

### 高干扰（多次开平仓 / 持仓中对账）

| 记录 | 为何降级 |
|---|---|
| 本次连续呼吸**第一轮**实盘观察（cancel↔rehang → -1003） | 直接撞上 B；平仓后幽灵 LIMIT = A |
| `docs/TP_DUPLICATE_INCIDENT_20260722.md` 及前后 ETH/XAU 持仓观察 | C 已坐实；叠单期间的「防线齐全」日志不可信 |
| `docs/FULL_SCENARIO_LIVE_TEST_20260722.md` / `E2E_*_20260722` 开↔平循环 | A：平后开可能带幽灵单；B/C：持仓窗内对账可能叠单 |
| `docs/OBSERVATION_WINDOW_20260722.md` / ATR breath part2 持仓采样 | 若中途有 API 毛刺/ban，B 会在「看起来止损还在」时叠单 |
| 任何「先平后开 / force_flat / restart reconcile」后立即开仓的脚本结果 | A：过滤干净 ≠ raw 干净 |

### 低干扰（可保留）

| 记录 | 为何仍可用 |
|---|---|
| Test2 连续 vs 离散**历史回测**（无交易所簿） | 不走挂单计数 |
| Test3/4 **进程内隔离断言** | 不依赖真实 openOrders |
| 冷启动 coef 公式单测 / XAU minmax 敏感性 | 纯计算 |
| 本次 v2 观察（6 采样 + `FLATTEN_CLEAN_OK` + raw=0） | 在热更门禁之后；仍建议再用 fail-closed 客户端重跑一轮持仓观察作金标 |

### 与「阶段一固定倍数」的类比

- 固定倍数：持仓观察 coef **卡死 0.85** → 那批「呼吸正常」无效。  
- 本三问题：持仓/循环观察可能 **仓位对、挂单脏** 或 **同价 N 张仍显示 aligned** → 涉及「盘口干净 / 止损唯一 / TP 唯一」的验收需重做或降级。

## 建议重做（金标）

1. 部署本 commit 后：空仓 raw=0 预检 → 双币最小仓 → ≥5 采样 → 平仓 leftover∈{0}（禁止 -1）。  
2. 人为注入：假 LIMT 残留时开仓必须 `OPEN_BOOK_DIRTY`；故意断 openOrders 时不得新挂 STOP/TP。  
3. 旧 E2E/情景报告在 README/验收表标注 **「挂单唯一性结论作废，仅仓位/信号路径可参考」**。
