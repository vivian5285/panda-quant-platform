# 系统事故与修复对照日志

> **权威入口**：查历史事故、限流螺旋、挂单硬帽、基线压扁、假 TP3 drift 时**优先读本文件**。  
> 规格正文仍以 `docs/VPS_SYSTEM_SPEC_GEMINI_MULTIUSER.md` 为准；本文件只记「现象 → 根因 → 修复 → 复查点」。  
> 对齐标签：**v16.4.2-incident-harden**（币安单系已上 VPS；Gemini 多用户同洞同修）。

---

## 索引

| 日期 | 标签 | 一句话 | 状态 |
|------|------|--------|------|
| 2026-07-27 | `pipeline-ledger-v1` | 统一 TradeLedger+岗位流水线+督察+REST阀门（全交易所） | 已修 · §9 |
| 2026-07-26 | `open_orders_gt_5` + `-1003` + TG 风暴 | 雷达 thrash + stale book + 暂停重复告警 → 硬帽熔断刷屏 | 已修 · 对照下方 §1 |
| 2026-07-26 | `initial_qty` 压扁 | 监控中把开仓基线压成余仓 → TP 对账错乱 | 已修 · §2 |
| 2026-07-26 | IP REST 冷却 / `_GLOBAL` | `-1003` 后哨兵/巡检继续打 REST；ETH/XAU 未同停 | 已修 · §3 |
| 2026-07-26 | 假 TP3 drift | 限价档对账把 mark 穿过 TV tp3 记成 consumed=3 | 已修 · §4 |
| 2026-07-26 | 暂停/冷却仍 REST | 哨兵与空闲巡检在 pause/cool 下仍查仓 | 已修 · §5 |
| 2026-07-26/27 | 雷达 qty 贴合 / TP2→TP3 护利 | 无 TP3 限价时雷达价对但量不对；双 TP 同成交漏缩量 | 已修 · §6 |
| 2026-07-26 | TP2 吃光雷达余仓 → ~1904 全平 | 排除 TP3 后切片把 70% 塞进 TP2；假 TP 成交 + 雷达抬止损扫出 | 已修 · §7 |
| 2026-07-27 | 全交易所 harden 对齐 | DeepCoin 平行监督器缺 TP/基线/雷达 qty/cool；OKX/Gate 限流指纹偏窄 | 已修 · §8 |

---

## 今日实盘问题文字总览（2026-07-26 · 币安单系 + Gemini 对照）

按时间线/因果，今天一共暴露并处理了这些问题：

1. **挂单硬帽熔断 + Telegram 风暴**  
   ETH（用户 6）反复告警 `open_orders_gt_5` /「交易已暂停」。雷达 cancel↔place thrash 瞬间挂单>5；暂停后仍每 tick 重复 `_alert`，TG 去重窗被冲破刷屏。

2. **Binance `-1003` IP 限流螺旋**  
   硬帽/对账在限流后仍 invalidate 缓存、force_refresh、哨兵继续 REST → stale book 假「>5」+ 全站 2400/min 打穿。ETH/XAU 未共享足够长的全局冷却。

3. **空仓后 state 仍暂停**  
   实盘已 flat、挂单≈0，账本仍 `trading_paused=true`，需人工清 pause + 重启止血。

4. **开仓基线 `initial_qty` 被压扁**  
   部分 TP 后把基线写成余仓 → 后续 TP 比例/consumed 全错。要求监控中基线只升不降，缩量只记 TP。

5. **假 TP3 drift**  
   价格穿过 TV 参考 tp3 时误记 `consumed` 含 3；规格是 TP3 永不挂限价，对账只按 TP1+TP2≈30%。

6. **暂停/IP 冷却时仍 REST**  
   哨兵与空闲巡检在 pause/cool 下继续查仓，加剧限流。

7. **雷达对无 TP3 余仓的责任不足（加固）**  
   价格「near」就跳过重挂，可能留下开仓满量雷达 STOP；TP1+TP2 同时成交时 `remaining_qty_pct`/resized 档位可能只记到 TP1。雷达是 TP2→TP3（约 70% 余仓）的唯一利润护栏，必须数量贴合 + 激活/追踪机智。

8. **ETH 多单 ~1904 全平、丢弃 1920+ 利润（trade 126）**  
   不是查账假空、不是重启误平。根因：排除 TP3 后切片把整仓塞进 TP1+TP2（0.011+0.02）；假 TP 成交通知（qty 未降）；雷达阶段二抬止损至 ~1904 后 `CLOSE_BREATH_STOP` 扫出。

