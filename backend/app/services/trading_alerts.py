"""DingTalk trading alerts — per-exchange GEMINI themes + 管理员中文可读通知."""

from __future__ import annotations

from datetime import datetime

from app.config import exchange_leverage, get_settings
from app.core.tv_entry_sizing import FIXED_LEVERAGE
from app.services.dingtalk_notify import push_dingtalk

settings = get_settings()

# Leverage always FIXED_LEVERAGE — themes must not seed a second source
_FIXED_LEV = int(FIXED_LEVERAGE)

# GEMINI 量化：各交易所独立 UI 主题（leverage/tag 由 resolve_exchange_theme 注入 FIXED）
EXCHANGE_THEMES: dict[str, dict] = {
    "binance": {
        "label": "币安",
        "symbol": "ETHUSDT",
        "leverage": _FIXED_LEV,
        "brand": "GEMINI量化 · 币安合约实盘引擎",
        "tag": f"#币安{_FIXED_LEV}x",
        "accent": "🔷",
        "palette": "靛蓝",
        "header": "━━ 🔷 GEMINI量化 · 币安 ━━",
        "qty_unit": "ETH",
    },
    "deepcoin": {
        "label": "深币",
        "symbol": "ETH-USDT-SWAP",
        "leverage": _FIXED_LEV,
        "brand": "GEMINI量化 · 深币 SWAP 实盘引擎",
        "tag": f"#深币{_FIXED_LEV}x",
        "accent": "🟢",
        "palette": "翡翠绿",
        "header": "━━ 🟢 GEMINI量化 · 深币 ━━",
        "qty_unit": "张",
    },
    "okx": {
        "label": "OKX",
        "symbol": "ETH-USDT-SWAP",
        "leverage": _FIXED_LEV,
        "brand": "GEMINI量化 · OKX 合约实盘引擎",
        "tag": f"#OKX{_FIXED_LEV}x",
        "accent": "🟣",
        "palette": "紫罗兰",
        "header": "━━ 🟣 GEMINI量化 · OKX ━━",
        "qty_unit": "ETH",
    },
    "gate": {
        "label": "Gate.io",
        "symbol": "ETH_USDT",
        "leverage": _FIXED_LEV,
        "brand": "GEMINI量化 · Gate 合约实盘引擎",
        "tag": f"#Gate{_FIXED_LEV}x",
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
    "CLOSE": "反转保护",
    "CLOSE_TP": "止盈成交",
    "CLOSE_TRAIL": "止损移动",
    "CLOSE_SL_INITIAL": "止损触发",
    "CLOSE_SL_BREAKEVEN": "止损触发",
    "CLOSE_TP3": "TP3 止盈成交",
    "CLOSE_QUICK_EXIT": "反转保护",
    "CLOSE_RSI_EXIT": "反转保护",
    "CLOSE_FAIL": "异常告警",
    "CLOSE_DEFER": "开仓保护忽略CLOSE",
    "STARTUP": "重启恢复",
    "STARTUP_FAIL": "异常告警",
    "DEFENSE_HEAL": "异常告警",
    "DEFENSE_HEAL_OK": "止盈对齐",
    "DEFENSE_HEAL_FAIL": "异常告警",
    "TRAIL": "止损移动",
    "RADAR_ARM": "止损移动",
    "RADAR_REVOKE": "止损移动",
    "BREATH_STEP": "止损移动",
    "BREATH_FLOOR": "止损移动",
    "BREATH_PHASE2": "阶段切换",
    "BREATH_TRAIL": "止损移动",
    "CLOSE_BREATH_STOP": "止损触发",
    "ATR_MISMATCH": "异常告警",
    "ATR_FALLBACK": "异常告警",
    "ATR_ANOMALY": "异常告警",
    "ATR_INVALID": "异常告警",
    "STALE_BAR_TIME": "异常告警",
    "ADJUST": "异常告警",
    "MANUAL_ADJUST": "异常告警",
    "FORCE_ALIGN": "异常告警",
    "TRADING_PAUSED": "异常告警",
    "POSITION_SIDE_FLIP": "异常告警",
    "TP_OVER_COMMIT": "异常告警",
    "IDLE_WATCH": "空仓巡检",
    "MANUAL_FLAT_TP_PURGE": "异常告警",
    "TP_ORPHAN_PURGE": "异常告警",
    "TP_RETRY_FAIL": "异常告警",
    "SL_RETRY_FAIL": "异常告警",
    "SENTINEL_ERROR": "异常告警",
    "INSUFFICIENT_BALANCE": "异常告警",
    "NOTIONAL_CAP": "异常告警",
    "LOCK_TIMEOUT": "异常告警",
    "CLOSE_PROTECT_EMPTY": "异常告警",
    "SAME_DIR_TP_REFRESH": "同向刷新",
    "SAME_DIR_REOPEN": "同向换仓",
    "CAP_ALIGN": "异常告警",
    "CAP_ALIGN_BLOCKED": "异常告警",
    "CAP_ALIGN_FAIL": "异常告警",
    "CAP_ALIGN_OVERTRIM": "异常告警",
    "UPDATE_SL": "止损参数",
    "UPDATE_TP": "止盈更新",
    "TP1_FILL": "TP1 止盈成交",
    "TP2_FILL": "TP2 止盈成交",
    "TP3_FILL": "TP3 止盈成交",
    "HARD_SL_MISSING": "异常告警",
    "SIGNAL_RECV": "TV信号接收",
    "COALESCE_WINDOW": "缓存窗口处理",
    "ADVERSE_SL": "呼吸止损挂载",
    "ADVERSE_SL_DISARM": "呼吸止损接管",
    "ADVERSE_SL_HIT": "止损触发",
    "ADVERSE_SL_MISALIGN": "异常告警",
    "ADVERSE_SL_REPAIR": "异常告警",
    "FALSE_FLAT": "异常告警",
    "CLOSE_ATTRIBUTION": "止盈成交",
    "POSITION_RECONCILE": "异常告警",
    "TP_FILLED": "止盈成交",
    "TP_SKIP_REHANG": "异常告警",
    "POSITION_QTY_CHANGE": "异常告警",
    "FLIP_CLEAN": "先平后开清场",
    "FLIP_CLEAN_ABORT": "异常告警",
    "API_OFFLINE": "异常告警",
}

ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP",
    "CLOSE_TRAIL",
    "CLOSE_SL_INITIAL",
    "CLOSE_SL_BREAKEVEN",
    "CLOSE_TP3",
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
    "CLOSE_FAIL",
    "CLOSE_DEFER",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "TRADING_PAUSED",
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
    "SAME_DIR_TP_REFRESH",
    "SAME_DIR_REOPEN",
    "SENTINEL_ERROR",
    "TP_RETRY_FAIL",
    "SL_RETRY_FAIL",
    "API_OFFLINE",
    "EXCHANGE_QUERY_FAIL",
    "EXCHANGE_QUERY_OK",
    "CAP_ALIGN",
    "CAP_ALIGN_BLOCKED",
    "CAP_ALIGN_FAIL",
    "CAP_ALIGN_OVERTRIM",
    "UPDATE_SL",
    "UPDATE_TP",
    "BREATH_STEP",
    "BREATH_FLOOR",
    "BREATH_PHASE2",
    "BREATH_TRAIL",
    "CLOSE_BREATH_STOP",
    "ADVERSE_SL",
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
    "FLIP_CLEAN_ABORT",
    "TRAIL",
    "ATR_ANOMALY",
    "ATR_INVALID",
    "ATR_MISMATCH",
    "ATR_FALLBACK",
    "STALE_BAR_TIME",
    "HARD_SL_MISSING",
    "CLOSE_PROTECT_EMPTY",
    # Fill / shield lifecycle (info-level must still reach DingTalk)
    "TP1_FILL",
    "TP2_FILL",
    "TP3_FILL",
    "ADVERSE_SL_DISARM",
    "SIGNAL_RECV",
    "COALESCE_WINDOW",
    "CLOSE_ANOMALY",
    "FLAT_UNCONFIRMED",
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


def format_regime_radar_activation_legend() -> str:
    """钉钉：呼吸止损图例（兼容旧调用名）。"""
    from app.core.breathing_stop import format_breathing_legend
    return format_breathing_legend()


def resolve_exchange_theme(
    exchange: str | None = None,
    symbol: str | None = None,
    leverage: int | float | None = None,
) -> dict:
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
    try:
        override = int(round(float(leverage))) if leverage is not None else 0
    except (TypeError, ValueError):
        override = 0
    lev = override if override > 0 else exchange_leverage(key)
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


def _pct_text(val: float | None) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _line(label: str, value: str) -> str:
    return f"- **{label}**：{value}"


def format_checklist_pipe_line(
    *,
    event: str,
    symbol: str = "",
    side: str = "",
    price: float | str | None = None,
    qty: float | str | None = None,
    equity: float | str | None = None,
    remark: str = "",
    ts: datetime | None = None,
) -> str:
    """Checklist §八: 时间戳 | 事件类型 | 合约 | 方向 | 价格 | 数量 | 账户权益 | 备注"""
    when = (ts or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    def _fmt(v) -> str:
        if v is None or v == "":
            return "-"
        try:
            f = float(v)
            if abs(f - int(f)) < 1e-9:
                return str(int(f))
            return f"{f:.4f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(v)

    return " | ".join([
        when,
        str(event or "-"),
        str(symbol or "-"),
        str(side or "-"),
        _fmt(price),
        _fmt(qty),
        _fmt(equity),
        str(remark or "-"),
    ])


def format_signal_received_message(payload: dict | None) -> str:
    from app.core.symbol_registry import extract_payload_symbol

    data = dict(payload or {})
    action = str(data.get("action") or "").upper()
    symbol = extract_payload_symbol(data)
    parts = [f"symbol={symbol}", f"action={action}"]
    if data.get("bot_id"):
        parts.append(f"bot={data.get('bot_id')}")
    if data.get("side"):
        parts.append(f"side={data.get('side')}")
    if data.get("price"):
        parts.append(f"price={data.get('price')}")
    if data.get("stop_loss") or data.get("tv_sl"):
        parts.append(f"stop_loss={data.get('stop_loss') or data.get('tv_sl')}")
    if data.get("tp1") or data.get("tv_tp1"):
        parts.append(f"tp1={data.get('tp1') or data.get('tv_tp1')}")
    if data.get("leg"):
        parts.append(f"leg={data.get('leg')}")
    return "信号已收 · " + " · ".join(parts)


def format_vps_entry_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """妈妈版开仓钉钉短文案."""
    side = detail.get("side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))
    price = detail.get("entry") or detail.get("price") or detail.get("tv_price") or 0
    qty = detail.get("qty") or detail.get("watched_qty") or 0
    init_stop = float(
        detail.get("initial_stop")
        or detail.get("tv_sl")
        or detail.get("stop_loss")
        or detail.get("current_sl")
        or 0
    )
    equity = detail.get("equity") or detail.get("sizing_base") or detail.get("equity_balance") or 0
    msg = (
        f"开仓 {side_txt}，价格 {float(price):.2f}，数量 {float(qty):.4f}，"
        f"初始止损 {init_stop:.2f}，账户权益 {float(equity):.2f}"
    )
    return msg


def format_force_align_detail_cn(detail: dict, exchange: str | None = None) -> str:
    return f"异常告警：FORCE_ALIGN，{detail.get('reason') or detail.get('message') or '方向背离'}"


def format_startup_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """妈妈版重启恢复短文案."""
    side = detail.get("side") or detail.get("current_side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))
    qty = detail.get("qty") or detail.get("live_qty") or detail.get("watched_qty") or 0
    stop_px = detail.get("shield_stop_price") or detail.get("current_sl") or detail.get("tv_sl") or 0
    return (
        f"重启恢复完成，持仓 {side_txt}，数量 {float(qty):.4f}，"
        f"当前止损 {float(stop_px):.2f}"
    )


def format_radar_arm_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """妈妈版止损移动 / 阶段切换短文案."""
    event = str(detail.get("event") or "")
    adx = float(detail.get("adx") or detail.get("current_adx") or 0)
    trail = detail.get("trail_dist_atr")
    if trail is None and isinstance(detail.get("meta"), dict):
        trail = detail["meta"].get("trail_dist_atr")
    new_sl = detail.get("new_sl") or detail.get("current_sl") or 0
    extreme = detail.get("best_price") or detail.get("extreme") or 0
    profit = detail.get("profit_pct") or detail.get("floating_pnl_pct")
    side = str(detail.get("side") or "").upper()
    move = "上移" if side != "SHORT" else "下移"

    if event == "phase2_enter":
        return (
            f"阶段切换：止损已进入阶段二（趋势追踪），"
            f"当前ADX={adx:.1f}，追踪距离={float(trail or 0):.2f}×ATR"
        )
    profit_txt = f"{float(profit):+.2f}" if profit is not None else "—"
    return (
        f"止损{move}至 {float(new_sl):.2f}，当前最高/最低价 {float(extreme):.2f}，"
        f"浮盈 {profit_txt}%"
    )


def format_close_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """妈妈版平仓 / 反转保护 / 止损触发短文案."""
    reason = detail.get("tv_reason") or detail.get("reason") or detail.get("close_reason") or ""
    price = detail.get("exit_price") or detail.get("tv_price") or detail.get("price") or detail.get("curr_px") or 0
    stop = detail.get("current_sl") or detail.get("stop") or detail.get("tv_sl") or 0
    pnl = detail.get("live_pnl_pct") or detail.get("pnl_pct") or detail.get("tv_pnl_pct")
    phase2 = bool(detail.get("breakeven_phase") or detail.get("breakeven_active"))
    action = str(detail.get("close_action") or detail.get("action") or "").upper()
    origin = str(detail.get("close_origin") or (detail.get("attribution") or {}).get("close_origin") or "")
    confidence = str(
        detail.get("attribution_confidence")
        or (detail.get("attribution") or {}).get("confidence")
        or ""
    ).lower()
    pnl_txt = f"{float(pnl):+.2f}" if pnl is not None else "—"

    if "BREATH" in action or detail.get("close_trigger") == "breathing_stop_hit":
        phase = "二" if phase2 else "一"
        return (
            f"止损触发：价格 {float(price):.2f} 触及止损 {float(stop):.2f}，"
            f"阶段 {phase}，盈亏 {pnl_txt}%"
        )
    # Only explicit TV reverse-protect actions — never promote arbitrary reason text
    if "QUICK" in action or "RSI" in action:
        return f"反转保护平仓，原因：{reason or action}，价格 {float(price):.2f}"
    if detail.get("matched_tps") or "TP" in action or origin in ("exchange_limit_tp", "radar_tp3_trail"):
        levels = detail.get("matched_tps") or []
        if not levels and isinstance(detail.get("attribution"), dict):
            levels = detail["attribution"].get("matched_tps") or []
        if 3 in levels or action == "CLOSE_TP3" or origin == "radar_tp3_trail":
            prefix = "（推断）" if confidence in ("inferred", "low") else ""
            return f"{prefix}TP3 止盈成交，全部平仓，盈亏 {pnl_txt}%"
        if 2 in levels:
            return f"TP2 止盈成交，剩余仓位 40%，当前止损 {float(stop):.2f}"
        if 1 in levels:
            return f"TP1 止盈成交，剩余仓位 70%，当前止损 {float(stop):.2f}"
        if origin == "exchange_limit_tp":
            return f"止盈限价成交，盈亏 {pnl_txt}%"
    if confidence in ("insufficient", "low") or origin in ("unknown", "exchange_already_flat"):
        return (
            f"仓位已平（证据不足，原因待核实）：{reason or origin or '未知'}，"
            f"价格 {float(price):.2f}"
        )
    if reason:
        return f"全平完成，说明：{reason}，价格 {float(price):.2f}"
    return f"全平完成，价格 {float(price):.2f}"


def format_tp_fill_detail_cn(detail: dict, alert_type: str = "") -> str:
    stop = float(detail.get("current_sl") or detail.get("stop") or 0)
    pnl = detail.get("pnl_pct") or detail.get("live_pnl_pct")
    level = detail.get("tp_level") or detail.get("level")
    at = str(alert_type or "").upper()
    if level is None:
        if "TP1" in at:
            level = 1
        elif "TP2" in at:
            level = 2
        elif "TP3" in at:
            level = 3
    lvl = int(level or 0)
    if lvl == 1:
        return f"TP1 止盈成交，剩余仓位 70%，当前止损 {stop:.2f}"
    if lvl == 2:
        return f"TP2 止盈成交，剩余仓位 40%，当前止损 {stop:.2f}"
    if lvl == 3:
        pnl_txt = f"{float(pnl):+.2f}" if pnl is not None else "—"
        return f"TP3 止盈成交，全部平仓，盈亏 {pnl_txt}%"
    rem = detail.get("remaining_qty_pct")
    if rem is not None:
        return f"止盈成交，剩余仓位 {float(rem)*100:.0f}%，当前止损 {stop:.2f}"
    return f"止盈成交，当前止损 {stop:.2f}"


def format_cap_align_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """叠仓超标对齐 — 短中文，无 JSON 块."""
    d = dict(detail or {})
    side = str(d.get("side") or "").upper()
    side_cn = "做多" if side == "LONG" else ("做空" if side == "SHORT" else (side or "—"))
    regime = d.get("regime")
    regime_txt = f"R{int(regime)}" if regime is not None else "—"
    live = d.get("live_qty")
    target = d.get("target_qty") or d.get("max_qty") or d.get("new_qty")
    trimmed = d.get("trimmed") or d.get("trim_qty")
    margin_usd = d.get("margin_usd")
    trigger = d.get("trigger") or ""
    parts = [
        f"叠仓对齐 · {side_cn} · {regime_txt}",
    ]
    if live is not None and target is not None:
        parts.append(f"实盘 {float(live):.4g} → 目标 {float(target):.4g}")
    if trimmed is not None:
        parts.append(f"削减 {float(trimmed):.4g}")
    if margin_usd is not None:
        parts.append(f"档位保证金 {float(margin_usd):.2f} USDT")
    if trigger:
        parts.append(f"触发：{trigger}")
    return "，".join(parts)


def format_adverse_sl_detail_cn(detail: dict, exchange: str | None = None) -> str:
    stop = detail.get("stop_price") or detail.get("current_sl") or detail.get("tv_sl") or 0
    return f"呼吸止损挂载 @{float(stop):.2f}"


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
    if alert_type in ("CLOSE", "CLOSE_TP3", "CLOSE_PROTECT", "CLOSE_STOPLOSS", "CLOSE_ATTRIBUTION", "CLOSE_BREATH_STOP", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"):
        return format_close_detail_cn(detail, ex)
    if alert_type in ("RADAR_ARM", "RADAR_REVOKE", "TRAIL", "BREATH_STEP", "BREATH_FLOOR", "BREATH_PHASE2", "BREATH_TRAIL"):
        return format_radar_arm_detail_cn(detail, ex)
    if alert_type == "STARTUP":
        return format_startup_detail_cn(detail, ex)
    if alert_type == "FORCE_ALIGN":
        return format_force_align_detail_cn(detail, ex)
    if alert_type == "IDLE_WATCH":
        return format_startup_detail_cn(detail, ex)
    if alert_type in ("OPEN", "NOTIONAL_CAP") or detail.get("sizing_mode") in (
        "vps_open", "equity20_lev5_notional", "risk20_cap5x_tv_qty_cap",
    ):
        return format_vps_entry_detail_cn(detail, ex)
    if alert_type in ("TP_FILLED", "TP1_FILL", "TP2_FILL", "TP3_FILL"):
        return format_tp_fill_detail_cn(detail, alert_type)
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
    d = dict(detail or {})
    ex = exchange or d.get("exchange") or d.get("exchange_id")
    # Breathing stop close title depends on phase
    resolved_title = title
    if alert_type == "CLOSE_BREATH_STOP":
        phase2 = bool(d.get("breakeven_phase") or d.get("breakeven_active"))
        if "阶段二" in str(message or "") or "趋势追踪" in str(message or ""):
            phase2 = True
        resolved_title = (
            "止损平仓(阶段二/趋势追踪)" if phase2 else "止损平仓(阶段一)"
        )
        type_label = resolved_title
    detail_block = format_admin_detail_lines(alert_type, detail, exchange=ex)

    pipe = format_checklist_pipe_line(
        event=type_label or alert_type,
        symbol=str(theme.get("symbol") or d.get("symbol") or d.get("canonical_symbol") or ""),
        side=str(d.get("side") or d.get("current_side") or ""),
        price=d.get("price") or d.get("mark_price") or d.get("entry") or d.get("curr_px"),
        qty=d.get("qty") or d.get("watched_qty") or d.get("live_qty"),
        equity=d.get("equity") or d.get("sizing_base") or d.get("equity_balance"),
        remark=str(message or resolved_title or "")[:120],
    )

    body = (
        f"`{pipe}`\n\n"
        f"{theme['header']}\n"
        f"{sev} **{theme['tag']} [{type_label}]** "
        f"{theme['accent']} {theme['label']} · **{theme.get('symbol_label') or theme['symbol']}** · **{theme['leverage']}×**\n\n"
        f"**合约**：`{theme['symbol']}`（{theme.get('canonical_symbol') or ''}）\n"
        f"**用户**：{display}（UID {uid} / 内部ID {user_id}）\n\n"
        f"**{resolved_title}**\n\n"
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
    theme = resolve_exchange_theme(ex, sym, leverage=(detail or {}).get("leverage"))
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
