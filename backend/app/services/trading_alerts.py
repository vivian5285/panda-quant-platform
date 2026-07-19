"""DingTalk trading alerts — per-exchange GEMINI themes + 管理员中文可读通知."""

from __future__ import annotations

from app.config import exchange_leverage, get_settings
from app.services.dingtalk_notify import push_dingtalk

settings = get_settings()

# GEMINI 量化：各交易所独立 UI 主题（leverage/tag 由 resolve_exchange_theme 从配置注入）
EXCHANGE_THEMES: dict[str, dict] = {
    "binance": {
        "label": "币安",
        "symbol": "ETHUSDT",
        "leverage": settings.LEVERAGE,
        "brand": "GEMINI量化 · 币安合约实盘引擎",
        "tag": f"#币安{settings.LEVERAGE}x",
        "accent": "🔷",
        "palette": "靛蓝",
        "header": "━━ 🔷 GEMINI量化 · 币安 ━━",
        "qty_unit": "ETH",
    },
    "deepcoin": {
        "label": "深币",
        "symbol": "ETH-USDT-SWAP",
        "leverage": settings.DEEPCOIN_LEVERAGE,
        "brand": "GEMINI量化 · 深币 SWAP 实盘引擎",
        "tag": f"#深币{settings.DEEPCOIN_LEVERAGE}x",
        "accent": "🟢",
        "palette": "翡翠绿",
        "header": "━━ 🟢 GEMINI量化 · 深币 ━━",
        "qty_unit": "张",
    },
    "okx": {
        "label": "OKX",
        "symbol": "ETH-USDT-SWAP",
        "leverage": settings.OKX_LEVERAGE,
        "brand": "GEMINI量化 · OKX 合约实盘引擎",
        "tag": f"#OKX{settings.OKX_LEVERAGE}x",
        "accent": "🟣",
        "palette": "紫罗兰",
        "header": "━━ 🟣 GEMINI量化 · OKX ━━",
        "qty_unit": "ETH",
    },
    "gate": {
        "label": "Gate.io",
        "symbol": "ETH_USDT",
        "leverage": settings.GATE_LEVERAGE,
        "brand": "GEMINI量化 · Gate 合约实盘引擎",
        "tag": f"#Gate{settings.GATE_LEVERAGE}x",
        "accent": "🟠",
        "palette": "琥珀橙",
        "header": "━━ 🟠 GEMINI量化 · Gate.io ━━",
        "qty_unit": "ETH",
    },
}

_EXCHANGE_TAG_PREFIX = {
    "binance": "币安",
    "deepcoin": "深币",
    "okx": "OKX",
    "gate": "Gate",
}

DEFAULT_THEME = EXCHANGE_THEMES["binance"]

