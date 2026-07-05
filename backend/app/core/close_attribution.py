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


def _match_tp_prices(fills: list[dict], tv_tps: list, consumed: list) -> list[int]:
    matched: list[int] = []
    for level, tp in enumerate(tv_tps[:3], start=1):
        if level in consumed and tp and tp > 0:
            for f in fills:
                if _near_price(f["price"], float(tp), pct=0.0015):
                    matched.append(level)
                    break
    return matched


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
    platform_initiated_market: bool = False,
) -> dict[str, Any]:
    """
    Build structured close attribution for logs, DB detail_json, and DingTalk.
    """
    trigger_key = trigger if trigger in CLOSE_TRIGGERS else "sentinel_zero"
    evidence: dict[str, Any] = {
        "trigger": trigger_key,
        "had_position_before_close": had_position_before_close,
        "platform_initiated_market": platform_initiated_market,
        "radar_active": radar_active,
        "consumed_tp_levels": list(consumed_tp_levels or []),
    }

    fills: list[dict] = []
    start_ms = int(trade_opened_at * 1000) if trade_opened_at else None
    if client and hasattr(client, "get_account_trades"):
        try:
            rows = client.get_account_trades(symbol, start_time_ms=start_ms, limit=200)
            fills = _parse_fill_rows(rows, side)
            evidence["closing_fill_count"] = len(fills)
            evidence["closing_fill_qty"] = _sum_fill_qty(fills)
            evidence["closing_avg_price"] = _avg_fill_price(fills)
        except Exception as e:
            logger.debug("fill fetch for attribution failed: %s", e)
            evidence["fill_fetch_error"] = str(e)

    tv_recent = _tv_close_recent(recent_tv_close)
    evidence["tv_close_recent"] = tv_recent
    if recent_tv_close:
        evidence["latest_tv_action"] = recent_tv_close.get("action")
        evidence["latest_tv_at"] = recent_tv_close.get("created_at")

    tp_matched = _match_tp_prices(fills, list(tv_tps or []), list(consumed_tp_levels or []))
    evidence["tp_price_matches"] = tp_matched

    avg_px = evidence.get("closing_avg_price") or 0.0
    near_entry = _near_price(avg_px, entry) if avg_px > 0 and entry > 0 else False
    evidence["exit_near_entry"] = near_entry

    origin = "unknown"
    actor = "unknown"
    human_reason = CLOSE_TRIGGERS.get(trigger_key, trigger_key)

    if platform_initiated_market:
        origin = "platform_market"
        actor = "platform_code"
        human_reason = f"平台代码主动市价全平（{CLOSE_TRIGGERS.get(trigger_key, trigger_key)}）"
    elif tv_recent and trigger_key in ("tv_signal", "code_close_all"):
        origin = "tv_forced"
        actor = "tv_signal"
        human_reason = "TV 平仓信号触发平台全平"
    elif not had_position_before_close:
        if tv_recent:
            origin = "tv_forced"
            actor = "tv_signal"
            human_reason = "盘口已平：近期有 TV 平仓信号，疑为 TV 驱动或跟随成交"
        elif tp_matched or (fills and all(f["maker"] for f in fills) and consumed_tp_levels):
            origin = "exchange_limit_tp"
            actor = "exchange_order"
            levels = tp_matched or list(consumed_tp_levels or [])
            human_reason = f"盘口已平：交易所限价止盈成交（TP{levels}）"
        elif near_entry and not radar_active:
            origin = "manual_exchange"
            actor = "human"
            human_reason = (
                "盘口已平：成交价接近开仓价且雷达未激活，"
                "疑为交易所端人工平仓或手动市价/限价平仓"
            )
        elif fills and any(not f["maker"] for f in fills):
            origin = "manual_exchange"
            actor = "human"
            human_reason = "盘口已平：检测到市价吃单成交，疑为人工或外部市价平仓"
        elif fills and all(f["maker"] for f in fills):
            origin = "exchange_limit_tp"
            actor = "exchange_order"
            human_reason = "盘口已平：检测到限价挂单成交"
        else:
            origin = "exchange_already_flat"
            actor = "unknown"
            human_reason = (
                "哨兵检测盘口归零，但平台未发平仓单；"
                "未能从成交记录判定原因（可能 API 延迟或成交窗口外）"
            )
    else:
        origin = "platform_market"
        actor = "platform_code"
        human_reason = f"平台下发市价单全平（{CLOSE_TRIGGERS.get(trigger_key, trigger_key)}）"

    if origin == "unknown":
        if near_entry and not radar_active:
            origin = "manual_exchange"
            actor = "human"
            human_reason = "成交价接近开仓价，疑为人工平仓（雷达未启动）"

    return {
        "close_trigger": trigger_key,
        "close_origin": origin,
        "close_actor": actor,
        "human_reason": human_reason,
        "origin_label": CLOSE_ORIGINS.get(origin, origin),
        "trigger_label": CLOSE_TRIGGERS.get(trigger_key, trigger_key),
        "actor_label": CLOSE_ACTORS.get(actor, actor),
        "evidence": evidence,
        "anomaly": origin in ("unknown", "exchange_already_flat") and not had_position_before_close,
    }


def format_close_reason(attribution: dict[str, Any]) -> str:
    """Single-line reason for Trade.action / alerts."""
    human = attribution.get("human_reason") or ""
    origin = attribution.get("origin_label") or attribution.get("close_origin") or ""
    if human and origin:
        return f"{human} [{origin}]"
    return human or origin or "仓位已平"