**实盘对照快照（币安单系汇报）**：v16.4.2 已 resume；仓约 0.655（TP1+TP2 成，余仓雷达）；仅硬止损挂单；`initial_qty=0.936`，`consumed=[1,2]`。

相关旧事故（细节在各自文档，此处不重复展开）：

- `docs/TP_DUPLICATE_INCIDENT_20260722.md` — 重复限价止盈风暴  
- `docs/TV_INCIDENT_WRAP_20260722.md` / `docs/TV_FIRST_SIGNAL_FAIL_20260722.md` — TV 首单失败  
- `docs/KNOWN_ISSUES.md` — 滚动已知项（非事故叙事）

---

## §1 · 2026-07-26 · `open_orders_gt_5` + `-1003` + Telegram 风暴

### 现象

- TG 连续推送：`[ETH] 交易已暂停` / `open_orders_gt_5`（约 15:03–15:06+，用户 6 · 币安 ETH）。
- 实盘稍后已空仓、挂单≈0，但 state 仍 `trading_paused=true`，告警可因 stale book 再燃。
- 日志可见雷达 `pending_tag release … placed_ok` 约 1s 节奏 thrash；随后 Binance `-1003`（IP 2400/min）。

### 根因

1. **雷达 cancel→place 窗口**与挂单硬帽（≤5）竞态：瞬间 open orders >5 → `_pause_trading(open_orders_gt_5)`。  
2. **`_pause_trading` 非幂等**：同 reason 每个 breath tick 再 `_alert` → TG/钉钉去重窗约 20s 仍刷屏。  
3. **`-1003` 后仍 invalidate / force_refresh 盘口**：REST 打穿 → 缓存失效 → 再打；硬帽在 cool 下仍用 stale 计数「>5」。  
4. 双品种（ETH/XAU）哨兵未共享足够长的 IP 冷却（见 §3）。

### 修复（代码锚点）

| 项 | 位置 | 行为 |
|----|------|------|
| 暂停幂等 | `adverse_radar_guard._pause_trading` | 同 reason 已暂停 → **不**再 alert |
| 硬帽冷静 | `adverse_radar_guard._enforce_open_orders_hard_cap` | IP cool 中跳过硬帽重数；已 latch 不风暴 |
| REST 缓存 | `rest_book_cache` / `binance_client` / `position_supervisor` | WS 路径不盲目 invalidate；`force_refresh` 仅开仓前；single-flight + TTL |
| `-1003` 告警 | `position_supervisor` | cool 期间跳过 `EXCHANGE_QUERY_FAIL` 刷屏；mop-up 跳过 |
| 共享 pacing | `rest_symbol_pace` / `ip_rest_cooldown` | 进程内共享 cool；见 §3 |

### 复查点

- [ ] 再次硬帽：TG **只一条** `TRADING_PAUSED`，同 reason 无连发。  
- [ ] `-1003` 出现后 180s 内：日志无密集 `get_open_orders` / `positionRisk` 重试风暴。  
- [ ] 实盘空仓且挂单=0 时：state 不应长期卡在 `open_orders_gt_5`（人工清 pause 后不再被 stale 立刻拉回）。  
- [ ] 三方 commit 一致后再观察 ≥30min 无 pause 风暴。

### 当日实盘快照（对照用 · 币安单系汇报）

- 版本标签：`v16.4.2`（已 resume）  
- 仓位示例：`0.655`（TP1+TP2 已成，余仓雷达）  
- 挂单：仅硬止损（例 `@1873.18`）  
- 账本：`initial_qty=0.936`，`tp_levels_consumed=[1,2]`（基线未压扁）

---

## §2 · 禁止压扁开仓基线（`initial_qty` 只升不降）

### 现象

- 部分 TP 后 `watched_qty` 下降，若把 `initial_qty` 写成现仓，后续 `_sync_consumed_tp_levels` / 比例对账全部错位（假减仓、假加仓、假 drift）。

### 根因

- 监控路径（TV 加仓重建、人工加仓、startup restore、雷达 adopt）曾直接 `initial_qty = live_qty`。

### 修复

- 统一入口：`AdverseRadarMixin._set_open_qty_baseline(qty, reason=…)`  
  - **monitoring 且已有基线**：`qty < cur` → **拒绝压扁**，只应走 TP consumed；`qty > cur` → 上调。  
