# 智能再入场闭环 · 白皮书 v2.0（生产权威）

> 同步：2026-07-25 · whitepaper v2.0 · commit 以 `main` HEAD 为准（部署后三方肉眼同 hash）  
> 适用：ETHUSDT（90m）/ XAUUSDT（45m）  
> 凡「5 档递进 / arm 50~95% / buffer 固定 1.2」旧文 **作废**。

本文解释**代码落点与调用顺序**。业务理念见根目录 `README.md`。

---

## 1. 灵魂（三条路径，无第四种）

| 路径 | 触发 | 行为 |
|------|------|------|
| ① 理想 | TP1/TP2/TP3 限价成交 | 逐级兑现 → flat → 等下一 TV |
| ② 核心 | 雷达在保本/微赚区扫出，且在窗口内 | 清场 → 双保险限价再入（最多 1 次）→ 雷达放宽 +1 档 |
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
                 ├─ 硬止损  compute_temp_tv_stop(…, trend_tier=ADX档)
                 ├─ TP1/TP2/TP3 (10/20/70)
                 └─ 雷达    路径 TP1×0.85 才激活
```

| 文件 | 职责 |
|------|------|
| `trend_tier_params.py` | ADX 0/1/2 档参数表（ETH/XAU 完整 knobs） |
| `smart_reentry.py` | 再入条件、窗口、双保险价、最多 1 次、+1 档放宽 |
| `smart_reentry_mixin.py` | plan/commit、限价 worker、钉钉 |
| `breathing_stop.py` | 硬止损 buffer；雷达延迟启动 + 被动跟踪 |
| `order_place_guard.py` | 本地挂单标签 |
| `adverse_radar_guard.py` | 双轨 STOP 挂/改 |

参数表镜像：`smart_reentry_tiers.json`（文档/运维对照；运行时以 `trend_tier_params.py` 为准）。

---

## 3. ADX 档位与关键参数

| 档 | ADX | 硬止损 buffer |
|----|-----|---------------|
| 0 弱 | &lt;20 | 1.1 |
| 1 中 | 20–30 | 1.2 |
| 2 强 | &gt;30 | 1.3 |

雷达启动：路径 **TP1×0.85**（入场→TP1 路程的 85%，非字面 `TP1*0.85`）。  
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

重入成功：雷达系数取 **ADX档+1**（封顶强档）；不影响 TP 价格与数量。

---

## 4. 硬止损

```
tv_stop_distance = |TV.price − TV.stop_loss|
actual = tv_stop_distance × buffer(ADX档)
hang = fill ± actual
缺 SL / ≤0 / 距 < 5 ticks → 拒开仓
至 flat：禁止收紧/撤销/替换
```

---

## 5. 本地标签与挂单硬帽

同旧：`PendingOrderRegistry` + `OPEN_ORDERS_HARD_CAP=5` + 查单失败 fail-closed。  
宁可错过，不要做错。

---

## 6. 钉钉事件（须含品种标签 + 档位）

| 事件 | 含义 |
|------|------|
| 开仓 | 品种/方向/价/量/档位/硬止损/TP123 |
| 雷达激活 | 激活价、档位、初始止损上移位置 |
| 止损移动 | 新止损、浮盈、档位 |
| TP 成交 | TP1/2/3、成交价、剩余比例 |
| 平仓 | 来源（TP/雷达/硬/反转）、价、盈亏、档位 |
| `SMART_REENTRY_ARM` | 重入尝试：原因、价、档位、窗口剩余 |
| `SMART_REENTRY_PROTECTED` | 重入成交后硬+TP+雷达核查 |
| `REENTRY_ABORT` / `REENTRY_SKIP` | 放弃（窗口/价格不优/已重入/硬止损等） |

---

## 7. 部署探针

```bash
docker compose exec -T -e PYTHONPATH=/app backend python /app/data/_vps_verify_smart_reentry.py
```

验收：`MAX_REENTRY==1`、arm=`0.85`、ADX 档 buffer 1.1/1.2/1.3、三方 commit 同数字。
