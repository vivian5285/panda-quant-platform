# 真实TV首次到达失败根因（2026-07-22 15:00 UTC）

## 结论摘要

| 系统 | 根因 | 「0.02 vs 4.445」是否脱节？ |
|------|------|---------------------------|
| **币安单一** | TV.qty=8.6e8 → adjusted 上限失效 → **bind=notional → qty=4.445**；市价 `-2019 Margin is insufficient` | **否**：下单用的就是 sizing 算出的 4.445。钉钉 0.02 是**信号预览阶段仍用上笔残留 tv_suggested_qty** 的误导播报 |
| **Gemini** | (1) 呼吸初始化把 **VPS 1.5×ATR 止损写进 `tv_sl`**，ATR 应急降级误判 Δ≈50%；(2) 巨大 TV.qty 同样使 TV 上限失效，打满名义 → `-2019`；文案「下单后未检测到持仓」掩盖了拒单 | sizing→下单**同值**；拒单非查询失败当空仓 |

两边交易所均为 **FLAT**，无成交仓位。

---

## 原始日志要点

### Gemini（User6）

```
15:00:13 ATR核对 OK: vps=15.6453 tv_implied=15.6433 (÷1.00)  ← 用 payload stop_loss
15:00:17 ATR_FALLBACK: TV隐含ATR=23.457997 Δ=49.94%      ← 用被覆写的 tv_sl=1908.93(=VPS止损距)
15:00:17 market order failed: APIError(code=-2019): Margin is insufficient.
15:00:18 TRADING_PAUSED / DISPATCH_PARTIAL_FAIL
```

状态残留：`tv_sl=1908.932`（应为 TV 1916.76）、`current_atr=23.457997`（降级值）、`trading_paused=true`。

### 币安单一

```
15:00:10 预览核算 TV.qty=0.02 → qty=0.02   ← 残留
15:00:10 仓位参数 TV.qty=865680123           ← 已绑定本笔
15:00:17 开仓核算 tv′=5.78e8 bind=notional → qty=4.445
15:00:18 [市价开仓失败] LONG 4.445: APIError(-2019) Margin is insufficient
```

4.445 = `1719×5 / 1932.4`（全额 5× 名义），不是 qty1/2/3 换算产物。

ATR 降级钉钉文案中的 `15.645332 / 23.457997` **来自 Gemini**，非单一系统本笔（单一本笔 `atr_source=vps`，未降级）。

---

## 修复（本轮）

1. Gemini：TV `stop_loss` 写入 `_tv_stop_loss_ref`；ATR/sizing **禁止**回退到 VPS hang 价  
2. Gemini+单一：`TV.qty` 相对 risk/notional 荒谬时忽略 TV 上限；名义乘 **0.85 haircut** 降 -2019  
3. Gemini：开仓失败返回交易所原始错误，不再只报「未检测到持仓」  
4. 单一：预览前已强制 `_apply_tv_sizing_params`（代码侧）；`compute_fixed_order_qty` 同步荒谬 qty/haircut  
5. 回归：`tests/test_absurd_tv_qty_sizing.py`（巨大 qty 与 final_qty≡order_qty）

**恢复自动交易前**：部署修复 → 人工确认空仓 → 清 pause/streak → 再放行。