- 调用方：`binance_smart_defense` TV-add rebuild、manual_add、`position_supervisor` startup restore（保留 saved baseline，余仓缩减改 `_sync_consumed_tp_levels`）。

### 复查点

- [ ] TP1+TP2 后：`initial_qty` 仍为开仓量；`consumed`/`tp_levels_consumed` 含 1、2；余仓 ≈ 70%。  
- [ ] 日志可出现 `refuse compress initial_qty … mark TP instead`，且基线不变。  
- [ ] 单测：`backend/tests/test_open_qty_baseline.py`。

---

## §3 · IP 全局 REST 冷却 180s + `_GLOBAL` 广播

### 现象

- 单用户 `-1003` 后，另一品种（XAU）或同 IP 其他 supervisor 继续打 REST → 全站限流螺旋。

### 根因

- 冷却过短（曾 90s）或仅 user 键；ETH/XAU 不共享「全站停 REST」。

### 修复

- `ip_rest_cooldown.DEFAULT_COOL_SEC = 180`  
- `note_rate_limit` 同时写入：`user` + `ip` + `binance:_GLOBAL`  
- `remaining_sec` 取三者 max  
- 调用点：`exchange_errors.raise_exchange_transient`、`rest_book_cache`、`position_supervisor` 均 `cool_sec=180`

### 复查点

- [ ] 任意 supervisor 记一次 `-1003` 后，ETH **与** XAU 的 `remaining_sec` 均 >0。  
- [ ] 单测：`backend/tests/test_ip_rest_cooldown.py`（默认 180、GLOBAL 键）。  
- [ ] cool 窗口内哨兵仅 WS 价 + 本地 qty 呼吸，无 REST 仓位轮询（§5）。

---

## §4 · 限价档对账按 placeable 30%（禁假 TP3 drift）

### 现象

- 价格穿过 TV 参考 tp3 时，账本误记 `consumed`/`tp_levels_consumed` 含 **3**，或审计报 TP3 drift；而规格：**TP3 永不挂限价**，余仓 70% 走雷达。

### 根因

- `_sync_consumed_tp_levels` / `_infer_filled` 对 mark-past 未限制在 `PLACEABLE_TP_LEVELS={1,2}`；把参考档 3 当成交档。

### 修复

- 成交/过去档推断 **仅** `PLACEABLE_TP_LEVELS`；slice 对账按 TP1+TP2 ≈ **30%**（10%+20%）。  
- 锚点：`tp_regime_targets.PLACEABLE_TP_LEVELS`、`position_supervisor._sync_consumed_tp_levels`。

### 复查点

- [ ] 余仓约 70% 且仅硬止损+雷达时：`consumed` ⊆ `{1,2}`，**不含 3**。  
- [ ] 盘口无 TP3 LIMIT；审计无假「TP3 drift」。  
- [ ] 自查口令：`PLACEABLE_TP_LEVELS={1,2}`。

---

## §5 · 暂停 / IP 冷却时哨兵与空闲巡检停 REST

### 现象

- `trading_paused` 或 cool-down 期间 sentinel / idle patrol 仍 `get_position` → 加剧 `-1003`。

### 根因

- 哨兵主循环与 `_run_idle_live_watch` 未在 pause/cool 短路。

### 修复

- `position_supervisor._sentinel_loop`：`ban_left > 0 or trading_paused` → 仅 WS 价 + 本地 `watched_qty` 呼吸，sleep，**不** REST。  
- `startup_reconcile._run_idle_live_watch`：`trading_paused` 或 `ban_left > 0` → 直接 return（延续 v16.4.1，v16.4.2 对齐）。

### 复查点

- [ ] 人为 pause 或注入 cool：docker 日志无 idle/sentinel 仓位 REST 风暴。  
- [ ] cool 结束后哨兵恢复正常对账，无卡死。

---

## §6 · 2026-07-26/27 · 雷达数量贴合与 TP2→TP3 余仓护利

### 现象 / 风险

- 无 TP3 限价时，约 **70% 余仓**全靠雷达 STOP 护利与收尾。  
- `_ensure_radar_sl` / 呼吸 tick 仅用「价 near」判定已对齐 → 可能留下**开仓满量**雷达单。  
- TP1+TP2 几乎同时成交时，只 notify/resize 一档 → `remaining_qty_pct` 卡在 0.9、`_stop_qty_resized_levels` 缺 2。  
- 重启后若 `radar_activated=false` 但已 consumed TP → 不进入追踪相。

