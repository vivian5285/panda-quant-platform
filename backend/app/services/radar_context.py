"""Radar recovery context: open trade log + latest TV webhook cross-check."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.symbol_precision import normalize_tv_targets
from app.models import Trade, TradeLog
from app.models.platform import WebhookReceiveLog

logger = logging.getLogger(__name__)

TV_ACTIONS_POSITION = {"LONG", "SHORT"}
TV_ACTIONS_CLOSE = {"CLOSE", "CLOSE_TP3", "CLOSE_PROTECT", "CLOSE_STOPLOSS"}


def get_latest_tv_signal(db: Session) -> dict | None:
    """Latest successfully dispatched TradingView webhook (platform-wide)."""
    row = (
        db.query(WebhookReceiveLog)
        .filter(
            WebhookReceiveLog.event_status.in_(("dispatched", "accepted")),
            WebhookReceiveLog.action.isnot(None),
        )
        .order_by(WebhookReceiveLog.created_at.desc())
        .first()
    )
    if not row:
        return None
    try:
        summary = json.loads(row.tv_summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    action = (row.action or summary.get("action") or "").upper()
    return {
        "id": row.id,
        "action": action,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "regime": int(summary.get("regime", 0) or 0),
        "atr": float(summary.get("atr", 0) or 0),
        "price": float(summary.get("price", 0) or 0),
        "tv_tps": normalize_tv_targets([
            summary.get("tv_tp1", 0),
            summary.get("tv_tp2", 0),
            summary.get("tv_tp3", 0),
        ]),
        "reason": summary.get("reason"),
    }


def get_open_trade_log_detail(db: Session, user_id: int, trade_id: int | None = None) -> dict | None:
    """Latest OPEN event from trade log (authoritative open snapshot)."""
    q = db.query(TradeLog).filter(
        TradeLog.user_id == user_id,
        TradeLog.event_type == "OPEN",
    )
    if trade_id:
        q = q.filter(TradeLog.trade_id == trade_id)
    row = q.order_by(TradeLog.created_at.desc()).first()
    if not row:
        return None
    try:
        detail = json.loads(row.detail_json or "{}")
    except json.JSONDecodeError:
        detail = {}
    return {
        "trade_id": row.trade_id,
        "opened_at": row.created_at.isoformat() if row.created_at else None,
        "side": detail.get("side"),
        "qty": float(detail.get("qty", 0) or 0),
        "entry": float(detail.get("entry", 0) or 0),
        "regime": int(detail.get("regime", 0) or 0),
        "atr": float(detail.get("atr", 0) or 0),
        "tv_tps": normalize_tv_targets(detail.get("tv_tps") or []),
        "tv_price": float(detail.get("tv_price", 0) or 0),
    }


def get_open_trade_context(db: Session, user_id: int) -> dict | None:
    trade = (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
        .first()
    )
    if not trade:
        return None
    return {
        "id": trade.id,
        "side": trade.side,
        "regime": trade.regime,
        "quantity": float(trade.quantity or 0),
        "entry_price": float(trade.entry_price or 0),
        "tv_tps": [trade.tv_tp1, trade.tv_tp2, trade.tv_tp3],
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
    }


def build_radar_recovery_context(db: Session, user_id: int) -> dict:
    """Merge DB open trade, OPEN log, and latest TV for VPS takeover audit."""
    trade = get_open_trade_context(db, user_id)
    trade_id = trade["id"] if trade else None
    open_log = get_open_trade_log_detail(db, user_id, trade_id)
    latest_tv = get_latest_tv_signal(db)

    checks = []
    if trade and open_log:
        if open_log.get("side") and trade.get("side") and open_log["side"] != trade["side"]:
            checks.append("open_log_side_mismatch")
        if open_log.get("entry") and trade.get("entry_price"):
            if abs(open_log["entry"] - trade["entry_price"]) > 0.05:
                checks.append("open_log_entry_mismatch")

    if latest_tv and trade:
        tv_action = latest_tv.get("action", "")
        if tv_action in TV_ACTIONS_POSITION and tv_action != trade.get("side"):
            checks.append("tv_direction_vs_trade")
        if tv_action in TV_ACTIONS_CLOSE:
            checks.append("tv_close_while_trade_open")

    return {
        "trade": trade,
        "open_log": open_log,
        "latest_tv": latest_tv,
        "checks": checks,
    }
