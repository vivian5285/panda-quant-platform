"""TV 全平信号 — 分类、明细字段、核实后钉钉文案（四家交易所共用）."""

from __future__ import annotations

from typing import Any


def parse_tv_pnl_pct(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def extract_tv_close_fields(payload: dict | None) -> dict[str, Any]:
    """Normalize Pine v6.9.75 精准风控 CLOSE_* webhook fields."""
    data = dict(payload or {})
    reason = str(data.get("reason") or "").strip()
    side = str(data.get("side") or "").upper().strip() or None
    regime = data.get("regime")
    try:
        regime = int(regime) if regime is not None and str(regime).strip() != "" else None
    except (TypeError, ValueError):
        regime = None
    atr = data.get("atr")
    try:
        atr = round(float(atr), 4) if atr is not None and str(atr).strip() != "" else None
    except (TypeError, ValueError):
        atr = None
    price = data.get("price")
    try:
        price = round(float(price), 2) if price is not None and str(price).strip() != "" else None
    except (TypeError, ValueError):
        price = None
    return {
        "close_action": str(data.get("action") or "").upper().strip() or None,
        "tv_reason": reason,
        "tv_side": side,
        "tv_pnl_pct": parse_tv_pnl_pct(data.get("pnl_pct")),
        "tv_price": price,
        "tv_regime": regime,
        "tv_atr": atr,
    }


def classify_tv_close_subtype(close_action: str | None, tv_reason: str | None) -> str:
    """breakeven | hard_stop | risk_intercept | tp3 | protect | generic."""
    action = str(close_action or "").upper()
    reason = str(tv_reason or "")
    if "CLOSE_TP3" in action:
        return "tp3"
    if "CLOSE_STOPLOSS" in action:
        if "防回吐" in reason or "保本" in reason:
            return "breakeven"
        if "硬止损" in reason:
            return "hard_stop"
        return "stoploss"
    if "CLOSE_PROTECT" in action or action.startswith("CLOSE_PROTECT"):
        if "风控拦截" in reason or "高优拦截" in reason:
            return "risk_intercept"
        return "protect"
    if action == "CLOSE":
        return "generic"
    return "generic"


def resolve_close_alert_type(
    close_action: str | None,
    tv_reason: str | None,
    attribution: dict | None = None,
) -> str:
    action = str(close_action or "").upper()
    if "CLOSE_QUICK_EXIT" in action:
        return "CLOSE_QUICK_EXIT"
    if "CLOSE_RSI_EXIT" in action:
        return "CLOSE_RSI_EXIT"
    if action in ("CLOSE_TP", "CLOSE_TRAIL", "CLOSE_SL_INITIAL", "CLOSE_SL_BREAKEVEN", "CLOSE_TP3"):
        return action
    hint = str((attribution or {}).get("close_action_hint") or (attribution or {}).get("sl_kind") or "")
    if hint == "CLOSE_TP3" or (attribution or {}).get("close_origin") == "radar_tp3_trail":
        return "CLOSE_TP3"
    if hint in ("CLOSE_SL_INITIAL", "CLOSE_SL_BREAKEVEN"):
        return hint
    subtype = classify_tv_close_subtype(action, tv_reason)
    if subtype == "tp3" or "CLOSE_TP3" in action:
        return "CLOSE_TP3"
    if subtype in ("breakeven", "hard_stop", "stoploss") or "CLOSE_STOPLOSS" in action:
        return "CLOSE_STOPLOSS"
    if "CLOSE_PROTECT" in action or action.startswith("CLOSE_PROTECT"):
        return "CLOSE_PROTECT"
    origin = str((attribution or {}).get("close_origin") or "")
    if origin == "exchange_limit_tp":
        return "CLOSE_ATTRIBUTION"
    if origin == "exchange_stop":
        return (
            "CLOSE_SL_BREAKEVEN"
            if (attribution or {}).get("sl_kind") == "CLOSE_SL_BREAKEVEN"
            else "CLOSE_SL_INITIAL"
        )
    return "CLOSE"


def resolve_close_alert_title(
    close_action: str | None,
    tv_reason: str | None,
    attribution: dict | None = None,
) -> str:
    hint = str((attribution or {}).get("close_action_hint") or (attribution or {}).get("sl_kind") or "")
    act = str(close_action or "").upper()
    origin = str((attribution or {}).get("close_origin") or "")
    if hint == "CLOSE_TP3" or origin == "radar_tp3_trail" or act == "CLOSE_TP3":
        return "TP3平仓 · 雷达追踪收网"
    if hint == "CLOSE_SL_INITIAL" or act == "CLOSE_SL_INITIAL":
        return "止损平仓（初始）"
    if hint == "CLOSE_SL_BREAKEVEN" or act == "CLOSE_SL_BREAKEVEN":
        return "止损平仓（保本/移动）"
    subtype = classify_tv_close_subtype(close_action, tv_reason)
    titles = {
        "tp3": "TP3平仓 · 雷达追踪收网",
        "breakeven": "防回吐保本 · 全平完成",
        "hard_stop": "硬止损 · 全平完成",
        "stoploss": "TV止损 · 全平完成",
        "risk_intercept": "风控拦截 · 保护全平",
        "protect": "保护性全平 · 完成",
        "generic": "全平完成",
    }
    if subtype != "generic" or close_action:
        return titles.get(subtype, "全平完成")
    # No TV close action — prefer exchange attribution (TP fill vs radar/stop)
    matched = (attribution or {}).get("matched_tps") or []
    if origin == "exchange_limit_tp":
        if matched:
            levels = ",".join(str(x) for x in matched)
            return f"限价止盈成交·TP{levels} · 全平"
        return "限价止盈成交 · 全平"
    if origin == "exchange_stop":
        if (attribution or {}).get("sl_kind") == "CLOSE_SL_INITIAL":
            return "止损平仓（初始）"
        return "止损平仓（保本/移动）"
    if origin == "manual_exchange":
        return "交易所人工平仓 · 全平"
    if origin == "tv_forced":
        return "TV强制平仓 · 全平"
    human = str((attribution or {}).get("human_reason") or "").strip()
    if human:
        return f"{human[:40]} · 全平"
    return "全平完成"


def build_verify_note(
    *,
    exit_price: float | None,
    live_pnl_pct: float | None,
    tv_pnl_pct: float | None,
    flat_confirmed: bool = True,
) -> str:
    parts = ["盘口已归零" if flat_confirmed else "盘口核实中"]
    if exit_price:
        parts.append(f"平仓价 @{float(exit_price):.2f}")
    if live_pnl_pct is not None:
        parts.append(f"实盘盈亏 {live_pnl_pct:+.2f}%")
    if tv_pnl_pct is not None:
        parts.append(f"TV报 {tv_pnl_pct:+.2f}%")
    if tv_pnl_pct is not None and live_pnl_pct is not None:
        delta = round(live_pnl_pct - float(tv_pnl_pct), 2)
        if abs(delta) > 0.15:
            parts.append(f"偏差 {delta:+.2f}%")
    return " | ".join(parts)


def build_close_detail(
    *,
    exchange_id: str,
    side: str | None,
    qty: float,
    entry: float,
    regime: int | None,
    atr: float | None,
    exit_price: float | None,
    pnl: float,
    funding_fee: float,
    tv_fields: dict[str, Any] | None,
    close_action: str | None,
    tv_reason: str | None,
    live_pnl_pct: float | None,
    verify_note: str,
    attribution: dict | None = None,
    trade_id: int | None = None,
) -> dict[str, Any]:
    tv = dict(tv_fields or {})
    detail: dict[str, Any] = {
        "exchange": exchange_id,
        "exchange_id": exchange_id,
        "close_action": close_action or tv.get("close_action"),
        "close_subtype": classify_tv_close_subtype(close_action or tv.get("close_action"), tv_reason or tv.get("tv_reason")),
        "reason": tv_reason or tv.get("tv_reason") or "",
        "tv_reason": tv_reason or tv.get("tv_reason") or "",
        "side": side,
        "qty": qty,
        "entry": entry,
        "exit_price": exit_price,
        "pnl": round(float(pnl or 0), 4),
        "funding_fee": funding_fee,
        "regime": regime if regime is not None else tv.get("tv_regime"),
        "atr": atr if atr is not None else tv.get("tv_atr"),
        "tv_price": tv.get("tv_price"),
        "tv_side": tv.get("tv_side"),
        "tv_pnl_pct": tv.get("tv_pnl_pct"),
        "live_pnl_pct": live_pnl_pct,
        "verify_note": verify_note,
        "live_verified": True,
    }
    if tv.get("tv_pnl_pct") is not None and live_pnl_pct is not None:
        detail["pnl_pct_delta"] = round(live_pnl_pct - float(tv["tv_pnl_pct"]), 2)
    if tv.get("tv_side") and side and str(tv["tv_side"]).upper() != str(side).upper():
        detail["tv_side_mismatch"] = True
    if attribution:
        detail["close_trigger"] = attribution.get("close_trigger")
        detail["close_origin"] = attribution.get("close_origin")
        detail["close_actor"] = attribution.get("close_actor")
        detail["human_reason"] = attribution.get("human_reason")
        detail["attribution"] = attribution
    if trade_id:
        detail["trade_id"] = trade_id
    return detail


def format_close_dingtalk_message(tv_reason: str | None, verify_note: str) -> str:
    head = (tv_reason or "").strip() or "全平"
    return f"{head} | {verify_note}"
