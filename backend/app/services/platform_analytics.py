"""Platform-wide analytics for admin dashboard."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Trade, TradeLog, User
from app.models.platform import SignalDispatchLog
from app.schemas import TradeOut
from app.services.trade_display_status import resolve_trade_display_status


def build_platform_analytics(db: Session, days: int = 14) -> dict:
    days = min(max(days, 7), 90)
    since = datetime.utcnow() - timedelta(days=days)

    closed = db.query(Trade).filter(Trade.status == "closed").all()
    wins = [t for t in closed if (t.realized_pnl or 0) > 0]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

    daily_map: dict[str, dict] = defaultdict(lambda: {"executions": 0, "pnl": 0.0})
    recent_trades = db.query(Trade).filter(Trade.created_at >= since).all()
    for t in recent_trades:
        if not t.created_at:
            continue
        key = t.created_at.strftime("%Y-%m-%d")
        daily_map[key]["executions"] += 1
        daily_map[key]["pnl"] += float(t.realized_pnl or 0)

    daily_series = [
        {"date": d, "executions": daily_map[d]["executions"], "pnl": round(daily_map[d]["pnl"], 2)}
        for d in sorted(daily_map.keys())
    ]

    logs = db.query(TradeLog).filter(TradeLog.created_at >= since).all()
    breakdown = {"success": 0, "failed": 0, "risk_blocked": 0}
    errors: Counter[str] = Counter()
    for log in logs:
        et = (log.event_type or "").upper()
        msg = log.message or ""
        if et == "ERROR":
            breakdown["failed"] += 1
            errors[msg[:60]] += 1
        elif et in ("OPEN", "CLOSE"):
            breakdown["success"] += 1
        elif et == "ADJUST" or "风控" in msg:
            breakdown["risk_blocked"] += 1

    active_api = db.query(User).filter(User.api_status == "active").count()
    total_users = db.query(User).count()

    cumulative_pnl = round(
        float(
            db.query(func.coalesce(func.sum(Trade.realized_pnl), 0))
            .filter(Trade.status == "closed")
            .scalar()
            or 0
        ),
        2,
    )

    signal_since = datetime.utcnow() - timedelta(days=days)
    signal_rows = (
        db.query(SignalDispatchLog)
        .filter(SignalDispatchLog.created_at >= signal_since)
        .order_by(SignalDispatchLog.created_at.asc())
        .all()
    )
    signal_map: dict[str, dict] = defaultdict(lambda: {"signals": 0, "users": 0, "errors": 0})
    for row in signal_rows:
        if not row.created_at:
            continue
        key = row.created_at.strftime("%Y-%m-%d")
        signal_map[key]["signals"] += 1
        signal_map[key]["users"] += int(row.dispatched_count or 0)
        signal_map[key]["errors"] += int(row.error_count or 0)
    signal_coverage_series = [
        {
            "date": d,
            "signals": signal_map[d]["signals"],
            "users_dispatched": signal_map[d]["users"],
            "errors": signal_map[d]["errors"],
        }
        for d in sorted(signal_map.keys())
    ]

    return {
        "win_rate": win_rate,
        "total_trades": len(closed),
        "total_users": total_users,
        "active_api_users": active_api,
        "cumulative_pnl": cumulative_pnl,
        "daily_series": daily_series,
        "signal_coverage_series": signal_coverage_series,
        "execution_breakdown": breakdown,
        "top_errors": [{"message": m, "count": c} for m, c in errors.most_common(8)],
    }


def enrich_trades(db: Session, trades: list[Trade]) -> list[dict]:
    if not trades:
        return []
    ids = [t.id for t in trades]
    open_logs = (
        db.query(TradeLog)
        .filter(TradeLog.trade_id.in_(ids), TradeLog.event_type == "OPEN")
        .all()
    )
    trade_logs = (
        db.query(TradeLog)
        .filter(TradeLog.trade_id.in_(ids))
        .order_by(TradeLog.created_at.asc())
        .all()
    )
    slip: dict[int, float] = {}
    logs_by_trade: dict[int, list[dict]] = defaultdict(list)
    for log in open_logs:
        if not log.trade_id or not log.detail_json:
            continue
        try:
            detail = json.loads(log.detail_json)
            if isinstance(detail.get("slippage"), (int, float)):
                slip[log.trade_id] = float(detail["slippage"])
        except json.JSONDecodeError:
            pass
    for log in trade_logs:
        if not log.trade_id:
            continue
        logs_by_trade[log.trade_id].append({
            "event_type": log.event_type,
            "message": log.message,
        })
    out = []
    for t in trades:
        row = TradeOut.model_validate(t).model_dump(mode="json")
        row["slippage"] = slip.get(t.id)
        row["funding_fee"] = float(getattr(t, "funding_fee", 0) or 0)
        row["display_status"] = resolve_trade_display_status(
            t.status, logs_by_trade.get(t.id, [])
        )
        out.append(row)
    return out