ALERT_TYPE_TAGS = {
    "OPEN": "开仓",
    "CLOSE": "全平",
    "CLOSE_TP3": "TP3全平",
    "CLOSE_PROTECT": "保护全平",
    "CLOSE_STOPLOSS": "TV止损",
    "CLOSE_FAIL": "清仓失败",
    "CLOSE_DEFER": "开仓保护忽略CLOSE",
    "STARTUP": "重启接管",
    "STARTUP_FAIL": "接管失败",
    "DEFENSE_HEAL": "止盈对齐修复",
    "DEFENSE_HEAL_OK": "止盈已对齐",
    "DEFENSE_HEAL_FAIL": "止盈仍异常",
    "TRAIL": "雷达保本",
    "RADAR_ARM": "雷达激活",
    "RADAR_REVOKE": "撤销过早雷达",
    "ADJUST": "人工异动",
    "MANUAL_ADJUST": "人工异动",
    "FORCE_ALIGN": "方向背离",
    "POSITION_SIDE_FLIP": "逆势蚂蚁仓",
    "TP_OVER_COMMIT": "止盈超挂",
    "IDLE_WATCH": "空仓巡检",
    "MANUAL_FLAT_TP_PURGE": "平仓撤止盈",
    "TP_ORPHAN_PURGE": "雷达撤过时TP",
    "TP_RETRY_FAIL": "止盈失败",
    "SL_RETRY_FAIL": "止损失败",
    "SENTINEL_ERROR": "哨兵异常",
    "INSUFFICIENT_BALANCE": "余额不足",
    "NOTIONAL_CAP": "名义敞口超限",
    "LOCK_TIMEOUT": "锁超时",
    "CLOSE_PROTECT_EMPTY": "空仓保护复位",
    "SAME_DIR_TP_REFRESH": "同向智能持仓",
    "SAME_DIR_REOPEN": "同向刷新换仓",
    "PYRAMID": "金字塔加仓",
    "PROFIT_ADD": "浮盈加仓",
    "CAP_ALIGN": "叠仓纠偏",
    "CAP_ALIGN_BLOCKED": "叠仓纠偏中止",
    "CAP_ALIGN_FAIL": "叠仓减仓失败",
    "CAP_ALIGN_OVERTRIM": "叠仓过度减仓",
    "UPDATE_SL": "VPS硬止损更新",
    "UPDATE_TP": "动能止盈升级",
    "SIGNAL_RECV": "TV信号接收",
    "ADVERSE_SL": "TV硬止损",
    "ADVERSE_SL_DISARM": "防护盾撤销·雷达接管",
    "ADVERSE_SL_HIT": "TV硬止损触发",
    "ADVERSE_SL_MISALIGN": "TV硬止损未对齐",
    "ADVERSE_SL_REPAIR": "逆势止损补挂",
    "FALSE_FLAT": "误报空仓",
    "CLOSE_ATTRIBUTION": "平仓归因",
    "POSITION_RECONCILE": "头寸对账",
    "TP_FILLED": "止盈成交",
    "TP_SKIP_REHANG": "拒绝补挂已成交止盈",
    "POSITION_QTY_CHANGE": "仓位异动",
    "FLIP_CLEAN": "先平后开清场",
    "API_OFFLINE": "API离线",
}

ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP3",
    "CLOSE_PROTECT",
    "CLOSE_STOPLOSS",
    "CLOSE_FAIL",
    "CLOSE_DEFER",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "POSITION_SIDE_FLIP",
    "TP_OVER_COMMIT",
    "IDLE_WATCH",
    "MANUAL_FLAT_TP_PURGE",
    "TP_ORPHAN_PURGE",
    "ADJUST",
    "MANUAL_ADJUST",
    "INSUFFICIENT_BALANCE",
    "NOTIONAL_CAP",
    "LOCK_TIMEOUT",
    "CLOSE_PROTECT_EMPTY",
    "SAME_DIR_TP_REFRESH",
    "SAME_DIR_REOPEN",
    "PYRAMID",
    "PROFIT_ADD",
    "SENTINEL_ERROR",
    "TP_RETRY_FAIL",
    "SL_RETRY_FAIL",
    "API_OFFLINE",
    "CAP_ALIGN",
    "CAP_ALIGN_BLOCKED",
    "CAP_ALIGN_FAIL",
    "CAP_ALIGN_OVERTRIM",
    "UPDATE_SL",
    "UPDATE_TP",
    "ADVERSE_SL",
    "ADVERSE_SL_DISARM",
    "ADVERSE_SL_HIT",
    "ADVERSE_SL_MISALIGN",
    "FALSE_FLAT",
    "CLOSE_ATTRIBUTION",
    "POSITION_RECONCILE",
    "TP_FILLED",
    "TP_FILL",
    "TP_SKIP_REHANG",
    "POSITION_QTY_CHANGE",
    "FLIP_CLEAN",
    "TRAIL",
    "RADAR_ARM",
    "RADAR_REVOKE",
})

DINGTALK_VERBOSE_EXCLUDED = frozenset({
    "DEFENSE_HEAL",
    "DEFENSE_HEAL_OK",
    "DEFENSE",
    "DEFENSE_AUDIT",
    "DEFENSE_FAIL",
    "TP_RETRY",
    "SIGNAL",
    "ADVERSE_SL_REPAIR",
    "RECOVERY",
})


def resolve_exchange_theme(exchange: str | None = None, symbol: str | None = None) -> dict:
    from app.core.symbol_registry import (
        exchange_native_symbol,
        label_for_symbol,
        normalize_canonical_symbol,
        qty_unit_for_symbol,
        DEFAULT_CANONICAL,
    )

    key = (exchange or "binance").strip().lower()
    if key == "gateio":
        key = "gate"
    base = dict(EXCHANGE_THEMES.get(key, DEFAULT_THEME))
    lev = exchange_leverage(key)
    prefix = _EXCHANGE_TAG_PREFIX.get(key, "币安")
    base["leverage"] = lev
    can = normalize_canonical_symbol(symbol) or DEFAULT_CANONICAL
    base["canonical_symbol"] = can
    base["symbol"] = exchange_native_symbol(key, can)
    base["qty_unit"] = qty_unit_for_symbol(can, key)
    base["symbol_label"] = label_for_symbol(can)
    tag_sym = "ETH" if can.startswith("ETH") else ("XAU" if "XAU" in can else can[:3])
    if prefix == "OKX":
        base["tag"] = f"#OKX{lev}x·{tag_sym}"
    else:
        base["tag"] = f"#{prefix}{lev}x·{tag_sym}"
    return base


def qty_unit_for_exchange(exchange: str | None = None, symbol: str | None = None) -> str:
    return resolve_exchange_theme(exchange, symbol).get("qty_unit", "ETH")


def format_signal_received_message(payload: dict | None) -> str:
    from app.core.symbol_registry import extract_payload_symbol

    data = dict(payload or {})
    action = str(data.get("action") or "").upper()
    entry_type = str(data.get("entry_type") or "").upper()
    symbol = extract_payload_symbol(data)
    parts = [f"symbol={symbol}", f"action={action}"]
    if entry_type:
        parts.append(f"entry_type={entry_type}")
    if data.get("side"):
        parts.append(f"side={data.get('side')}")
    if data.get("price"):
        parts.append(f"price={data.get('price')}")
    if data.get("risk_pct") is not None:
        parts.append(f"risk_pct={data.get('risk_pct')}%")
    if data.get("qty_ratio") is not None:
        parts.append(f"qty_ratio={data.get('qty_ratio')}")
    if data.get("tv_sl"):
        parts.append(f"tv_sl={data.get('tv_sl')}")
    return " | ".join(parts)


