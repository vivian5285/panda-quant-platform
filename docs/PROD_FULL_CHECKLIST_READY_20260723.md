# Gemini 生产级最终全功能检测 · 就绪报告

生成：2026-07-23  
对照清单：桌面《Gemini生产级最终全功能检测清单.md》

---

## 三方 commit 对照（书面证据）

| 位置 | commit | 说明 |
|---|---|---|
| 本地 `main` | **`6953763`** | Drop TV qty gate… + 连续插值生产锁 `d5fe10d` 之上 |
| GitHub `origin/main` | **`6953763`** | 已 push |
| VPS `/home/panda/...` | **见部署后探针**（目标 `6953763`） | `git reset --hard origin/main` + rebuild |

前置生产锁：`d5fe10d`（连续插值证据 + XAU 0.5~1.2 + 冷启动种子）。

---

## 零、initial_atr 来源（已拍板）

| 决定 | 证据 |
|---|---|
| **继续用 TV webhook `atr`**，开仓冻结为 `initial_atr` | `position_supervisor` 开仓路径；README / `VPS_LIVE_CHECKLIST` 已写明 |
| 异常（缺失/≤0/中位数异常）**拒开仓**，禁止 VPS K 线发明 atr | `open_atr_guard` + `atr_invalid` 硬门 |
| 不改回「VPS 独立算开仓 atr」 | 避免历史 33% 假偏差类事故 |

---

## 一、Webhook 精简（qty 可缺省）

| 项 | 状态 | 证据 |
|---|---|---|
| 算仓 = 本金×20%×5/价 | ✅ | `tv_entry_sizing.compute_tv_entry_qty` · `binding=margin20_lev5` |
| **不再**强制要求 qty 字段 | ✅ | `6953763` 删除 `missing_tv_qty` 门禁 |
| qty1/2/3 不参与 TP 数量 | ✅ | `_compute_tp_slices` 固定 30%/30%；`resolve_tp_ratios_from_payload` 忽略 payload |
| atr 异常拒绝 | ✅ | 开仓硬门 + 钉钉 `ATR_INVALID`/`ATR_ANOMALY` |
| TV 策略侧去掉 qty | ⚠️ 需你在 TradingView 确认 | 代码已兼容有/无 qty |

---

## 二、三方同步

| 项 | 状态 |
|---|---|
| 本地与 origin 一致 | ✅ 目标 `6953763` |
| VPS health | ✅ `:6010` / `:8000` ok（探针） |
| 交易未全局暂停 | ✅ `global_paused=False` |

本地仍有大量未跟踪 `_vps_*.sh` 运维脚本（不影响运行）。

---

## 三～八（代码存续复查摘要）

| 章节 | 结论 |
|---|---|
| 三 历史 bug | ✅ 抖动/清零/钉钉白名单/TP qty 收缩/杠杆5/fail-closed 查仓/归因门/DeepCoin TP 补齐 — 仍在主干 |
| 四 重复挂单 | ✅ fail-closed 计数、同价拒挂、脏簿拒开（`56bdb4b` 起） |
| 五 呼吸 | ✅ 连续插值 ETH 1.2~2.5 / XAU 0.5~1.2；阶段一无 coef；冷启动 1.525/0.675 |
| 六 TP | ✅ 仅挂 TP1/TP2 30/30；TP3 不挂 |
| 七 双币 | ✅ profile 独立；floor/ceiling 只读 |
| 八 多用户 | ✅ `(exchange,user,symbol)` 隔离断言 |

详证：`docs/CONTINUOUS_BREATH_PROD_TEST_20260723.md`、`docs/BINANCE_EXECUTION_ACCEPTANCE.md`、E2E 文档。

---

## 九、冒烟（证据分层）

| 项 | 状态 | 说明 |
|---|---|---|
| LONG 全流程（开仓→TP→呼吸→平仓） | ✅ 已有 | E2E webhook 2026-07-22 + 连续插值双币观察 6×5min（`pass:true`） |
| 无 qty 字段开仓 | ✅ 单测/容器断言 | `6953763`；**建议首笔真实 TV 用无 qty JSON 再盯一眼** |
| SHORT 全流程 | ⚠️ 历史 scenario 有短测 | **本轮未重跑 SHORT 最小资金冒烟** |
| 收尾空仓 + unpaused | ✅ | user6 ETH/XAU 空仓、paused=false（探针） |

---

## 十、验收结论

| 判定 | 说明 |
|---|---|
| **可接真实 TV（ETH+XAU）** | 三方将对齐 `6953763`；算仓/呼吸/挂单门禁已生产级 |
| 剩余人工项 | ① TV Pine 确认已去掉 qty；② 可选补一次 SHORT 最小资金冒烟；③ 首笔真实信号盯钉钉 5× / coef 连续 / 1 stop+2 TP |

**生产监管状态：进入等待真实 TV。**