### 根因

- 硬止损有 `_hard_stop_live_qty`，雷达缺少对等数量审计。  
- `_boost_radar_after_tp_fill` 未先 `_sync_consumed_tp_levels`，且只 mark 单档。

### 修复

| 项 | 位置 | 行为 |
|----|------|------|
| `_radar_stop_live_qty` | `adverse_radar_guard` | 按 radar oid / 价读盘口 qty |
| qty 贴合 ensure | `binance_smart_defense._ensure_radar_sl` | near 且 qty≠live → 撤雷达重挂 |
| 呼吸 tick | `_process_breathing_stop_tick` | `need_sync` 含 qty_mismatch |
| 多档 TP | `_boost_radar_after_tp_fill` | 先 sync consumed；一次缩量；mark 1+2 |
| 重启 | `_refresh_breathing_state_on_recover` | TP 已消耗 → 强制 `radar_activated` |

### 复查点

- [ ] TP1 后：硬+雷达 STOP qty ≈ 90% 仓；TP2 后 ≈ 70%。  
- [ ] 部分成交（非整档）后数秒内雷达 qty 追上 `watched_qty`。  
- [ ] 日志可见 `TP后双轨止损数量收缩` / `雷达数量贴合`。  
- [ ] 重启持仓且 consumed=[1,2]：雷达保持激活并继续 trail（TP2→TP3 区 breath）。

---

## §7 · 2026-07-26 · TP2 吃光 70% 雷达余仓 → 1904 全平

### 现象

- Gemini ETH 多：开仓 1886.30（22:01），**平仓均价 1904.16**（00:10），+0.50U；币安单系同向持到 **1920+**。  
- 平台记录 trade#126：`CLOSE_BREATH_STOP` /「追踪止损平仓（阶段二）」；归因文案曾写「哨兵检测盘口归零·平台未发平仓单」（重启晚到账）。

### 时间线（UTC）

| 时间 | 事件 |
|------|------|
| 14:01 | OPEN 0.031 @1886.3；硬止损 ~1874.64；计划 TP1 0.011@1895.66 + **TP2 0.02@1904.63**（合计=整仓） |
| 14:43 | TP1 后余仓 0.02；雷达轨 |
| 15:02 | `RADAR_ACTIVATE` @1895.46 |
| 15:16 | **假** TP2 成交通知 `0.02→0.02`（数量未降） |
| 15:36 | **假** TP3 成交通知；呼吸止损步进至 **~1904.58** |
| 16:10:29 | `CLOSE_BREATH_STOP` 追踪止损平仓；16:10:49 flat |
| 16:30 | 新 TV LONG @1920.35（新单，非智能重入） |

### 根因

1. **`compute_tp_slices` 在 exclude TP3 后把 last placeable（TP2）写成 `qty - allocated`** → 70% 雷达份额被 TP2 限价吃光。  
2. 无减仓的假 TP 成交通知污染 `consumed` / 助推雷达相态。  
3. 雷达阶段二把 SL 抬到 ~1904 后触发真实扫出（硬止损在 1874，**不是**硬止损，**不是**查账发明空仓）。

### 修复

| 项 | 行为 |
|----|------|
| `compute_tp_slices` | **绝对比例** 10%/20%；禁止把排除档份额塞进最后一档；`live_cap` + budget；≥95% 且排除 TP3 → 拒挂 |
| `_compute_tp_slices` | 以 `initial_qty` 为锚、live 为 cap；超限打 error 并返回空 |
| `_notify_tp_fill_detected` | `old≈new` 且仍有仓 → **拒绝**假成交 |

### 复查点

- [ ] 开仓后盘口：TP1+TP2 数量和 ≤ 约 30%×initial；余仓 ≥约 70% 无对应限价。  
- [ ] 单测 `test_exclude_tp3_never_eats_radar_residual`。  
- [ ] 无 `TP_FILLED … 0.02→0.02` 类无减仓通知。  
- [ ] 雷达激活后 SL 可上移，但余仓仍在，不得因 TP2 限价吃满而在 TP2 价位必然全平。

---

## §8 · 2026-07-27 · 全交易所图表同修（OKX / Gate / DeepCoin）