def _pct_text(val: float | None) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(val)


def _line(label: str, value: str) -> str:
    return f"- **{label}**：{value}"


def format_cap_align_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """叠仓纠偏 — 管理员一眼能看懂的中文明细."""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    regime = detail.get("regime")
    regime_txt = f"R{regime}" if regime else "—"
    side = detail.get("side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))

    lines = [
        _line("交易所", theme["label"]),
        _line("合约", theme["symbol"]),
        _line("方向", side_txt),
        _line("档位", f"{regime_txt}（保证金比例 {_pct_text(detail.get('margin_pct'))}）"),
    ]

    # 开仓/纠偏不再单独刷「本金快照」条（与 OPEN 明细重复刷屏）
    if detail.get("margin_usd") and str(detail.get("entry_type") or "").upper() != "OPEN":
        lines.append(_line("档位保证金", f"{float(detail['margin_usd']):.2f} USDT × {theme['leverage']}倍杠杆"))

    live = detail.get("live_qty")
    target = detail.get("target_qty") or detail.get("max_qty")
    new_qty = detail.get("new_qty")
    trimmed = detail.get("trimmed") or detail.get("trim_qty")

    if live is not None and target is not None:
        lines.append(_line("仓位对比", f"实盘 **{float(live):.4f}** {unit} → 档位上限 **{float(target):.4f}** {unit}"))
    if trimmed:
        lines.append(_line("减仓数量", f"**{float(trimmed):.4f}** {unit}"))
    if new_qty is not None:
        lines.append(_line("纠偏后仓位", f"**{float(new_qty):.4f}** {unit}"))

    defense = detail.get("defense") or {}
    if defense.get("expected"):
        lines.append(_line("止盈重挂", f"{defense.get('matched', 0)}/{defense.get('expected')} 档"))
    if detail.get("radar_sl_preserved"):
        lines.append(_line("雷达止损", f"已保留 @{float(detail['radar_sl_preserved']):.2f}"))
    if detail.get("trigger"):
        lines.append(_line("触发场景", str(detail["trigger"])))
    if detail.get("error"):
        lines.append(_line("异常原因", str(detail["error"])))

    return "\n".join(lines)


def format_adverse_sl_detail_cn(detail: dict, exchange: str | None = None) -> str:
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(detail.get("side", "")).upper(), "—")
    hard_pct = detail.get("hard_stop_pct", 10)
    lines = [
        _line("交易所", theme["label"]),
        _line("方向", side_txt),
        _line("硬止损", f"开仓价 {hard_pct:.0f}% 全平"),
        _line("止损价", f"{detail.get('stop_price', '—')}"),
        _line("持仓数量", f"{detail.get('live_qty', 0)} {unit}"),
    ]
    if detail.get("entry"):
        lines.insert(3, _line("开仓价", f"{float(detail['entry']):.2f}"))
    return "\n".join(lines)


def format_close_detail_cn(detail: dict, exchange: str | None = None) -> str:
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    lines = [_line("交易所", theme["label"])]
    if sym:
        lines.append(_line("合约", theme.get("symbol") or sym))
    if detail.get("side"):
        side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(detail["side"]).upper(), detail["side"])
        lines.append(_line("方向", side_txt))
    if detail.get("qty"):
        lines.append(_line("平仓数量", f"{detail['qty']} {unit}"))
    if detail.get("close_reason") or detail.get("reason") or detail.get("tv_reason"):
        lines.append(_line(
            "平仓原因",
            str(detail.get("tv_reason") or detail.get("close_reason") or detail.get("reason")),
        ))
    if detail.get("close_subtype"):
        subtype_labels = {
            "tp3": "TP3止盈",
            "breakeven": "防回吐保本",
            "hard_stop": "硬止损",
            "risk_intercept": "风控拦截",
            "protect": "保护性全平",
            "stoploss": "TV止损",
            "generic": "换防清场",
        }
        lines.append(_line("平仓类型", subtype_labels.get(detail["close_subtype"], detail["close_subtype"])))
    origin = detail.get("close_origin")
    if origin:
        origin_labels = {
            "exchange_limit_tp": "交易所限价止盈成交（非雷达）",
            "exchange_stop": "保本雷达/条件止损触发（非TP限价）",
            "manual_exchange": "交易所人工操作",
            "platform_market": "平台市价全平",
            "tv_forced": "TV强制平仓信号",
            "exchange_already_flat": "盘口已平",
            "unknown": "未能判定",
        }
        lines.append(_line("平仓来源", origin_labels.get(str(origin), str(origin))))
    if detail.get("human_reason"):
        lines.append(_line("归因说明", str(detail["human_reason"])))
    if detail.get("regime") is not None:
        lines.append(_line("档位", f"R{detail['regime']}"))
    if detail.get("atr") is not None:
        lines.append(_line("ATR", str(detail["atr"])))
    if detail.get("tv_price"):
        lines.append(_line("TV价格", f"{float(detail['tv_price']):.2f}"))
    if detail.get("entry"):
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("exit_price"):
        lines.append(_line("平仓价", f"{float(detail['exit_price']):.2f}"))
    if detail.get("live_pnl_pct") is not None:
        lines.append(_line("实盘盈亏", f"{float(detail['live_pnl_pct']):+.2f}%"))
    if detail.get("tv_pnl_pct") is not None:
        lines.append(_line("TV盈亏", f"{float(detail['tv_pnl_pct']):+.2f}%"))
    if detail.get("pnl_pct_delta") is not None:
        lines.append(_line("盈亏偏差", f"{float(detail['pnl_pct_delta']):+.2f}%"))
    if detail.get("verify_note"):
        lines.append(_line("实盘核实", str(detail["verify_note"])))
    if detail.get("attribution"):
        lines.append(_line("归因", str(detail["attribution"])))
    # Radar path context on premature close / 换防清场
    if detail.get("radar_progress") is not None:
        base = detail.get("radar_activation")
        eff = detail.get("radar_activation_effective") or base
        prog = float(detail["radar_progress"])
        if base is not None and eff is not None:
            lines.append(
                _line(
                    "雷达路径",
                    f"进度 {prog:.0%} · 档位需 {float(base):.0%} · 有效需 {float(eff):.0%}",
                )
            )
        else:
            lines.append(_line("雷达路径", f"进度 {prog:.0%}"))
    if detail.get("radar_arm_reason"):
        lines.append(_line("雷达判定", str(detail["radar_arm_reason"])))
    return "\n".join(lines)


