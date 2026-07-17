"""Combined ETH+XAU notional exposure guard (≤ equity × MAX_COMBINED_NOTIONAL_MULT)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.core.symbol_registry import DEFAULT_CANONICAL, normalize_canonical_symbol

logger = logging.getLogger(__name__)
settings = get_settings()


def position_notional(qty: float, entry_or_mark: float) -> float:
    q = abs(float(qty or 0))
    px = float(entry_or_mark or 0)
    if q <= 0 or px <= 0:
        return 0.0
    return q * px


def supervisor_live_notional(supervisor) -> float:
    """Estimate open notional for one supervisor from watched qty × entry/mark."""
    if supervisor is None:
        return 0.0
    qty = abs(float(getattr(supervisor, "watched_qty", 0) or 0))
    if qty <= 0:
        return 0.0
    entry = float(getattr(supervisor, "watched_entry", 0) or 0)
    mark = float(getattr(supervisor, "best_price", 0) or 0)
    px = entry if entry > 0 else mark
    if px <= 0 and hasattr(supervisor, "client"):
        try:
            sym = getattr(supervisor, "symbol", None)
            px = float(supervisor.client.get_current_price(sym) or 0)
        except Exception:
            px = 0.0
    return position_notional(qty, px)


def peer_notional_excluding(user_id: int, canonical: str | None) -> float:
    """Sum open notional of sibling symbols for the same user."""
    from app.services.dispatcher import supervisor_pool

    can = normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL
    total = 0.0
    for sup in supervisor_pool.get_all_for_user(user_id):
        peer_can = getattr(sup, "canonical_symbol", None) or normalize_canonical_symbol(
            getattr(sup, "symbol", None)
        )
        if peer_can == can:
            continue
        total += supervisor_live_notional(sup)
    return total


def check_combined_notional_cap(
    *,
    user_id: int,
    canonical: str | None,
    equity: float,
    new_notional: float,
    replace_own: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """
    Allow OPEN only if (peer + new) ≤ equity × MAX_COMBINED_NOTIONAL_MULT.
    When replace_own=True, current symbol's existing notional is excluded (re-open replaces it).
    """
    eq = max(float(equity or 0), 0.0)
    mult = float(getattr(settings, "MAX_COMBINED_NOTIONAL_MULT", 13.0) or 13.0)
    cap = eq * mult if eq > 0 else 0.0
    peers = peer_notional_excluding(user_id, canonical)
    proposed = peers + max(float(new_notional or 0), 0.0)
    ok = cap <= 0 or proposed <= cap + 1e-6
    meta = {
        "combined_notional_check": True,
        "equity": round(eq, 2),
        "max_mult": mult,
        "notional_cap": round(cap, 2),
        "peer_notional": round(peers, 2),
        "new_notional": round(float(new_notional or 0), 2),
        "proposed_notional": round(proposed, 2),
        "allowed": ok,
    }
    if not ok:
        meta["error"] = "combined_notional_exceeded"
        logger.warning(
            "Combined notional blocked user=%s symbol=%s proposed=%.2f cap=%.2f",
            user_id,
            canonical,
            proposed,
            cap,
        )
    return ok, meta
