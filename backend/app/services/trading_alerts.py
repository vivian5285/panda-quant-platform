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
    "STARTUP": "重启接管",
    "STARTUP_FAIL": "接管失败",
    "DEFENSE_HEAL": "止盈对齐修复",
    "DEFENSE_HEAL_OK": "止盈已对齐",
    "DEFENSE_HEAL_FAIL": "止盈仍异常",
    "TRAIL": "雷达保本",
    "ADJUST": "人工异动",
    "MANUAL_ADJUST": "人工异动",
    "FORCE_ALIGN": "方向背离",
    "TP_RETRY_FAIL": "止盈失败",
    "SL_RETRY_FAIL": "止损失败",
    "SENTINEL_ERROR": "哨兵异常",
    "INSUFFICIENT_BALANCE": "余额不足",
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
    "UPDATE_SL": "TV硬止损更新",
    "SIGNAL_RECV": "TV信号接收",
    "ADVERSE_SL": "TV硬止损",
    "ADVERSE_SL_DISARM": "防护盾撤销·雷达接管",
    "ADVERSE_SL_HIT": "TV硬止损触发",
    "ADVERSE_SL_MISALIGN": "TV硬止损未对齐",
    "ADVERSE_SL_REPAIR": "逆势止损补挂",
    "FALSE_FLAT": "误报空仓",
    "CLOSE_ATTRIBUTION": "平仓归因",
    "API_OFFLINE": "API离线",
}

ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP3",
    "CLOSE_PROTECT",
    "CLOSE_STOPLOSS",
    "CLOSE_FAIL",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "ADJUST",
    "MANUAL_ADJUST",
    "INSUFFICIENT_BALANCE",
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
    "ADVERSE_SL",
    "ADVERSE_SL_DISARM",
    "ADVERSE_SL_HIT",
    "ADVERSE_SL_MISALIGN",
    "FALSE_FLAT",
    "CLOSE_ATTRIBUTION",
})

DINGTALK_VERBOSE_EXCLUDED = frozenset({
    "DEFENSE_HEAL",
    "DEFENSE_HEAL_OK",
    "DEFENSE",
    "DEFENSE_AUDIT",
    "DEFENSE_FAIL",
    "TRAIL",
    "TP_RETRY",
    "SIGNAL",
    "ADVERSE_SL_REPAIR",
    "RECOVERY",
})


def resolve_exchange_theme(exchange: str | None = None) -> dict:
    key = (exchange or "binance").strip().lower()
    if key == "gateio":
        key = "gate"
    base = dict(EXCHANGE_THEMES.get(key, DEFAULT_THEME))
    lev = exchange_leverage(key)
    prefix = _EXCHANGE_TAG_PREFIX.get(key, "币安")
    base["leverage"] = lev
    base["tag"] = f"#{prefix}{lev}x" if prefix != "OKX" else f"#OKX{lev}x"
    return base


def qty_unit_for_exchange(exchange: str | None) -> str:
    return resolve_exchange_theme(exchange).get("qty_unit", "ETH")


def format_signal_received_message(payload: dict | None) -> str:
    data = dict(payload or {})
    action = str(data.get("action") or "").upper()
    entry_type = str(data.get("entry_type") or "").upper()
    parts = [f"action={action}"]
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
    theme = resolve_exchange_theme(exchange or detail.get("exchange"))
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

    principal = detail.get("initial_principal") or detail.get("sizing_base")
    if principal:
        lines.append(_line("本金快照", f"{float(principal):.2f} USDT"))
    if detail.get("equity_balance"):
        lines.append(_line("合约总权益", f"{float(detail['equity_balance']):.2f} USDT"))
    if detail.get("margin_usd"):
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
    theme = resolve_exchange_theme(exchange or detail.get("exchange"))
    unit = qty_unit_for_exchange(exchange or detail.get("exchange"))
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
    theme = resolve_exchange_theme(exchange or detail.get("exchange"))
    unit = qty_unit_for_exchange(exchange or detail.get("exchange"))
    lines = [_line("交易所", theme["label"])]
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
    return "\n".join(lines)


def format_vps_entry_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 开仓/加仓 — 风险系数口径（非档位保证金百分比）."""
    theme = resolve_exchange_theme(exchange or detail.get("exchange"))
    unit = theme["qty_unit"]
    entry_type = str(detail.get("entry_type") or "OPEN").upper()
    regime = detail.get("regime")
    regime_txt = f"R{regime}" if regime else "—"
    side = detail.get("side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))

    lines = [
        _line("交易所", theme["label"]),
        _line("类型", {"OPEN": "首次开仓", "PYRAMID": "加仓", "PROFIT_ADD": "浮盈加仓"}.get(entry_type, entry_type)),
        _line("方向", side_txt),
        _line("档位", regime_txt),
    ]

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
            lines.append(_line("下单名义", f"{float(detail['order_amount']):.2f} USDT × {lev}×杠杆"))
        if detail.get("sl_distance") is not None:
            lines.append(_line("止损距离", f"{float(detail['sl_distance']):.2f}"))
        if detail.get("base_qty") is not None:
            lines.append(_line("基准数量", f"**{float(detail['base_qty']):.4f}** {unit}"))
    else:
        if detail.get("base_qty") is not None:
            lines.append(_line("首次基准", f"{float(detail['base_qty']):.4f} {unit}"))
        ratio = detail.get("add_qty_ratio") or detail.get("qty_ratio")
        if ratio is not None:
            lines.append(_line("加仓比例", f"VPS 固定 {float(ratio):.2f}"))
        if detail.get("add_qty") is not None:
            lines.append(_line("本次加仓", f"**{float(detail['add_qty']):.4f}** {unit}"))
        if detail.get("add_count") is not None:
            cap = detail.get("max_add_times")
            if cap:
                lines.append(_line("加仓次数", f"{int(detail['add_count'])}/{int(cap)}"))
            else:
                lines.append(_line("加仓次数", str(detail["add_count"])))

    if detail.get("qty") is not None:
        lines.append(_line("实盘数量", f"**{float(detail['qty']):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("tv_sl"):
        lines.append(_line("TV 止损", f"{float(detail['tv_sl']):.2f}"))

    return "\n".join(lines)


def format_startup_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 重启接管 — TP123 / 硬止损 / 雷达进度."""
    theme = resolve_exchange_theme(exchange or detail.get("exchange"))
    unit = theme["qty_unit"]
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
    if detail.get("startup_summary"):
        lines.append(_line("对账摘要", str(detail["startup_summary"])))
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
    if alert_type == "STARTUP":
        return format_startup_detail_cn(detail, ex)
    if alert_type in ("OPEN", "PYRAMID", "PROFIT_ADD") or detail.get("sizing_mode") in ("vps_open", "vps_add"):
        return format_vps_entry_detail_cn(detail, ex)

    theme = resolve_exchange_theme(ex)
    lines = [_line("交易所", theme["label"])]
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
        f"{theme['accent']} {theme['label']} {theme['symbol']} · **{theme['leverage']}×**\n\n"
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
    theme = resolve_exchange_theme(ex)
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
