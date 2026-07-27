# 智能再入场闭环 · 白皮书 v3.0（生产权威）

> 同步：2026-07-25 · whitepaper v3.0 · commit 以 `main` HEAD 为准（部署后三方肉眼同 hash）  
> 适用：ETHUSDT（90m）/ XAUUSDT（45m）  
> 凡「5 档递进 / arm 50~95% / buffer 1.1/1.2/1.3 / 字面 TP1×0.85」旧文 **作废**。

本文解释**代码落点与调用顺序**。业务理念见根目录 `README.md`。权威白皮书：`docs/WHITEPAPER_DUAL_RADAR_REENTRY_v3.md`（与桌面 `双币种雷达重入系统白皮书_v3.md` 同步）。

---

## 1. 灵魂（三条路径，无第四种）

| 路径 | 触发 | 行为 |
|------|------|------|
| ① 理想 | TP1/TP2 限价 + 雷达兑现 TP3 残仓 | 逐级兑现 → flat → 等下一 TV |
| ② 核心 | 雷达在保本/微赚区扫出，且在窗口内 | 清场 → 双保险限价再入（最多 1 次）→ trail +1 档（arm 仍由 ADX 驱动） |
| ③ 认输 | 硬止损 / 亏损 / 窗口过期 / 已重入过 / **该用户TP1已成交** / **档位非强趋势(tier≠2)** | **永不重入**，等新 TV |

---

## 2. 模块地图

```
TV webhook (:6010)
  → position_supervisor._close_all / OPEN protect
       │
       ├─ flat 成功
       │    ├─ _maybe_arm_smart_reentry(defer=True)   # plan（含窗口/次数）
       │    ├─ purge 净场
       │    └─ _commit_deferred_reentry()             # 净场后再开 worker
       │
       └─ OPEN / 再入成交
            └─ _protect_and_monitor
                 ├─ 硬止损  compute_temp_tv_stop(…, buffer=1.15 固定)
                 ├─ TP1/TP2 (10/20；TP3=70% 雷达)
                 └─ 雷达    fill ± (1.35×ATR × ADX_ratio 70%~90%)
```

| 文件 | 职责 |
|------|------|
| `trend_tier_params.py` | ADX 0/1/2 档参数表；Layer-1 ADX arm 70–90%；固定 hard buffer |
| `smart_reentry.py` | 再入条件、窗口、双保险价、最多 1 次、trail +1 |
| `smart_reentry_mixin.py` | plan/commit、限价 worker、钉钉、持久化 `radar_tp1_distance` |
| `breathing_stop.py` | 硬止损 buffer；雷达延迟启动 + 被动跟踪 |
| `order_place_guard.py` | 本地挂单标签 |
| `rest_symbol_pace.py` | 单品种 REST ≥100ms（白皮书 §8.3） |
| `ip_rest_cooldown.py` | −1003 共享 90s 冷静 |
| `adverse_radar_guard.py` | 双轨 STOP 挂/改 |

参数表镜像：`smart_reentry_tiers.json`（文档/运维对照；运行时以 `trend_tier_params.py` 为准）。

---

## 3. ADX 档位与关键参数

| 档 | ADX | 硬止损 buffer |
|----|-----|---------------|
| 0 弱 | &lt;20 | **1.15（统一）** |
| 1 中 | 20–30 | **1.15（统一）** |
| 2 强 | &gt;30 | **1.15（统一）** |

可选：webhook 传 `tier`（0/1/2）；否则 ADX；再否则 `tv_stop_distance/atr` 启发式。

雷达启动 Layer-1（ADX 驱动，与 TP1 是否成交无关）：
```
ADX ≤ 17 → 70%；ADX ≥ 35 → 90%；中间线性插值
arm_distance = (1.35 × initial_atr) × start_ratio
多：触发价 = fill + arm_distance；空：fill − arm_distance
```
Layer-2 追踪 `trailDistanceMultiplier` 仍由实时 ATR/initial_atr 比值驱动（ETH 1.2~2.5 / XAU 0.5~1.2），与 Layer-1 独立。
激活瞬间：止损上移至 **开仓价 ± 0.5×ATR**。

| 参数 | ETH 弱/中/强 | XAU 弱/中/强 |
|------|--------------|--------------|
| 跟踪步长×ATR | 0.40 / 0.50 / 0.60 | 0.35 / 0.40 / 0.50 |
| 跟进幅度×ATR | 0.25 / 0.35 / 0.40 | 0.20 / 0.30 / 0.35 |
| TP1→TP2 呼吸 | 0.80 / 1.20 / 1.50 | 0.70 / 1.00 / 1.30 |
| TP2→TP3 呼吸 | 1.00 / 1.60 / 2.00 | 0.90 / 1.40 / 1.80 |
| TP3 后 coef | 1.2~1.5 / 2.0~2.5 / 2.5~3.5 | 1.0~1.3 / 1.8~2.2 / 2.2~3.0 |
| 重入窗口 | 2 根×90m ≈ 3h | 3 根×45m ≈ 2.25h |
| 重入区 | 开仓价→开仓+0.5×ATR | 开仓价→开仓+0.3×ATR |

重入成功：雷达 trail 取 **ADX档+1**（封顶强档）；Layer-1 arm 仍按当前 ADX 插值；不影响 TP 价格与数量。

### 重入硬闸（Gemini 多用户规格 §9.1 本版新增）

1. **`tp1_filled=True`（该用户本笔已吃过 TP1）→ 禁止重入** — 趋势曾确认后反转，非噪音扫出。
2. **`adx_tier != 2`（非强趋势）→ 禁止重入** — 弱/中趋势雷达扫出一律不重入；档位按 TV 信号统一，全用户一致。

落点：`smart_reentry.close_allows_reentry(..., tp1_filled=, require_strong_tier=True)`；`smart_reentry_mixin` 从 `consumed_tp_levels` 推导 TP1，并传入 `_resolve_trend_tier()`。

### 切片/部分止盈（规格 §7.3）

TP1/TP2/TP3 可能分批成交 → 实时总头寸变小。每次 TP 对账 / WS 感知成交后，**硬止损+雷达止损数量按当时交易所 live qty 收缩**（价格不变）。`_bump_sl_after_tp_reconcile` / `_boost_radar_after_tp_fill` 禁止仅用陈旧 `watched_qty`。平仓市价一律 `reduce_only` 且 `qty ≤ live`，杜绝反向开仓。空仓后 `_purge_defense_orders_on_flat` 多轮 mop 清幽灵/蚂蚁限价。

---

## 4. 硬止损

```
tv_stop_distance = |TV.price − TV.stop_loss|
actual_stop_distance = tv_stop_distance × 1.15
多：硬止损 = fill − actual；空：fill + actual
```

算例：TV 1900 / SL 1874 → dist 26 × 1.15 = 29.90；fill 1900.80 → **1870.90**。

---

## 5. 验收探针

```
MAX_REENTRY == 1
radar_arm_ratio_by_adx(17) == 0.70
radar_arm_ratio_by_adx(35) == 0.90
HARD_STOP_BUFFER_FIXED == 1.15
compute_temp_tv_stop(1900.80, LONG, 1874, tv_entry=1900) == 1870.90
radar_arm_trigger_price(fill=1900, atr=20, adx=17) == 1900 + 1.35*20*0.70
```

三方 commit 同数字；`E2E_FORCE_NOTIONAL_USD=0`。
