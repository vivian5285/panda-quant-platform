"""Infer why an exchange position went flat (manual vs TP vs TV vs platform)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# close_trigger: how the platform detected / initiated the close
CLOSE_TRIGGERS = {
    "sentinel_zero": "哨兵检测盘口归零",
    "dust_sweep": "蚂蚁仓扫尾",
    "startup_reconcile": "重启账本对账",
    "code_close_all": "平台主动市价全平",
    "qty_change_full": "仓位数量归零",
    "tv_signal": "TV 平仓信号",
    "direction_mismatch": "方向背离强平",
    "idle_patrol": "空闲巡检扫尾",
}

# close_origin: who actually closed on the exchange
CLOSE_ORIGINS = {
    "exchange_limit_tp": "交易所限价止盈成交",
    "exchange_stop": "交易所止损/条件单触发",
    "radar_tp3_trail": "雷达TP3追踪收网",
    "manual_exchange": "交易所端人工操作",
    "platform_market": "平台下发市价平仓单",
    "exchange_already_flat": "盘口已平(平台未发平仓单)",
    "tv_forced": "TV 强制平仓信号",
    "unknown": "未能判定",
}

# close_actor: coarse bucket for dashboards / alerts
CLOSE_ACTORS = {
    "human": "人工",
    "exchange_order": "交易所挂单",
    "platform_code": "平台代码",
    "tv_signal": "TV 信号",
    "unknown": "未知",
}

TV_CLOSE_WINDOW_SEC = 300
ENTRY_NEAR_PCT = 0.003


def classify_vps_sl_kind(
    *,
    activated: bool,
    current_stop: float,
    initial_stop: float,
    side: str | None = None,
) -> str:
    """Checklist §七: CLOSE_SL_INITIAL vs CLOSE_SL_BREAKEVEN."""
    init = float(initial_stop or 0)
    cur = float(current_stop or 0)
    if not activated:
        return "CLOSE_SL_INITIAL"
    if init <= 0 or cur <= 0:
        return "CLOSE_SL_BREAKEVEN"
    side_u = str(side or "").upper()
    if side_u == "LONG" and cur > init + 1e-9:
        return "CLOSE_SL_BREAKEVEN"
    if side_u == "SHORT" and cur < init - 1e-9:
        return "CLOSE_SL_BREAKEVEN"
    if abs(cur - init) <= max(init * 1e-6, 1e-6):
        return "CLOSE_SL_INITIAL"
    return "CLOSE_SL_BREAKEVEN"


def _near_price(a: float, b: float, pct: float = ENTRY_NEAR_PCT) -> bool:
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / a <= pct


def _parse_fill_rows(rows: list[dict], side: str | None) -> list[dict]:
    """Normalize Binance USDT-M fill rows for a closing leg."""
    if not side or side not in ("LONG", "SHORT"):
        return []
    close_side = "SELL" if side == "LONG" else "BUY"
    out: list[dict] = []
    for r in rows or []:
        if str(r.get("side", "")).upper() != close_side:
            continue
        try:
            out.append({
                "price": float(r.get("price", 0) or 0),
                "qty": float(r.get("qty", 0) or 0),
                "maker": bool(r.get("maker")),
                "time_ms": int(r.get("time", 0) or 0),
                "realized_pnl": float(r.get("realizedPnl", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def _sum_fill_qty(fills: list[dict]) -> float:
    return round(sum(f["qty"] for f in fills), 6)


def _avg_fill_price(fills: list[dict]) -> float:
    total_q = _sum_fill_qty(fills)
    if total_q <= 0:
        return 0.0
    return round(sum(f["price"] * f["qty"] for f in fills) / total_q, 4)


def _tv_close_recent(recent_tv: dict | None) -> bool:
    if not recent_tv:
        return False
    action = str(recent_tv.get("action") or "").upper()
    if not action.startswith("CLOSE"):
        return False
    created = recent_tv.get("created_at")
    if not created:
        return True
    try:
        ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        return age <= timedelta(seconds=TV_CLOSE_WINDOW_SEC)
    except (TypeError, ValueError):
        return True


def _closing_leg_fills(fills: list[dict], target_qty: float, qty_tol: float | None = None) -> list[dict]:
    """Most recent closing fills that sum to ~target_qty (ignore earlier TP1 legs)."""
    if not fills or target_qty <= 0:
        return list(fills or [])
    tol = qty_tol if qty_tol is not None else max(target_qty * 0.12, 0.001)
    sorted_f = sorted(fills, key=lambda x: x.get("time_ms", 0), reverse=True)
    picked: list[dict] = []
    acc = 0.0
    for f in sorted_f:
        picked.append(f)
        acc += f["qty"]
        if acc >= target_qty - tol:
            break
    return picked


def _match_tp_prices(fills: list[dict], tv_tps: list, entry: float = 0.0) -> list[int]:
    """Match fill prices to TP tiers — adaptive tol so near-entry fills ≠ TP1."""
    matched: list[int] = []
    entry_f = float(entry or 0)
    for level, tp in enumerate(tv_tps[:3], start=1):
        if not tp or float(tp) <= 0:
            continue
        tp_f = float(tp)
        # Default 0.15%; when TP is close to entry, shrink to ≤25% of entry→TP span
        tol_pct = 0.0015
        if entry_f > 0:
            span = abs(tp_f - entry_f)
            if span > 0:
                span_pct = span / entry_f
                tol_pct = min(0.0015, max(0.0002, span_pct * 0.25))
        for f in fills:
            if _near_price(f["price"], tp_f, pct=tol_pct):
                matched.append(level)
                break
    return matched


def _near_stop_price(avg_px: float, stop_px: float, pct: float = 0.008) -> bool:
    if avg_px <= 0 or stop_px <= 0:
        return False
    return abs(avg_px - stop_px) / stop_px <= pct


def _is_loss_side_exit(side: str | None, entry: float, avg_px: float) -> bool:
    if entry <= 0 or avg_px <= 0 or side not in ("LONG", "SHORT"):
        return False
    if side == "LONG":
        return avg_px < entry * (1 - ENTRY_NEAR_PCT)
    return avg_px > entry * (1 + ENTRY_NEAR_PCT)


def diagnose_flat_close(
    *,
    client,
    symbol: str,
    side: str | None,
    qty: float,
    entry: float,
    trade_opened_at: float | None,
    consumed_tp_levels: list,
    tv_tps: list,
    trigger: str,
    had_position_before_close: bool,
    recent_tv_close: dict | None = None,
    radar_active: bool = False,
    current_sl: float = 0.0,
    initial_stop: float = 0.0,
    platform_initiated_market: bool = False,
    peak_price: float = 0.0,
    exit_price: float = 0.0,
) -> dict[str, Any]:
    """
    Build structured close attribution for logs, DB detail_json, and DingTalk.
    """
    trigger_key = trigger if trigger in CLOSE_TRIGGERS else "sentinel_zero"
    tps = list(tv_tps or [])
    tp3 = float(tps[2] or 0) if len(tps) > 2 else 0.0
    peak = float(peak_price or 0)
    evidence: dict[str, Any] = {
        "trigger": trigger_key,
        "had_position_before_close": had_position_before_close,
        "platform_initiated_market": platform_initiated_market,
        "radar_active": radar_active,
        "current_sl": float(current_sl or 0),
        "initial_stop": float(initial_stop or 0),
        "consumed_tp_levels": list(consumed_tp_levels or []),
        "peak_price": peak,
        "tp3": tp3,
    }
    sl_kind = classify_vps_sl_kind(
        activated=bool(radar_active),
        current_stop=float(current_sl or 0),
        initial_stop=float(initial_stop or 0),
        side=side,
    )
    evidence["sl_kind"] = sl_kind

    def _reached_tp3(px: float) -> bool:
        if tp3 <= 0 or px <= 0:
            return False
        if side == "LONG":
            return px + 1e-9 >= tp3
        if side == "SHORT":
            return px - 1e-9 <= tp3
        return False

    peak_hit_tp3 = _reached_tp3(peak) or _reached_tp3(float(exit_price or 0))
    evidence["peak_hit_tp3"] = peak_hit_tp3

    fills: list[dict] = []
    leg_fills: list[dict] = []
    start_ms = int(trade_opened_at * 1000) if trade_opened_at else None
    if client and hasattr(client, "get_account_trades"):
        try:
            rows = client.get_account_trades(symbol, start_time_ms=start_ms, limit=200)
            fills = _parse_fill_rows(rows, side)
            leg_fills = _closing_leg_fills(fills, float(qty or 0))
            evidence["closing_fill_count"] = len(leg_fills)
            evidence["closing_fill_qty"] = _sum_fill_qty(leg_fills)
            evidence["closing_avg_price"] = _avg_fill_price(leg_fills)
        except Exception as e:
            logger.debug("fill fetch for attribution failed: %s", e)
            evidence["fill_fetch_error"] = str(e)

    tv_recent = _tv_close_recent(recent_tv_close)
    evidence["tv_close_recent"] = tv_recent
    if recent_tv_close:
        evidence["latest_tv_action"] = recent_tv_close.get("action")
        evidence["latest_tv_at"] = recent_tv_close.get("created_at")

    tp_matched = _match_tp_prices(leg_fills, tps, entry=float(entry or 0))
    evidence["tp_price_matches"] = tp_matched

    avg_px = float(evidence.get("closing_avg_price") or exit_price or 0.0)
    if peak_hit_tp3 and not _reached_tp3(avg_px) and avg_px > 0:
        # Exit may be on trail stop below TP3 after peak hit — still TP3 regime
        pass
    near_entry = _near_price(avg_px, entry) if avg_px > 0 and entry > 0 else False
    near_stop = _near_stop_price(avg_px, float(current_sl or 0))
    loss_side = _is_loss_side_exit(side, entry, avg_px)
    evidence["exit_near_entry"] = near_entry
    evidence["exit_near_stop"] = near_stop
    evidence["exit_loss_side"] = loss_side

    origin = "unknown"
    actor = "unknown"
    human_reason = CLOSE_TRIGGERS.get(trigger_key, trigger_key)
    close_action_hint = None
    confidence = "insufficient"

    # Checklist 9.6: TP3 radar trail — only when peak AND exit evidence supports it
    tp3_exit_confirmed = bool(
        peak_hit_tp3
        and radar_active
        and (
            _reached_tp3(avg_px)
            or near_stop
            or (leg_fills and _near_stop_price(avg_px, float(current_sl or 0), pct=0.015))
        )
    )
    evidence["tp3_exit_confirmed"] = tp3_exit_confirmed

    if tp3_exit_confirmed:
        origin = "radar_tp3_trail"
        actor = "exchange_order" if not platform_initiated_market else "platform_code"
        human_reason = (
            f"TP3平仓（雷达追踪）·峰值@{peak:.2f}≥TP3@{tp3:.2f}"
            if side == "LONG"
            else f"TP3平仓（雷达追踪）·极值@{peak:.2f}≤TP3@{tp3:.2f}"
        )
        close_action_hint = "CLOSE_TP3"
        confidence = "confirmed" if _reached_tp3(avg_px) else "inferred"
    elif peak_hit_tp3 and radar_active and not tp3_exit_confirmed:
        # Peak touched TP3 but exit evidence weak — do not assert TP3 title
        origin = "unknown"
        actor = "unknown"
        human_reason = (
            f"峰值曾过TP3@{tp3:.2f}，但平仓成交证据不足（均价 {avg_px:.2f}），原因待核实"
        )
        confidence = "insufficient"
    elif platform_initiated_market:
        origin = "platform_market"
        actor = "platform_code"
        human_reason = f"平台代码主动市价全平（{CLOSE_TRIGGERS.get(trigger_key, trigger_key)}）"
        confidence = "confirmed"
    elif tv_recent and trigger_key in ("tv_signal", "code_close_all"):
        origin = "tv_forced"
        actor = "tv_signal"
        human_reason = "TV 平仓信号触发平台全平"
        confidence = "confirmed"
    elif not had_position_before_close:
        if tv_recent:
            origin = "tv_forced"
            actor = "tv_signal"
            human_reason = "盘口已平：近期有 TV 平仓信号，疑为 TV 驱动或跟随成交"
            confidence = "inferred"
        # Prefer stop/radar when exit hugs entry+radar SL (avoid false TP1 from loose tol)
        elif (radar_active or near_stop) and near_stop and (near_entry or loss_side):
            origin = "exchange_stop"
            actor = "exchange_order"
            sl_note = f"@{current_sl:.2f}" if current_sl else ""
            if sl_kind == "CLOSE_SL_INITIAL":
                human_reason = f"止损平仓（初始）{sl_note}（均价 {avg_px:.2f}）"
            else:
                human_reason = f"止损平仓（保本/移动）{sl_note}（均价 {avg_px:.2f}）"
            close_action_hint = sl_kind
            confidence = "confirmed"
        elif tp_matched:
            origin = "exchange_limit_tp"
            actor = "exchange_order"
            human_reason = f"盘口已平：交易所限价止盈成交（TP{tp_matched}）"
            confidence = "confirmed"
        elif (radar_active or near_stop) and (loss_side or near_stop):
            origin = "exchange_stop"
            actor = "exchange_order"
            sl_note = f"@{current_sl:.2f}" if current_sl else ""
            if sl_kind == "CLOSE_SL_INITIAL":
                human_reason = f"止损平仓（初始）{sl_note}（均价 {avg_px:.2f}）"
            else:
                human_reason = f"止损平仓（保本/移动）{sl_note}（均价 {avg_px:.2f}）"
            close_action_hint = sl_kind
            confidence = "inferred"
        elif near_entry and not radar_active:
            origin = "manual_exchange"
            actor = "human"
            human_reason = (
                "盘口已平：成交价接近开仓价且雷达未激活，"
                "疑为交易所端人工平仓或手动市价/限价平仓"
            )
            confidence = "inferred"
        elif leg_fills and any(not f["maker"] for f in leg_fills):
            origin = "unknown"
            actor = "unknown"
            human_reason = (
                "盘口已平：检测到市价吃单成交，但缺少止损/TP/TV 证据，原因待核实"
            )
            confidence = "insufficient"
        elif leg_fills and all(f["maker"] for f in leg_fills):
            # Maker-only is NOT enough to claim TP — require price match (handled above)
            origin = "unknown"
            actor = "unknown"
            human_reason = (
                "盘口已平：检测到限价挂单成交，但未匹配到 TP 价位，原因待核实"
            )
            confidence = "insufficient"
        else:
            origin = "exchange_already_flat"
            actor = "unknown"
            human_reason = (
                "哨兵检测盘口归零，但平台未发平仓单；"
                "未能从成交记录判定原因（可能 API 延迟或成交窗口外）"
            )
            confidence = "insufficient"
    else:
        # had_position_before_close=True: only assert platform_market when we truly initiated
        if platform_initiated_market:
            origin = "platform_market"
            actor = "platform_code"
            human_reason = f"平台下发市价单全平（{CLOSE_TRIGGERS.get(trigger_key, trigger_key)}）"
            confidence = "confirmed"
            if tp3_exit_confirmed:
                origin = "radar_tp3_trail"
                close_action_hint = "CLOSE_TP3"
                human_reason = "TP3平仓（雷达追踪）·平台市价收网"
                confidence = "inferred"
        else:
            origin = "unknown"
            actor = "unknown"
            human_reason = (
                f"平台检测到仓位关闭（触发={CLOSE_TRIGGERS.get(trigger_key, trigger_key)}），"
                "但未确认主动市价单，原因待核实"
            )
            confidence = "insufficient"

    if origin == "unknown" and confidence == "confirmed":
        confidence = "insufficient"
    if origin == "unknown" and near_entry and not radar_active and confidence != "insufficient":
        origin = "manual_exchange"
        actor = "human"
        human_reason = "成交价接近开仓价，疑为人工平仓（雷达未启动）"
        confidence = "inferred"

    if close_action_hint is None and origin == "exchange_stop":
        close_action_hint = sl_kind

    CLOSE_ORIGINS_LOCAL = dict(CLOSE_ORIGINS)
    CLOSE_ORIGINS_LOCAL["radar_tp3_trail"] = "雷达TP3追踪收网"

    return {
        "close_trigger": trigger_key,
        "close_origin": origin,
        "close_actor": actor,
        "human_reason": human_reason,
        "origin_label": CLOSE_ORIGINS.get(origin, origin),
        "trigger_label": CLOSE_TRIGGERS.get(trigger_key, trigger_key),
        "actor_label": CLOSE_ACTORS.get(actor, actor),
        "sl_kind": sl_kind if origin == "exchange_stop" else None,
        "close_action_hint": close_action_hint,
        "confidence": confidence,
        "evidence": evidence,
        "matched_tps": tp_matched if origin == "exchange_limit_tp" else [],
        "anomaly": (
            origin in ("unknown", "exchange_already_flat")
            or confidence == "insufficient"
        ) and not had_position_before_close,
    }


def format_close_reason(attribution: dict[str, Any]) -> str:
    """Single-line reason for Trade.action / alerts."""
    human = attribution.get("human_reason") or ""
    origin = attribution.get("origin_label") or attribution.get("close_origin") or ""
    if human and origin:
        return f"{human} [{origin}]"
    return human or origin or "仓位已平"
