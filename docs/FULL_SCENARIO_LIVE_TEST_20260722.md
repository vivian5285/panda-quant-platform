# Gemini 全场景实盘测试交付（2026-07-22）

依据桌面《Gemini全场景实盘测试指令》。账户：User 6 · Binance · ETHUSDT。  
生产锚点：VPS `77d171b`（执行层）；本地验收文档 `74fb39b` 已在 `origin/main`（本轮未强制 rebuild）。

Webhook：`https://twinstar.pro/gemini/webhook`

---

## 总览

| # | 场景 | 本轮结论 |
|---|------|----------|
| 7 | 持仓期间 VPS 重启 | **✅ 真实验证通过**（必须项） |
| 6 | SHORT 完整周期 | **⏭ 用户决定跳过**，等真实 TV |
| 1 | 阶段一阶梯止损真实移动 | ⏳ 约 20min 观察未触发（已收尾） |
| 2 | TP1/TP2 真实成交→止损 qty 收缩 | ⏳ 未触发（已收尾） |
| 8 | 跨越 90m K 线 ADX 更新 | ⏳ 未完整覆盖（已收尾） |
| 3 | 进入阶段二 | **逻辑已通过模拟验证**；真实触发留待自然 |
| 4 | 真实止损触发 | 待生产自然发生 |
| 5 | TP3 阶段追踪全平 | 待生产自然发生 / 已有代码模拟 |

---

## 场景 7 · 持仓重启（必须项）— PASS

### 开仓

| UTC | 事件 |
|-----|------|
| 12:53:23Z | POST LONG qty=0.03，`stop_loss=price−1.0×ATR` → HTTP 200 |
| 12:53:24Z | ATR 核对 OK：vps=13.8737 / tv_implied=14.05（Δ1.3%） |
| 12:53:29Z | 市价 LONG **0.029** @ 1920.74 · `trade_id=54` |
| 12:53:35–51Z | 开仓初始化补挂 TP1/TP2（日志仍含「核武」字样：VPS 未拉 74fb39b 措辞） |
| 12:53:54Z | algo stop SELL trigger=**1899.93** |
| 12:53:57Z | 钉钉 OPEN：档位3 · **5×** · 呼吸止损 @1899.93 |

### 重启前快照（13:00:14Z）

| 字段 | 值 |
|------|-----|
| side / qty / entry | LONG 0.029 @ 1920.74 |
| initial_atr | 13.873693747839834 |
| initial_stop / current_sl | 1899.9294593782402 |
| best_price | 1920.74 |
| breakeven_phase | false |
| TP1 / TP2 | 0.009@1939.81 / 0.009@1955.96 |
| algo | id=1000002467904094 · trigger=1899.93 · qty=0.029 |
| adverse_sl_armed | true |
| trading_paused | false |

### 动作

`docker compose restart backend`（**无 rebuild、无 state 清零**）→ health ok → 等待 recover ≈20s。

### 重启后对比（VERDICT **PASS**）

| 字段 | before → after |
|------|----------------|
| watched_entry | 1920.74 → 1920.74 |
| initial_atr | 13.8737… → 同 |
| initial_stop | 1899.929… → 同 |
| **current_sl** | **1899.929… → 同（未振荡）** |
| best_price / side / qty / trade_id / leverage / schema | 全部一致 |
| algo trigger | 1899.93 → 1899.93 |
| monitoring / paused | true / false |

恢复日志摘录：

```
呼吸止损重启恢复: phase=1 best=1920.74 SL=1899.93 atr=13.8737 adx=28.1
[UserEvent][STARTUP] … LONG 0.029 @ 1920.74 | TP2/2 | 呼吸止损✓ | 未重复挂单
```

**结论：持仓重启后呼吸状态完整恢复，止损价未出现姊妹系统式虚构 ATR 振荡；TP 仍识别为未成交并继续监控。场景 7 通过。**

---

## 场景 1 / 2 / 8 · 延长观察摘要（已按用户指令提前收尾）

观察窗：约 **12:53Z 开仓 → 13:13Z 主动 CLOSE**（约 20 分钟；未等到阶梯/TP/90m 自然触发）。

| 项 | 结果 |
|----|------|
| 止损真实移动 | **未发生** · 全程 `best≈entry=1920.74` · `step_count=0` · `current_sl` 恒为 **1899.93** |
| TP1/TP2 成交 | **未发生** · 限价仍挂 1939.81 / 1955.96 直至平仓撤销 |
| 90m ADX 更新 | **未完整覆盖** · 观察期内 `current_adx` 仍约 28.13（未跨过足以验证的收盘窗） |
| 收尾 | 13:13:10Z `CLOSE_QUICK_EXIT` HTTP 200 → 市价平仓 → 状态清零 |

公式对照基准（本窗未触发）：`step_count=floor((best−entry)/(0.75×ATR))`；`expected=initial_stop+step_count×0.4×ATR`。

---

## 场景 3 · 阶段二（模拟补充）

新增单测：`test_phase1_to_phase2_and_adx_trail_interpolation` / `test_phase2_short_symmetric_sim`  
（`backend/tests/test_breathing_stop.py`，**12 passed**）

标注：**逻辑已通过模拟验证，真实触发验证留待生产环境自然发生时留意确认。**

---

## 场景 6 · SHORT

**本轮按用户决定跳过**（平观察仓后直接进入等真实 TV，不再人工 SHORT）。对称性仍有单测覆盖；真实 SHORT 留待生产 TV。

---

## 场景 4 / 5

不强求本轮人为触发；待自然发生记录。

---

## 生产前收尾结论（用户指令 2026-07-22）

- 场景 **7 必须项已通过**。
- 观察仓已主动平仓；系统进入 **等待真实 TV 信号** 的生产监管状态。
- GitHub / 本地 / VPS 代码三方对齐见同日部署记录（目标同一 `main` HEAD）。
