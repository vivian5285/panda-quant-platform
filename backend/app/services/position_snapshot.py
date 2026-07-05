"""Unified live position + account snapshot for all exchange supervisors."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _as_position_status(
    *,
    side: str,
    qty: float,
    entry_price: float,
    mark_price: float = 0.0,
    unrealized_pnl: float = 0.0,
    leverage: str | int | float = "N/A",
) -> dict[str, Any]:
    return {
        "has_position": True,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "unrealized_pnl": unrealized_pnl,
        "leverage": leverage,
    }


def get_supervisor_position_status(supervisor) -> dict[str, Any]:
    """Binance/OKX/Gate via PositionManager; Deepcoin via _get_active_position."""
    if supervisor is None:
        return {"has_position": False}

    if hasattr(supervisor, "position_manager"):
        try:
            return supervisor.position_manager.get_position_status()
        except Exception as e:
            logger.warning("position_manager status failed user=%s: %s", getattr(supervisor, "user_id", "?"), e)
            return {"has_position": False, "error": str(e)}

    if hasattr(supervisor, "_get_active_position"):
        try:
            pos = supervisor._get_active_position()
            if not pos or float(pos.get("size", 0) or 0) <= 0:
                return {"has_position": False}
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
            )
        except Exception as e:
            logger.warning("deepcoin position status failed user=%s: %s", getattr(supervisor, "user_id", "?"), e)
            return {"has_position": False, "error": str(e)}

    return {"has_position": False}


def get_supervisor_account_summary(supervisor) -> dict[str, Any]:
    if supervisor is None:
        return {}
    try:
        return supervisor.client.get_futures_account_summary() or {}
    except Exception as e:
        logger.warning("account summary failed user=%s: %s", getattr(supervisor, "user_id", "?"), e)
        return {}


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
        }
    return {
        "has_position": True,
        "position_side": status.get("side"),
        "position_qty": float(status.get("qty") or 0),
        "position_entry": float(status.get("entry_price") or 0),
        "position_mark": float(status.get("mark_price") or 0),
        "position_unrealized": float(status.get("unrealized_pnl") or 0),
    }
