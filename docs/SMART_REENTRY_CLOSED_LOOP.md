# 智能再入场闭环 · 白皮书 v3.0（生产权威）

> 同步：2026-07-25 · whitepaper v3.0 · commit 以 `main` HEAD 为准（部署后三方肉眼同 hash）  
> 适用：ETHUSDT（90m）/ XAUUSDT（45m）  
> 凡「5 档递进 / arm 50~95% / buffer 1.1/1.2/1.3 / 字面 TP1×0.85」旧文 **作废**。

本文解释**代码落点与调用顺序**。业务理念见根目录 `README.md`。桌面白皮书原文：`双币种雷达重入系统白皮书_v3.md`。

---

## 1. 灵魂（三条路径，无第四种）

| 路径 | 触发 | 行为 |
|------|------|------|
| ① 理想 | TP1/TP2/TP3 限价成交 | 逐级兑现 → flat → 等下一 TV |
| ② 核心 | 雷达在保本/微赚区扫出，且在窗口内 | 清场 → 双保险限价再入（最多 1 次）→ trail +1 档 + **arm=1.00** |
| ③ 认输 | 硬止损 / 亏损 / 窗口过期 / 已重入过 | **永不重入**，等新 TV |

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
                 ├─ TP1/TP2/TP3 (10/20/70)
                 └─ 雷达    fill ± tp1_distance × (0.85|1.00)
```

| 文件 | 职责 |
|------|------|
| `trend_tier_params.py` | ADX 0/1/2 档参数表；arm 公式；固定 hard buffer |
| `smart_reentry.py` | 再入条件、窗口、双保险价、最多 1 次、arm 0.85→1.00、trail +1 |
| `smart_reentry_mixin.py` | plan/commit、限价 worker、钉钉、持久化 `radar_tp1_distance` |
| `breathing_stop.py` | 硬止损 buffer；雷达延迟启动 + 被动跟踪 |
| `order_place_guard.py` | 本地挂单标签 |
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

雷达启动（距离，非绝对价）：
```
tp1_distance = |TV.tp1 − TV.price|
首次：fill ± tp1_distance × 0.85
重入：fill ± tp1_distance × 1.00
```
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

重入成功：雷达 trail 取 **ADX档+1**（封顶强档）；arm 固定 **1.00**；不影响 TP 价格与数量。

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
RADAR_ARM_TP1_PCT == 0.85
RADAR_ARM_TP1_PCT_REENTRY == 1.00
HARD_STOP_BUFFER_FIXED == 1.15
compute_temp_tv_stop(1900.80, LONG, 1874, tv_entry=1900) == 1870.90
radar_arm_trigger_price(fill=1900.80, tp1=1925.65, tv_entry=1900, 0.85) == 1922.60
```

三方 commit 同数字；`E2E_FORCE_NOTIONAL_USD=0`。
