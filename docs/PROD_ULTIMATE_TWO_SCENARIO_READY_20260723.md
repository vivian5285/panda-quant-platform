# Gemini 终极最终方案 · 生产就绪报告

生成：2026-07-23  
对照：桌面《Gemini终极最终方案.md》

---

## 三方 commit 对照（部署后填写）

| 位置 | commit | 说明 |
|---|---|---|
| 本地 `main` | **（deploy）** | 两场景 ATR + 临时 TV 止损 + 条件 TP3 |
| GitHub `origin/main` | **（deploy）** | 已 push |
| VPS `/home/panda/...` | **（deploy）** | health ok · trading on |

---

## 定稿行为（已实现）

| 项 | 状态 |
|---|---|
| 开仓即挂 TV `stop_loss`×1.2 临时硬止损 | ✅ |
| 始终挂 TP1/TP2 30%/30%；场景一不挂 TP3 | ✅ |
| 立即拉原生 1h ATR；成功→场景一重算 initial_atr/stop | ✅ |
| 失败→场景二用 TV atr + 挂 TP3 40% + 记录钉钉 | ✅ |
| tick 重试升级场景一并撤 TP3（不止损倒退） | ✅ |
| qty 字段可缺省；算仓 equity×20%×5 | ✅ |
| Binance + DeepCoin 双路径对齐 | ✅ |

实现入口：`open_atr_scenario.py` · `adverse_radar_guard.py` · `position_supervisor*.py` · `tp_regime_targets.py`

---

## 生产监管

**进入等待真实 TV 信号。** 首笔盯：临时→精确止损切换、`atr_scenario`、TP 档数（场景一=2 / 场景二=3）、钉钉 ATR_SCENARIO 记录。