def format_vps_entry_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 开仓/加仓 — 风险系数口径（非档位保证金百分比）."""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    entry_type = str(detail.get("entry_type") or "OPEN").upper()
    regime = detail.get("regime")
    regime_txt = f"R{regime}" if regime else "—"
    if detail.get("margin_coeff") is not None:
        regime_txt = f"{regime_txt}（保证金 {_pct_text(detail.get('margin_coeff'))}）"
    side = detail.get("side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))

    lines = [
        _line("交易所", theme["label"]),
        _line("合约", f"{theme.get('symbol_label') or theme['symbol']} `{theme['symbol']}`"),
        _line("类型", {"OPEN": "首次开仓", "PYRAMID": "加仓", "PROFIT_ADD": "浮盈加仓"}.get(entry_type, entry_type)),
        _line("方向", side_txt),
        _line("档位", regime_txt),
    ]
    if detail.get("tp_ratios_pct"):
        lines.append(_line("止盈比例", f"TP1/2/3 = {detail['tp_ratios_pct']}%（对齐 Pine qty_percent）"))

    # OPEN 不再附带本金快照行（头寸价值/保证金已足够）
    if entry_type != "OPEN":
        principal = detail.get("initial_principal") or detail.get("sizing_base")
        if principal:
            lines.append(_line("合约本金", f"{float(principal):.2f} USDT"))

    if entry_type == "OPEN":
        if detail.get("vps_risk_pct") is not None:
            eff = detail.get("effective_risk_pct") or detail.get("scaled_risk_pct")
            scale = detail.get("regime_scale")
            if eff and scale:
                lines.append(_line("VPS 风险", f"{float(detail['vps_risk_pct']):.2f}% × 档位系数 {float(scale):.2f} = {float(eff):.2f}%"))
            else:
                lines.append(_line("VPS 风险", f"{float(detail['vps_risk_pct']):.2f}%"))
        if detail.get("order_amount") is not None:
            lev = detail.get("leverage") or theme["leverage"]
            lines.append(_line("头寸价值", f"{float(detail['order_amount']):.2f} USDT（{lev}×）"))
        if detail.get("margin_usd") is not None:
            lines.append(_line("保证金", f"{float(detail['margin_usd']):.2f} USDT"))
        if detail.get("margin_coeff") is not None and detail.get("vps_risk_pct") is None:
            lines.append(_line("档位权重", f"{float(detail['margin_coeff']) * 100:.0f}% 总本金"))
        notional = detail.get("notional_usd") or detail.get("order_amount") or detail.get("position_value")
        if notional is not None and detail.get("order_amount") is None:
            lev = detail.get("leverage") or theme["leverage"]
            lines.append(_line("名义头寸", f"{float(notional):.2f} USDT（{lev}×）"))
        if detail.get("combined_notional") is not None or detail.get("proposed_notional") is not None:
            total_n = detail.get("proposed_notional") or detail.get("combined_notional")
            mult = detail.get("max_combined_mult") or detail.get("cap_mult") or detail.get("max_mult")
            if mult is None:
                from app.config import get_settings
                mult = float(getattr(get_settings(), "MAX_COMBINED_NOTIONAL_MULT", 13.0) or 13.0)
            cap = detail.get("notional_cap")
            if cap is not None:
                lines.append(
                    _line(
                        "当前总敞口",
                        f"{float(total_n):.2f} / 上限 {float(cap):.2f} USDT（{float(mult):.0f}×本金）",
                    )
                )
            else:
                lines.append(_line("当前总敞口", f"{float(total_n):.2f} USDT（{float(mult):.0f}倍本金上限）"))
        if detail.get("tv_sl"):
            pct = detail.get("hard_sl_pct_display") or detail.get("vps_hard_sl_pct")
            style = detail.get("hard_sl_order_style") or (detail.get("shield") or {}).get("order_style")
            style_cn = {
                "reduce_only_limit": "只减仓限价（已废弃·会秒平）",
                "stop_limit": "Stop-Limit（降级·可能与TP抢份额）",
                "stop_market_qty": "STOP_MARKET 数量单（降级）",
                "stop_market_close_all": "条件全平槽 closePosition（与TP123共存）",
                "deepcoin_trigger_limit": "条件限价",
                "deepcoin_trigger_market": "条件市价",
            }.get(str(style or ""), "")
            if pct:
                line = f"@{float(detail['tv_sl']):.2f}（开仓价×{pct}）"
                if style_cn:
                    line += f" · {style_cn}"
                lines.append(_line("VPS 硬止损", line))
            else:
                lines.append(_line("VPS 硬止损", f"@{float(detail['tv_sl']):.2f}"))
            lines.append(
                _line(
                    "盘口结构",
                    "基础单×3：TP1/2/3 限价 + 条件委托×1：硬止损/雷达合并槽 closePosition（互不抢份额；R1-4按档位路径启动适度追随）",
                )
            )
        if detail.get("tv_sl_reference"):
            ref = float(detail["tv_sl_reference"])
            vps = float(detail.get("tv_sl") or 0)
            note = "（仅参考·不挂单）"
            if vps > 0 and abs(ref - vps) < 0.02:
                note = "（与 VPS 同价·仍只挂 1 张硬止损）"
            lines.append(_line("TV 止损参考", f"{ref:.2f}{note}"))
        elif detail.get("tv_sl_ref"):
            lines.append(
                _line("TV 止损参考", f"{float(detail['tv_sl_ref']):.2f}（仅参考·不挂单）")
            )
        # Regime path arm R1=85%…R4=70% + ATR breath (适度追随)
        if detail.get("radar_armed") or detail.get("radar_active"):
            radar_sl = detail.get("radar_sl") or detail.get("current_sl")
            if radar_sl:
                lines.append(_line("雷达状态", f"已激活 @{float(radar_sl):.2f}"))
            else:
                lines.append(_line("雷达状态", "已激活"))
        else:
            act = detail.get("radar_activation_effective") or detail.get("radar_activation")
            base = detail.get("radar_activation")
            regime = int(detail.get("regime") or 3)
            if act is None:
                from app.core.radar_trail import REGIME_RADAR, radar_effective_activation
                base = REGIME_RADAR.get(regime, REGIME_RADAR[3])["activation"]
                entry = float(detail.get("entry") or detail.get("entry_price") or 0)
                tp1 = 0.0
                tps = detail.get("tv_tps") or []
                if tps:
                    try:
                        tp1 = float(tps[0] or 0)
                    except (TypeError, ValueError, IndexError):
                        tp1 = 0.0
                atr = float(detail.get("atr") or 0)
                act = (
                    radar_effective_activation(regime, entry, tp1, atr)
                    if entry > 0 and tp1 > 0
                    else base
                )
            base = base if base is not None else act
            if abs(float(act) - float(base)) > 0.01:
                arm_txt = (
                    f"待命 · R{regime}路径 {float(base) * 100:.0f}% "
                    f"（有效 {float(act) * 100:.0f}%：TP1 间距收紧）后适度追随"
                )
            else:
                remain = max(0.0, 1.0 - float(act)) * 100.0
                arm_txt = (
                    f"待命 · R{regime}路径 {float(act) * 100:.0f}% "
                    f"（距 TP1 剩 {remain:.0f}%）后启动适度追随（TP2/TP3 锁利）"
                )
            # Show absolute trigger price for short/long when entry+tp1 known
            entry_r = float(detail.get("entry") or detail.get("entry_price") or 0)
            tp1_r = 0.0
            tps_r = detail.get("tv_tps") or []
            if tps_r:
                try:
                    tp1_r = float(tps_r[0] or 0)
                except (TypeError, ValueError, IndexError):
                    tp1_r = 0.0
            side_r = str(detail.get("side") or "").upper()
            if entry_r > 0 and tp1_r > 0 and side_r in ("LONG", "SHORT"):
                span = abs(tp1_r - entry_r)
                need = span * float(act)
                if side_r == "LONG":
                    trig = entry_r + need
                else:
                    trig = entry_r - need
                lines.append(
                    _line(
                        "雷达触发价",
                        f"现价需达 ≈{trig:.2f}（有效路径 {float(act)*100:.0f}% · "
                        f"TP1间距 {span:.2f}）",
                    )
                )
            lines.append(_line("雷达状态", arm_txt))
        slices = detail.get("tp_slices") or []
        if slices:
            parts = []
            for lv in slices[:3]:
                if isinstance(lv, dict):
                    parts.append(f"TP{lv.get('level')} {float(lv.get('qty', 0)):.4f}@{float(lv.get('price', 0)):.2f}")
            if parts:
                lines.append(_line("TP 分批", " · ".join(parts)))
        if detail.get("base_qty") is not None:
            lines.append(_line("基准数量", f"**{float(detail['base_qty']):.4f}** {unit}"))
    else:
        if detail.get("base_qty") is not None:
            lines.append(_line("首次基准", f"{float(detail['base_qty']):.4f} {unit}"))
        ratio = detail.get("add_qty_ratio") or detail.get("qty_ratio")
        if ratio is not None:
            source = detail.get("qty_ratio_source") or "tv_qty_ratio"
            source_label = "TV 动态" if source == "tv_qty_ratio" else "档位默认"
            lines.append(_line("加仓比例", f"{source_label} {float(ratio):.2f} × 首仓"))
        if detail.get("add_qty") is not None:
            lines.append(_line("本次加仓", f"**{float(detail['add_qty']):.4f}** {unit}"))
        if detail.get("add_count") is not None:
            cap = detail.get("max_add_times")
            if cap:
                lines.append(_line("加仓次数", f"{int(detail['add_count'])}/{int(cap)}"))
            else:
                lines.append(_line("加仓次数", str(detail["add_count"])))
        slices = detail.get("tp_slices") or []
        if slices:
            parts = []
            for lv in slices[:3]:
                if isinstance(lv, dict):
                    parts.append(f"TP{lv.get('level')} {float(lv.get('qty', 0)):.4f}@{float(lv.get('price', 0)):.2f}")
            if parts:
                lines.append(_line("新 TP 分批", " · ".join(parts)))
        prev_tps = detail.get("prev_tv_tps")
        new_tps = detail.get("tv_tps")
        if prev_tps and new_tps and prev_tps != new_tps:
            lines.append(_line("TP 价格", f"{prev_tps} → {new_tps}"))
        if detail.get("radar_active"):
            radar_sl = detail.get("radar_sl")
            if radar_sl:
                lines.append(_line("雷达止损", f"{float(radar_sl):.2f}（已按新总头寸同步）"))

    if detail.get("qty") is not None:
        lines.append(_line("实盘数量", f"**{float(detail['qty']):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("tv_sl"):
        lines.append(_line("TV 止损", f"{float(detail['tv_sl']):.2f}"))

    return "\n".join(lines)


def format_force_align_detail_cn(detail: dict, exchange: str | None = None) -> str:
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    live = detail.get("live_side") or "—"
    tv = detail.get("tv_side") or detail.get("last_tv_side") or "—"
    live_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(live).upper(), str(live))
    tv_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(tv).upper(), str(tv))
    lines = [
        _line("交易所", theme["label"]),
        _line("实盘方向", live_txt),
        _line("TV 方向", tv_txt),
        _line(
            "触发",
            {
                "startup": "重启接管",
                "sentinel": "哨兵巡检",
            }.get(str(detail.get("trigger") or ""), str(detail.get("trigger") or "—")),
        ),
    ]
    qty = detail.get("qty") or detail.get("watched_qty")
    if qty is not None:
        lines.append(_line("强平数量", f"**{float(qty):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("adopted_manual"):
        lines.append(_line("来源", "人工/外部开仓"))
    return "\n".join(lines)


def format_startup_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 重启接管 — TP123 / 硬止损 / 雷达进度."""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    side = detail.get("side") or detail.get("current_side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))
    lines = [
        _line("交易所", theme["label"]),
        _line("方向", side_txt),
    ]
    qty = detail.get("qty") or detail.get("live_qty") or detail.get("watched_qty")
    if qty is not None:
        lines.append(_line("实盘数量", f"**{float(qty):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("base_qty"):
        lines.append(_line("首仓基准", f"{float(detail['base_qty']):.4f} {unit}"))
    if detail.get("add_count") is not None:
        lines.append(_line("已加仓", f"{int(detail['add_count'])} 次"))
    if detail.get("adopted_manual"):
        lines.append(_line("接管类型", "人工/外部持仓 · 按最新 TV 补挂"))
        if detail.get("radar_permitted") is False and not detail.get("breakeven_active"):
            lines.append(_line("雷达状态", "待档位路径比例或TP成交后启动适度追随"))
    if detail.get("shield_stop_price") or detail.get("tv_sl"):
        stop_px = detail.get("shield_stop_price") or detail.get("tv_sl")
        if detail.get("breakeven_active"):
            lines.append(_line("雷达止损", f"@{float(stop_px):.2f}（已激活）"))
        else:
            pct = detail.get("hard_sl_pct_display")
            suffix = f" · 开仓价×{pct}" if pct else ""
            lines.append(_line("VPS 硬止损", f"@{float(stop_px):.2f}（雷达未激活）{suffix}"))
        if detail.get("tv_sl_reference"):
            lines.append(_line("TV 止损参考", f"{float(detail['tv_sl_reference']):.2f}"))
    if detail.get("force_aligned"):
        lines.append(_line("逆势处理", "已强平对齐 TV 方向"))
    if detail.get("startup_summary"):
        lines.append(_line("对账摘要", str(detail["startup_summary"])))
    if detail.get("regime") is not None:
        lines.append(_line("档位", f"R{detail['regime']}"))
    if detail.get("tp_ratios_pct"):
        lines.append(_line("止盈比例", f"TP1/2/3 = {detail['tp_ratios_pct']}%"))
    tp_m, tp_e = detail.get("tp_matched"), detail.get("tp_expected")
    if tp_e:
        lines.append(_line("止盈挂单", f"{tp_m or 0}/{tp_e} 档"))
    if detail.get("pnl_track"):
        track = "浮盈/雷达轨" if detail["pnl_track"] == "profit_radar" else "浮亏/防护轨"
        lines.append(_line("风控轨道", track))
    prog = detail.get("radar_progress")
    if prog is not None:
        lines.append(_line("雷达进度", f"{float(prog):.0%}"))
    radar_sl = detail.get("radar_sl") or {}
    if radar_sl.get("expected_sl"):
        status = "✓" if radar_sl.get("live") else "待补挂"
        lines.append(_line("雷达止损", f"@{float(radar_sl['expected_sl']):.2f} {status}"))
    return "\n".join(lines)


def format_radar_arm_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """雷达激活 / 撤销 / 追踪 — 钉钉核实明细."""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    lines = [
        _line("交易所", theme["label"]),
        _line("合约", theme.get("symbol") or sym or "—"),
    ]
    if detail.get("regime") is not None:
        lines.append(_line("档位", f"R{detail['regime']}"))
    if detail.get("entry"):
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("tp1"):
        lines.append(_line("TP1", f"{float(detail['tp1']):.2f}"))
    if detail.get("curr_px"):
        lines.append(_line("现价", f"{float(detail['curr_px']):.2f}"))
    prog = detail.get("radar_progress")
    base = detail.get("radar_activation")
    eff = detail.get("radar_activation_effective") or base
    if prog is not None:
        if base is not None and eff is not None:
            lines.append(
                _line(
                    "路径进度",
                    f"{float(prog):.0%} · 档位需 {float(base):.0%} · 有效需 {float(eff):.0%}",
                )
            )
        else:
            lines.append(_line("路径进度", f"{float(prog):.0%}"))
    if detail.get("tp1_span") is not None:
        lines.append(_line("TP1间距", f"{float(detail['tp1_span']):.2f}"))
    if detail.get("favorable_move") is not None and detail.get("min_abs_move") is not None:
        lines.append(
            _line(
                "有利位移",
                f"{float(detail['favorable_move']):.2f} / 下限 {float(detail['min_abs_move']):.2f}",
            )
        )
    if detail.get("radar_arm_reason"):
        lines.append(_line("启动原因", str(detail["radar_arm_reason"])))
    if detail.get("arm_source"):
        src_labels = {
            "path_tp1": "路径达TP1比例（非TP限价成交）",
            "tp1_filled": "TP1限价成交后强制启动",
            "tp2_filled": "TP2限价成交后强制启动",
            "tp3_filled": "TP3限价成交后强制启动",
            "tp_fill": "止盈成交后强制启动",
        }
        lines.append(
            _line("启动来源", src_labels.get(str(detail["arm_source"]), str(detail["arm_source"])))
        )
    if detail.get("first_arm") is True:
        lines.append(_line("首次启动", "是 · 路径保本雷达"))
    if detail.get("new_sl") or detail.get("radar_sl"):
        sl = detail.get("new_sl") or detail.get("radar_sl")
        lines.append(_line("雷达止损", f"@{float(sl):.2f}"))
    if detail.get("stage_label") or detail.get("radar_stage"):
        lines.append(
            _line(
                "雷达阶段",
                str(detail.get("stage_label") or f"阶段{detail.get('radar_stage')}"),
            )
        )
    if detail.get("reason"):
        lines.append(_line("说明", str(detail["reason"])))
    return "\n".join(lines)


def format_admin_detail_lines(
    alert_type: str,
    detail: dict | None,
    *,
    exchange: str | None = None,
) -> str:
    """将 detail 转为管理员可读中文条目（不再 dump 原始 JSON）。"""
    if not detail:
        return ""
    ex = exchange or detail.get("exchange") or detail.get("exchange_id")

    if alert_type.startswith("CAP_ALIGN"):
        return format_cap_align_detail_cn(detail, ex)
    if alert_type.startswith("ADVERSE_SL"):
        return format_adverse_sl_detail_cn(detail, ex)
    if alert_type in ("CLOSE", "CLOSE_TP3", "CLOSE_PROTECT", "CLOSE_STOPLOSS", "CLOSE_ATTRIBUTION"):
        return format_close_detail_cn(detail, ex)
    if alert_type in ("RADAR_ARM", "RADAR_REVOKE", "TRAIL"):
        return format_radar_arm_detail_cn(detail, ex)
    if alert_type == "STARTUP":
        return format_startup_detail_cn(detail, ex)
    if alert_type == "FORCE_ALIGN":
        return format_force_align_detail_cn(detail, ex)
    if alert_type == "IDLE_WATCH":
        return format_force_align_detail_cn(detail, ex) if detail.get("live_side") else format_startup_detail_cn(detail, ex)
    if alert_type in ("OPEN", "PYRAMID", "PROFIT_ADD", "NOTIONAL_CAP") or detail.get("sizing_mode") in ("vps_open", "vps_add", "vps_open_margin_coeff"):
        return format_vps_entry_detail_cn(detail, ex)
    if alert_type == "UPDATE_TP":
        theme = resolve_exchange_theme(ex, detail.get("symbol") or detail.get("canonical_symbol"))
        side = detail.get("side")
        side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side or "").upper(), side or "—")
        lines = [
            _line("交易所", theme["label"]),
            _line("合约", theme["symbol"]),
            _line("方向", side_txt),
        ]
        if detail.get("qty") is not None:
            lines.append(_line("数量", f"{float(detail['qty']):.4f} {detail.get('qty_unit') or theme['qty_unit']}"))
        if detail.get("mark_price"):
            lines.append(_line("市价", f"{float(detail['mark_price']):.2f}"))
        old_tps = detail.get("old_tv_tps")
        new_tps = detail.get("new_tv_tps") or detail.get("tv_tps")
        if old_tps is not None and new_tps is not None:
            lines.append(_line("TP 升级", f"{old_tps} → {new_tps}"))
        elif new_tps is not None:
            lines.append(_line("新 TP", str(new_tps)))
        if detail.get("cancelled_tp") is not None:
            lines.append(_line("撤销止盈", str(detail["cancelled_tp"])))
        if detail.get("placed_tp") is not None:
            lines.append(_line("新挂止盈", str(detail["placed_tp"])))
        lines.append(_line("硬止损", "未改动" if detail.get("hard_sl_untouched") else "—"))
        lines.append(_line("雷达", "未改动" if detail.get("radar_untouched") else "—"))
        return "\n".join(lines)

    theme = resolve_exchange_theme(ex, detail.get("symbol") or detail.get("canonical_symbol"))
    lines = [_line("交易所", theme["label"]), _line("合约", theme["symbol"])]
    for key, label in (
        ("side", "方向"),
        ("regime", "档位"),
        ("qty", "数量"),
        ("live_qty", "实盘数量"),
        ("entry", "开仓价"),
        ("reason", "原因"),
        ("message", "说明"),
        ("error", "错误"),
    ):
        if detail.get(key) is not None:
            val = detail[key]
            if key == "side":
                val = {"LONG": "做多", "SHORT": "做空"}.get(str(val).upper(), val)
            elif key == "regime":
                val = f"R{val}"
            lines.append(_line(label, str(val)))
    return "\n".join(lines) if len(lines) > 1 else ""


def format_trading_alert_body(
    *,
    theme: dict,
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    user_id: int,
    uid: str,
    display: str,
    detail: dict | None = None,
    exchange: str | None = None,
) -> str:
    sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    ex = exchange or (detail or {}).get("exchange") or (detail or {}).get("exchange_id")
    detail_block = format_admin_detail_lines(alert_type, detail, exchange=ex)

    body = (
        f"{theme['header']}\n"
        f"{sev} **{theme['tag']} [{type_label}]** "
        f"{theme['accent']} {theme['label']} · **{theme.get('symbol_label') or theme['symbol']}** · **{theme['leverage']}×**\n\n"
        f"**合约**：`{theme['symbol']}`（{theme.get('canonical_symbol') or ''}）\n"
        f"**用户**：{display}（UID {uid} / 内部ID {user_id}）\n\n"
        f"**{title}**\n\n"
        f"{message}\n"
    )
    if detail_block:
        body += f"\n**核实明细**\n{detail_block}\n"
    body += f"\n*{theme['brand']} · GEMINI VPS 实盘*"
    return body


def push_trading_alert(
    user_id: int,
    uid: str,
    display: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
    exchange: str | None = None,
) -> None:
    ex = exchange or (detail or {}).get("exchange") or (detail or {}).get("exchange_id")
    sym = (detail or {}).get("symbol") or (detail or {}).get("canonical_symbol")
    theme = resolve_exchange_theme(ex, sym)
    body = format_trading_alert_body(
        theme=theme,
        severity=severity,
        alert_type=alert_type,
        title=title,
        message=message,
        user_id=user_id,
        uid=uid,
        display=display,
        detail=detail,
        exchange=ex,
    )
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    push_dingtalk(f"{theme['tag']} [{type_label}] {title}", body)


def should_push_trading_dingtalk(alert_type: str, severity: str) -> bool:
    if alert_type in DINGTALK_VERBOSE_EXCLUDED:
        return False
    if alert_type in ADMIN_DINGTALK_KEY_TYPES:
        return True
    return severity == "critical"