### 现象

- Binance/`PositionSupervisor` 已落地 §1–§7；DeepCoin 为平行 `position_supervisor_deepcoin.py`，未继承同一套 harden。
- OKX/Gate 走共享 supervisor，但限流指纹偏 Binance `-1003`，其它所频率限制未必触发 180s `_GLOBAL` 冷却。

### 根因

1. DeepCoin `_compute_tp_slices` 缺 ≥95% 拒挂；consumed/expected 仍允许档位 3。  
2. DeepCoin 直接写 `initial_qty = live` 可在监控中压扁基线。  
3. DeepCoin 雷达 `_ensure_radar_sl` 仅价 near，无 qty 贴合。  
4. DeepCoin 哨兵 pause/cool 仍 REST 查仓；查仓失败不 `note_rate_limit`。  
5. `raise_exchange_transient` 对 OKX `50011/50013`、Gate/DeepCoin “too many/frequent” 识别不足。

### 修复

| 项 | 行为 |
|----|------|
| DeepCoin TP | placeable-only + 95% refuse + consumed 无 3 |
| DeepCoin 基线 | `_set_open_qty_baseline`（TV 开仓/重对齐/重启） |
| DeepCoin 雷达 | `_radar_stop_live_qty` 数量不匹配则重挂 |
| DeepCoin 哨兵 | pause/cool → WS breath only；失败 → 180s cool |
| `exchange_errors` | 跨所限流指纹 → 共享 cool |

### 复查点

- [ ] OKX/Gate 与 Binance 同属 `PositionSupervisor`：开仓后 TP1+TP2≤~30%。  
- [ ] DeepCoin 单测：placeable / 基线拒绝压缩 / 哨兵 cool 分支存在。  
- [ ] OKX `code=50011` 触发 `note_rate_limit`。

---

## §9 · pipeline-ledger-v1（全域生产级流水线 · 2026-07-27）

### 现象

今日实盘多点故障（TP 切片吞仓、限流螺旋、暂停不生效、OPEN 钉钉抢跑）同源：各模块凭本地记忆判断，无统一交接状态。

### 根因

无「总账本 + 岗位边界 + 督察结案」。通讯在 VERIFIED 前即发 OPEN；哨兵在 cool/pause 下仍可打 REST；TP 自检不统一。

### 修复

| 模块 | 行为 |
|------|------|
| `trade_ledger.py` | 用户-交易所-品种账本；状态机 SIGNAL→…→VERIFIED→REPORTED / FLAT / FAILED |
| `pipeline_officers.py` | 信号/准入/稽查/执行(TP≈30%自检)/督察/通讯门禁 |
| `rest_throttle_valve.py` | 账户维 REST 预算 + cool；`sentinel_may_rest` |
| Binance/OKX/Gate + DeepCoin | 开仓链路挂账；挂单后 `run_post_open_pipeline`；flat 自动清审计类 pause |
| `rest_book_cache.py` | 刷新前 `acquire_rest_permit`，拒绝则 stale |
| `dispatcher.py` | `AdmissionOfficer.admit` |

### 复查点

- [ ] 开仓后 `data/supervisor/ledgers/ledger_*.json` 相位到 VERIFIED/REPORTED  
- [ ] TP1+TP2 自检失败 → 拒挂 + 督察 FAIL 暂停  
- [ ] cool/pause 下哨兵无新 REST；账本优先  
- [ ] OPEN/DEFENSE 钉钉在 VERIFIED 前被 CommunicationsOfficer 拦截（critical 放行）  
- [ ] 本地 = GitHub = VPS 同 commit

---

## 版本与部署对照

| 项 | 说明 |
|----|------|
| 标签 | `pipeline-ledger-v1` + `v16.4.2-incident-harden` |
| 三方同步 | 本地 = GitHub `main` = VPS `git rev-parse --short HEAD` **同数字** |
| VPS | `/home/panda/panda-quant-platform` · `docker compose` backend |
| 部署后最小验证 | ① 账本相位 ② TP 自检 ③ pause/cool 无 REST ④ 通讯门禁 ⑤ 全交易所同行为 |

---

## 如何追加新条目

1. 顶部索引表加一行。  
2. 新建 `§N · 日期 · 标题`：现象 / 根因 / 修复（文件+行为）/ 复查点 checklist。  
3. README「事故与修复日志」链到本文件；不要把长叙事只写在聊天里。
