"""Unified live position + account snapshot for all exchange supervisors."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Trade, TradeLog

logger = logging.getLogger(__name__)
settings = get_settings()


def _as_position_status(
    *,
    side: str,
    qty: float,
    entry_price: float,
    mark_price: float = 0.0,
    unrealized_pnl: float = 0.0,
    leverage: str | int | float = "N/A",
    snapshot_source: str = "unknown",
    api_degraded: bool = False,
) -> dict[str, Any]:
    out = {
        "has_position": True,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "unrealized_pnl": unrealized_pnl,
        "leverage": leverage,
        "snapshot_source": snapshot_source,
    }
    if api_degraded:
        out["api_degraded"] = True
    return out


def _estimate_unrealized(side: str, qty: float, entry: float, mark: float) -> float:
    if mark <= 0 or entry <= 0 or qty <= 0:
        return 0.0
    diff = (mark - entry) if side == "LONG" else (entry - mark)
    return round(diff * qty, 4)


def _mark_from_supervisor(supervisor, entry: float, side: str, qty: float) -> tuple[float, float]:
    mark = 0.0
    unrealized = 0.0
    symbol = getattr(supervisor, "symbol", None)
    if symbol and hasattr(supervisor, "client"):
        try:
            mark = float(supervisor.client.get_current_price(symbol) or 0)
        except Exception:
            pass
    best = float(getattr(supervisor, "best_price", 0) or 0)
    if mark <= 0 and best > 0:
        mark = best
    if mark > 0:
        unrealized = _estimate_unrealized(side, qty, entry, mark)
    return mark, unrealized


def _position_from_supervisor_memory(supervisor) -> dict[str, Any]:
    if not getattr(supervisor, "monitoring", False):
        return {"has_position": False}
    qty = float(getattr(supervisor, "watched_qty", 0) or 0)
    entry = float(getattr(supervisor, "watched_entry", 0) or 0)
    side = getattr(supervisor, "current_side", None)
    if qty <= 0 or not side:
        return {"has_position": False}
    mark, unrealized = _mark_from_supervisor(supervisor, entry, side, qty)
    return _as_position_status(
        side=side,
        qty=qty,
        entry_price=entry,
        mark_price=mark,
        unrealized_pnl=unrealized,
        leverage=getattr(supervisor, "leverage", "N/A"),
        snapshot_source="supervisor_memory",
    )


def _position_from_log_detail(detail: dict, source: str) -> dict[str, Any] | None:
    if not detail:
        return None
    if detail.get("has_position"):
        side = detail.get("side")
        qty = float(detail.get("qty", 0) or 0)
        entry = float(detail.get("entry", 0) or 0)
    elif source == "OPEN":
        side = detail.get("side")
        qty = float(detail.get("qty", 0) or 0)
        entry = float(detail.get("entry", detail.get("entry_price", 0)) or 0)
    else:
        return None
    if not side or qty <= 0:
        return None
    mark = float(detail.get("mark_price", detail.get("best_price", 0)) or 0)
    unrealized = float(detail.get("unrealized_pnl", 0) or 0)
    if unrealized == 0 and mark > 0:
        unrealized = _estimate_unrealized(side, qty, entry, mark)
    return _as_position_status(
        side=side,
        qty=qty,
        entry_price=entry,
        mark_price=mark,
        unrealized_pnl=unrealized,
        snapshot_source=f"trade_log_{source.lower()}",
    )


def _position_from_db(db: Session, user_id: int) -> dict[str, Any]:
    trade = (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
        .first()
    )
    if trade and float(trade.quantity or 0) > 0:
        return _as_position_status(
            side=trade.side,
            qty=float(trade.quantity),
            entry_price=float(trade.entry_price or 0),
            snapshot_source="db_open_trade",
        )

    for event_type in ("STARTUP", "OPEN"):
        row = (
            db.query(TradeLog)
            .filter(TradeLog.user_id == user_id, TradeLog.event_type == event_type)
            .order_by(TradeLog.created_at.desc())
            .first()
        )
        if not row or not row.detail_json:
            continue
        try:
            detail = json.loads(row.detail_json)
        except json.JSONDecodeError:
            continue
        parsed = _position_from_log_detail(detail, event_type)
        if parsed:
            return parsed
    return {"has_position": False}


def _position_from_startup_audit(user_id: int) -> dict[str, Any]:
    try:
        from app.services.dispatcher import supervisor_pool

        for audit in supervisor_pool.last_startup_audits or []:
            if audit.get("user_id") != user_id or not audit.get("has_position"):
                continue
            side = audit.get("side")
            qty = float(audit.get("qty", 0) or 0)
            entry = float(audit.get("entry", 0) or 0)
            if not side or qty <= 0:
                continue
            mark = float(audit.get("best_price", 0) or 0)
            unrealized = _estimate_unrealized(side, qty, entry, mark) if mark > 0 else 0.0
            return _as_position_status(
                side=side,
                qty=qty,
                entry_price=entry,
                mark_price=mark,
                unrealized_pnl=unrealized,
                snapshot_source="startup_audit",
            )
    except Exception as e:
        logger.debug("startup audit fallback skipped user=%s: %s", user_id, e)
    return {"has_position": False}


def _try_exchange_api(supervisor) -> tuple[dict[str, Any], str | None]:
    api_error: str | None = None

    if hasattr(supervisor, "position_manager"):
        try:
            status = supervisor.position_manager.get_position_status()
            if status.get("has_position"):
                status["snapshot_source"] = "exchange_api"
                return status, None
            return status, None
        except Exception as e:
            api_error = str(e)
            logger.warning(
                "position_manager status failed user=%s: %s",
                getattr(supervisor, "user_id", "?"),
                e,
            )

    if hasattr(supervisor, "_get_active_position"):
        try:
            pos = supervisor._get_active_position()
            if not pos or float(pos.get("size", 0) or 0) <= 0:
                return {"has_position": False}, api_error
            side = "LONG" if str(pos.get("posSide", "long")).lower() == "long" else "SHORT"
            qty = float(pos.get("size", 0))
            entry = float(pos.get("entry_price", 0) or 0)
            mark = 0.0
            unrealized = 0.0
            face = float(getattr(supervisor, "face_value", 0.1) or 0.1)
            symbol = getattr(supervisor, "symbol", None)
            if symbol and hasattr(supervisor, "client"):
                try:
                    mark = float(supervisor.client.get_current_price(symbol) or 0)
                    if mark > 0 and entry > 0:
                        diff = (mark - entry) if side == "LONG" else (entry - mark)
                        unrealized = round(diff * qty * face, 4)
                except Exception:
                    pass
            return _as_position_status(
                side=side,
                qty=qty,
                entry_price=entry,
                mark_price=mark,
                unrealized_pnl=unrealized,
                leverage=getattr(supervisor, "leverage", "N/A"),
                snapshot_source="exchange_api",
            ), api_error
        except Exception as e:
            api_error = str(e)
            logger.warning(
                "deepcoin position status failed user=%s: %s",
                getattr(supervisor, "user_id", "?"),
                e,
            )

    return {"has_position": False}, api_error


def get_supervisor_position_status(
    supervisor,
    *,
    db: Session | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Exchange API first; fall back to supervisor memory, DB trade/log, startup audit."""
    if supervisor is None:
        return {"has_position": False}

    uid = user_id or getattr(supervisor, "user_id", None)
    api_status, api_error = _try_exchange_api(supervisor)
    if api_status.get("has_position"):
        return api_status

    fallbacks: list[dict[str, Any]] = []
    mem = _position_from_supervisor_memory(supervisor)
    if mem.get("has_position"):
        fallbacks.append(mem)
    if db is not None and uid is not None:
        db_pos = _position_from_db(db, uid)
        if db_pos.get("has_position"):
            fallbacks.append(db_pos)
    if uid is not None:
        audit_pos = _position_from_startup_audit(uid)
        if audit_pos.get("has_position"):
            fallbacks.append(audit_pos)

    if fallbacks:
        chosen = fallbacks[0]
        if api_error:
            chosen = {**chosen, "api_degraded": True, "api_error": api_error}
        if chosen.get("mark_price", 0) <= 0 and supervisor is not None:
            mark, unrealized = _mark_from_supervisor(
                supervisor,
                float(chosen.get("entry_price", 0) or 0),
                chosen.get("side", "LONG"),
                float(chosen.get("qty", 0) or 0),
            )
            if mark > 0:
                chosen["mark_price"] = mark
                if not chosen.get("unrealized_pnl"):
                    chosen["unrealized_pnl"] = unrealized
        return chosen

    result: dict[str, Any] = {"has_position": False}
    if api_error:
        result["error"] = api_error
    return result


