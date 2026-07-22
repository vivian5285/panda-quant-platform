"""TV 全平信号 — 妈妈版分类与钉钉标题（四所共用）."""

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
    """quick_exit | rsi_exit | breath_stop | tp | generic — no legacy protect keywords."""
    action = str(close_action or "").upper()
    if "CLOSE_QUICK_EXIT" in action:
        return "quick_exit"
    if "CLOSE_RSI_EXIT" in action:
        return "rsi_exit"
    if "CLOSE_BREATH" in action or "BREATH_STOP" in action:
        return "breath_stop"
    if "CLOSE_TP" in action or "TP3" in action:
        return "tp"
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
    if "CLOSE_BREATH" in action:
        return "CLOSE_BREATH_STOP"
    hint = str((attribution or {}).get("close_action_hint") or (attribution or {}).get("sl_kind") or "")
    origin = str((attribution or {}).get("close_origin") or "")
    if hint == "CLOSE_TP3" or origin in ("radar_tp3_trail", "exchange_limit_tp"):
        return "CLOSE_TP3" if hint == "CLOSE_TP3" or origin == "radar_tp3_trail" else "CLOSE_ATTRIBUTION"
    if origin == "breathing_stop" or (attribution or {}).get("close_trigger") == "breathing_stop_hit":
        return "CLOSE_BREATH_STOP"
    if origin == "exchange_stop":
        return "CLOSE_BREATH_STOP"
    # Legacy CLOSE_PROTECT / STOPLOSS → generic reverse-protect wording only
    if "CLOSE_PROTECT" in action or "CLOSE_STOPLOSS" in action:
        return "CLOSE"
    return "CLOSE"


def resolve_close_alert_title(
    close_action: str | None,
    tv_reason: str | None,
    attribution: dict | None = None,
) -> str:
    act = str(close_action or "").upper()
    hint = str((attribution or {}).get("close_action_hint") or (attribution or {}).get("sl_kind") or "")
    origin = str((attribution or {}).get("close_origin") or "")
    reason = str(tv_reason or (attribution or {}).get("human_reason") or "").strip()

    if hint == "CLOSE_TP3" or origin == "radar_tp3_trail" or act == "CLOSE_TP3":
        return "余仓止盈（阶段二）"
    if act == "CLOSE_BREATH_STOP" or origin == "breathing_stop":
        phase2 = bool(
            (attribution or {}).get("breakeven_phase")
            or (attribution or {}).get("breakeven_active")
            or "阶段二" in reason
            or "趋势追踪" in reason
        )
        return "止损平仓(阶段二/趋势追踪)" if phase2 else "止损平仓(阶段一)"
    if "CLOSE_QUICK_EXIT" in act:
        return "反转保护"
    if "CLOSE_RSI_EXIT" in act:
        return "反转保护"
    if origin == "exchange_limit_tp":
        matched = (attribution or {}).get("matched_tps") or []
        if matched:
            return f"TP{','.join(str(x) for x in matched)} 止盈成交"
        return "止盈成交"
    if origin == "exchange_stop":
        return "止损平仓(阶段一)"
    if reason:
        return "反转保护平仓"
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
    return " · ".join(parts)


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
        "close_subtype": classify_tv_close_subtype(
            close_action or tv.get("close_action"), tv_reason or tv.get("tv_reason"),
        ),
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
    return f"{head} · {verify_note}"


def format_tv_close_detail_lines(detail: dict | None) -> list[str]:
    d = dict(detail or {})
    lines = []
    reason = d.get("tv_reason") or d.get("reason") or ""
    price = d.get("tv_price") or d.get("price") or d.get("exit_price")
    if reason:
        lines.append(f"- **原因**：{reason}")
    if price:
        try:
            lines.append(f"- **价格**：{float(price):.2f}")
        except (TypeError, ValueError):
            lines.append(f"- **价格**：{price}")
    return lines
