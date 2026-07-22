# 生产就绪最终确认（2026-07-22）

范围：**Gemini 多用户 SaaS（本仓库）**。  
「币安单一账户」姊妹系统不在本工作区，需在其独立环境另行勾选同一清单。

权威 HEAD：`a3858d3`（本地 = GitHub `origin/main` = VPS）

---

## 一、账本与仓位状态 — ✅ Gemini

| 项 | 结果 |
|----|------|
| User6 ETHUSDT | FLAT · open_orders=0 · algo=0 |
| User6 XAUUSDT | FLAT · open_orders=0 · algo=0 |
| `binance_6_ethusdt` state | monitoring=false · qty=0 · paused=false · atr_fallback=false |
| `binance_6_xauusdt` state | 同上空闲 |
| DB `is_user_paused(6)` | false |
| Redis `*pause*` | 无遗留键 |

其他用户（1–5）无 API Key，无交易所查询必要。

---

## 二、代码与部署一致性 — ✅ Gemini

| 项 | 结果 |
|----|------|
| VPS `git rev-parse HEAD` | `a3858d3f556a91975256213bdf5a93ddc3b1ef18` |
| 本地 / GitHub | 同哈希 · `main...origin/main` |
| 工作区 | 无未提交代码改动；仅未跟踪 `backend/data/`（临时脚本/运行态）、`deploy/Untitled`（无关） |
| health | `{"status":"ok","coalesce_pending":0}` |
| 正式默认参数 | `FIXED_LEVERAGE=5` · `TV_STOP_ATR_MULT=1.0` · TP1/TP2 = **1.35 / 2.5 ×ATR**（非 0.35/0.70 紧 TP 测试参数） |

---

## 三、Webhook 与鉴权 — ✅ Gemini

| 项 | 结果 |
|----|------|
| 生产端点 | `https://twinstar.pro/gemini/webhook` |
| Secret | 后台已配置（len=6，与历史测试一致）；错误 secret → **HTTP 403 `Invalid secret`**（证明路径+鉴权链路通，未开仓） |
| TV 侧 | 请你本人再核对 Pine/告警 URL 与 secret 是否仍指向上述端点（服务端已就绪） |

---

## 四、告警通道 — ✅ Gemini（服务端）

| 项 | 结果 |
|----|------|
| `DINGTALK_WEBHOOK` / `SECRET` | 已配置 |
| 探测 | `push_dingtalk(..., immediate=True)` 返回成功；标题「生产就绪确认」 |
| 接收人 | 请你在钉钉群确认已收到该探测消息（客户端在你侧） |

---

## 五、已知非阻塞项 — 正式登记（知晓并接受）

Gemini（记录在案，不阻塞上线）：

- WS 断线重连止损追赶逻辑未做  
- 交易所 API 限频重试未做  
- OKX/Gate 仅共享代码受益，测试网实锤未做  
- 结算/充值逻辑未独立验证  
- 告警用户归属标注未做  

（币安单一系统对应项请在姊妹仓库清单勾选。）

---

## 六、正式确认 — Gemini

- [x] 以上环境/配置项已核对  
- [x] **转入生产监管状态：等待真实 TV 信号**  
- [x] 不建议继续主动加测；异常按正常排查流程处理  

币安单一账户系统：本清单 **未在本环境执行**，需你在对应 VPS/仓库单独确认后即可两边齐套。
