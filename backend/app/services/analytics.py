"""User analytics computed from trades and logs."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Trade, TradeLog


def _max_drawdown(series: list[float]) -> float:
    if not series:
        return 0.0
    peak = series[0]
    mdd = 0.0
    for v in series:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def _sharpe(daily: list[float]) -> float:
    if len(daily) < 2:
        return 0.0
    mean = sum(daily) / len(daily)
    var = sum((x - mean) ** 2 for x in daily) / (len(daily) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return round((mean / std) * math.sqrt(365), 2)


def _sortino(daily: list[float]) -> float:
    if len(daily) < 2:
        return 0.0
    mean = sum(daily) / len(daily)
    downside = [x for x in daily if x < 0]
    if not downside:
        return round(mean * math.sqrt(365), 2) if mean > 0 else 0.0
    var = sum(x ** 2 for x in downside) / len(downside)
    std = math.sqrt(var) if var > 0 else 0.0
    return round((mean / std) * math.sqrt(365), 2) if std else 0.0


def _monte_carlo(daily: list[float], simulations: int = 500, bins: int = 10) -> dict:
    empty = {"median": 0.0, "p5": 0.0, "p95": 0.0, "histogram": []}
    if len(daily) < 5:
        return empty
    import random
    outcomes = []
    for _ in range(simulations):
        sample = random.choices(daily, k=len(daily))
        outcomes.append(sum(sample))
    outcomes.sort()
    n = len(outcomes)
    lo, hi = outcomes[0], outcomes[-1]
    histogram: list[dict] = []
    if hi == lo:
        histogram = [{"label": f"{lo:.0f}", "count": n}]
    else:
        width = (hi - lo) / bins
        counts = [0] * bins
        for v in outcomes:
            idx = min(int((v - lo) / width), bins - 1) if width > 0 else 0
            counts[idx] += 1
        for i in range(bins):
            start = lo + i * width
            histogram.append({"label": f"{start:.0f}", "count": counts[i]})
    return {
        "median": round(outcomes[n // 2], 2),
        "p5": round(outcomes[int(n * 0.05)], 2),
        "p95": round(outcomes[int(n * 0.95)], 2),
        "histogram": histogram,
    }


def build_user_analytics(db: Session, user_id: int, days: int = 90, *, since: date | None = None) -> dict:
    """Build analytics. If since is set, window starts at that date (API activation); else last N days."""
    if since is not None:
        start = since
    else:
        start = date.today() - timedelta(days=days - 1)

    closed = (
        db.query(Trade)
        .filter(
            Trade.user_id == user_id,
            Trade.status == "closed",
            Trade.closed_at.isnot(None),
            func.date(Trade.closed_at) >= start,
        )
        .order_by(Trade.closed_at.asc())
        .all()
    )

    wins = [t for t in closed if (t.realized_pnl or 0) > 0]
    losses = [t for t in closed if (t.realized_pnl or 0) < 0]
    gross_profit = sum(t.realized_pnl or 0 for t in wins)
    gross_loss = abs(sum(t.realized_pnl or 0 for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)

    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

    daily_map: dict[str, float] = defaultdict(float)
    for t in closed:
        if t.closed_at:
            daily_map[t.closed_at.date().isoformat()] += float(t.realized_pnl or 0)

    equity_curve: list[float] = []
    running = 0.0
    daily_series: list[dict] = []
    d = start
    while d <= date.today():
        key = d.isoformat()
        pnl = daily_map.get(key, 0.0)
        running += pnl
        equity_curve.append(running)
        daily_series.append({"date": key, "pnl": round(pnl, 2), "cumulative": round(running, 2)})
        d += timedelta(days=1)

    daily_values = [x["pnl"] for x in daily_series]
    mdd = _max_drawdown(equity_curve)
    sharpe = _sharpe(daily_values)
    sortino = _sortino(daily_values)

    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = round((win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss), 2) if closed else 0.0
    win_prob = win_rate / 100 if win_rate else 0
    loss_prob = 1 - win_prob
    kelly = round(win_prob - (loss_prob / (avg_win / avg_loss)) if avg_loss > 0 and avg_win > 0 else 0, 4)
    sqn = round(math.sqrt(len(closed)) * (expectancy / (sum(abs(x) for x in daily_values) / len(daily_values) or 1)), 2) if closed and daily_values else 0.0
    calmar = round((equity_curve[-1] / (mdd or 1)) if mdd and equity_curve else 0, 2)
    monte_carlo = _monte_carlo(daily_values)

    regime_map: dict[str, float] = defaultdict(float)
    for t in closed:
        regime_map[f"R{t.regime or 3}"] += float(t.realized_pnl or 0)

    pnl_by_regime = [
        {"regime": k, "pnl": round(v, 2)}
        for k, v in sorted(regime_map.items(), key=lambda x: x[0])
    ]

    symbol_map: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for t in closed:
        sym = (t.symbol or "ETHUSDT").upper()
        symbol_map[sym]["pnl"] += float(t.realized_pnl or 0)
        symbol_map[sym]["trades"] += 1
        if (t.realized_pnl or 0) > 0:
            symbol_map[sym]["wins"] += 1
    pnl_by_symbol = [
        {
            "symbol": k,
            "pnl": round(v["pnl"], 2),
            "trades": v["trades"],
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
        }
        for k, v in sorted(symbol_map.items(), key=lambda x: x[0])
    ]

    week_labels: list[str] = []
    week_values: list[float] = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        week_labels.append(day.isoformat())
        week_values.append(round(daily_map.get(day.isoformat(), 0.0), 2))

    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "sqn": sqn,
        "expectancy": expectancy,
        "kelly": kelly,
        "monte_carlo": monte_carlo,
        "total_trades": len(closed),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "daily_series": daily_series,
        "week_labels": week_labels,
        "week_values": week_values,
        "pnl_by_regime": pnl_by_regime,
        "pnl_by_symbol": pnl_by_symbol,
        "window_start": start.isoformat(),
        "since_activation": since is not None,
    }


def build_signal_stats(db: Session, user_id: int, limit: int = 100) -> dict:
    import json

    logs = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user_id)
        .order_by(TradeLog.created_at.desc())
        .limit(limit)
        .all()
    )
    exec_logs = [l for l in logs if (l.event_type or "").upper() in ("OPEN", "CLOSE", "ERROR", "ADJUST", "SIGNAL")]
    opens = [l for l in exec_logs if (l.event_type or "").upper() == "OPEN"]
    errors = [l for l in exec_logs if (l.event_type or "").upper() == "ERROR"]
    attempts = len(opens) + len(errors)
    success_rate = round(len(opens) / attempts * 100, 1) if attempts else 0.0

    regime_confidence = 0.0
    regime_count = 0
    for log in opens[:20]:
        detail = {}
        if log.detail_json:
            try:
                detail = json.loads(log.detail_json)
            except json.JSONDecodeError:
                pass
        regime = detail.get("regime")
        if isinstance(regime, int) and regime > 0:
            regime_confidence += min(95.0, 55.0 + regime * 12.0)
            regime_count += 1

    if regime_count:
        confidence = round(regime_confidence / regime_count, 1)
    elif attempts:
        confidence = round(min(92.0, max(52.0, 48 + success_rate * 0.45)), 1)
    else:
        confidence = 0.0

    open_trade = (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
        .first()
    )
    direction_bias = open_trade.side if open_trade and open_trade.side else None
    if not direction_bias:
        for l in exec_logs:
            msg = (l.message or "").upper()
            if "LONG" in msg:
                direction_bias = "LONG"
                break
            if "SHORT" in msg:
                direction_bias = "SHORT"
                break

    last_signal_at = exec_logs[0].created_at.isoformat() if exec_logs and exec_logs[0].created_at else None

    return {
        "total": len(exec_logs),
        "success_rate": success_rate,
        "confidence_score": confidence,
        "direction_bias": direction_bias,
        "last_signal_at": last_signal_at,
        "execution_attempts": attempts,
        "recent": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "message": l.message,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in exec_logs[:50]
        ],
    }