def get_supervisor_account_summary(supervisor, *, user=None, position: dict | None = None) -> dict[str, Any]:
    if supervisor is None:
        return {}
    try:
        summary = supervisor.client.get_futures_account_summary() or {}
        if float(summary.get("total_margin_balance", 0) or 0) > 0:
            summary["snapshot_source"] = "exchange_api"
            return summary
    except Exception as e:
        logger.warning(
            "account summary failed user=%s: %s",
            getattr(supervisor, "user_id", "?"),
            e,
        )

    initial = float(getattr(user, "initial_principal", 0) or 0) if user else 0.0
    unrealized = float((position or {}).get("unrealized_pnl", 0) or 0)
    if initial > 0 or (position or {}).get("has_position"):
        equity = round(initial + unrealized, 2) if initial > 0 else round(unrealized, 2)
        return {
            "total_margin_balance": equity,
            "available_balance": equity,
            "unrealized_pnl": unrealized,
            "snapshot_source": "estimated",
            "api_degraded": True,
        }
    return {}


def ensure_open_trade_from_snapshot(
    db: Session,
    user_id: int,
    supervisor,
    position: dict[str, Any],
) -> int | None:
    """Create missing open Trade row so settlement/history align with live position."""
    if not position.get("has_position"):
        return None
    existing = (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
        .first()
    )
    if existing:
        return existing.id

    from app.services.trade_logger import TradeLogger

    regime = int(getattr(supervisor, "regime", 0) or 0)
    tv_tps = list(getattr(supervisor, "tv_tps", [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0])
    trade_id = TradeLogger(db).on_trade_open(
        user_id,
        position["side"],
        float(position["qty"]),
        float(position["entry_price"]),
        regime,
        tv_tps,
    )
    if trade_id and supervisor is not None:
        supervisor.current_trade_id = trade_id
        if hasattr(supervisor, "_save_state"):
            supervisor._save_state()
    return trade_id or None


def position_fields_from_status(status: dict | None) -> dict[str, Any]:
    """Flatten position status for admin/referral list rows."""
    if not status or not status.get("has_position"):
        return {
            "has_position": False,
            "position_side": None,
            "position_qty": 0.0,
            "position_entry": 0.0,
            "position_mark": 0.0,
            "position_unrealized": 0.0,
            "snapshot_source": status.get("snapshot_source") if status else None,
            "snapshot_degraded": bool(status.get("api_degraded")) if status else False,
        }
    return {
        "has_position": True,
        "position_side": status.get("side"),
        "position_qty": float(status.get("qty") or 0),
        "position_entry": float(status.get("entry_price") or 0),
        "position_mark": float(status.get("mark_price") or 0),
        "position_unrealized": float(status.get("unrealized_pnl") or 0),
        "snapshot_source": status.get("snapshot_source"),
        "snapshot_degraded": bool(status.get("api_degraded")),
    }
