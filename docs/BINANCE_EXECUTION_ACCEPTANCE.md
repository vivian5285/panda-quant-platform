# Gemini 币安执行层最终验收清单（状态跟踪）

更新：2026-07-22 19:50 CST  
范围：仅 TV→VPS→币安执行链路（不含结算/多所铺开）

**总判定：验收通过。** 权威摘要见 [GEMINI_FINAL_STATUS_20260722.md](GEMINI_FINAL_STATUS_20260722.md)。

## 阻塞项（必须）— 已关闭

| # | 项 | 状态 | 说明 |
|---|-----|------|------|
| B1 | TP 重复挂单修复后观察无复发 | **✅ 通过** | 修复入库后持续观察 + E2E 持仓约 14min 无二次核武抖动 |
| B2 | TP1/TP2 成交 → 止损 qty 收缩 | **✅ 通过（代码模拟）** | `test_tp_fill_stop_qty_resize` 等；自然 TP 成交样本列为非阻塞可选 |
| B3 | 真实完整平仓 → 状态清零 | **✅ 通过** | E2E `CLOSE_QUICK_EXIT`：市价全平、撤单、state 清零、钉钉「反转保护」 |

## 全链路 webhook 实锤（User6 · ETH）

见 [E2E_WEBHOOK_TIMELINE_20260722.md](E2E_WEBHOOK_TIMELINE_20260722.md) / [E2E_ANOMALY_ANALYSIS_20260722.md](E2E_ANOMALY_ANALYSIS_20260722.md)。

## 非阻塞项（记录在案，可后补）

| # | 项 | 状态 |
|---|-----|------|
| N1 | webhook 乱序 CLOSE→OPEN 实测证据 | 架构已有；实锤可后补 |
| N2 | ADX 与 TV 人工核对 3–5 点 | 待补 |
| N3 | 平静场景先平后开标准日志范例 | 待补 |
| N4 | 实操重启恢复 | 部分有（E2E 前 restart 清 pause） |
| N5 | WS 重连瞬间 trail 追赶 | 已知缺口 |
| N6 | 交易所 REST 429 / `-1003` 重试 | 记录在案；观察窗禁无必要 rebuild |
| N7 | 钉钉杠杆双数据源 | **已根治**（`FIXED_LEVERAGE`） |
| N8 | 平仓归因过宽断言 | **已修**（证据门） |
| N9 | 自然 TP 成交实盘样本 | 可选；不阻塞 |

## 已打勾摘要

信号鉴权/去重、RISK20、先平后开、ATR/initialStop、TP1+TP2、呼吸引擎唯一写止损、止损抖动修复、防 TP 重复、查询失败≠空仓、归因证据门、杠杆 5× 根治、未登记仓位接管、webhook 全链路 E2E。

## 判定口令

**Gemini 币安执行层验收通过**（2026-07-22）。非阻塞加固项见最终状态清单 §七。
