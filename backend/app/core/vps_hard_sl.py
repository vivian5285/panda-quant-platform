"""Hard stop placement — authoritative stop = TradingView ``tv_sl``.

VPS entry×regime% wide SL has been REMOVED from live placement.
All exchanges (LONG/SHORT) hang Stop-Limit at TV ``tv_sl`` only.
"""

from __future__ import annotations

from typing import Any

from app.core.regime_utils import clamp_regime
from app.core.symbol_precision import round_price

# Legacy table retained only for docs/audit — NOT used for live placement
REGIME_HARD_SL_PCT: dict[int, float] = {
    1: 0.0278,
    2: 0.0389,
    3: 0.0556,
    4: 0.0833,
}

HARD_SL_LIMIT_PCT = 0.0015  # 0.15%
HARD_SL_STOP_LIMIT_OFFSET = 0.5


def hard_sl_pct(regime: int) -> float:
    """Deprecated legacy helper — not used for live hard-SL placement."""
    return float(REGIME_HARD_SL_PCT[clamp_regime(regime)])


def hard_sl_final_multiplier(regime: int) -> float:
    return hard_sl_pct(regime)


def compute_hard_sl_distance(
    entry: float,
    regime: int,
    *,
    atr: float = 0.0,
    relax_pct: float = 0.0,
) -> float:
    """Deprecated — VPS distance formula no longer drives live stops."""
    e = max(float(entry or 0), 0.0)
    if e <= 0:
        return 0.0
    _ = atr
    dist = e * hard_sl_pct(regime)
    rp = max(float(relax_pct or 0), 0.0)
    if rp > 0:
        dist *= 1.0 + rp
    return dist


def compute_vps_hard_sl(
    entry: float,
    side: str | None,
    atr: float = 0.0,
    regime: int = 3,
    *,
    relax_pct: float = 0.0,
    tv_sl_reference: float | None = None,
) -> dict[str, Any]:
    """
    Resolve live hard-stop price from TradingView ``tv_sl`` only.

    ``tv_sl_reference`` is the authoritative stop. Entry×regime% is NOT applied.
    Returns ``error=no_tv_sl`` when TV stop missing — caller must alert / not place VPS.
    """
    _ = atr, relax_pct  # legacy kwargs ignored for placement
    entry_f = float(entry or 0)
    side_u = str(side or "").upper()
    r = clamp_regime(regime)
    tv = float(tv_sl_reference or 0)
    meta: dict[str, Any] = {
        "source": "tv_sl",
        "method": "tv_hard_sl",
        "regime": r,
        "entry": round(entry_f, 2),
        "side": side_u,
        "hard_sl_pct": None,
        "hard_sl_pct_display": "TV",
        "final_multiplier": None,
        "sl_distance": round(abs(entry_f - tv), 4) if entry_f > 0 and tv > 0 else 0.0,
        "relax_pct": 0.0,
        "tv_sl": round(tv, 2) if tv > 0 else None,
    }

    if tv <= 0:
        meta["stop_price"] = 0.0
        meta["error"] = "no_tv_sl"
        meta["source"] = "missing_tv_sl"
        return meta

    if side_u not in ("LONG", "SHORT"):
        meta["stop_price"] = 0.0
        meta["error"] = "invalid_side"
        return meta

    # Soft sanity: LONG stop should be below entry; SHORT above (log only, still hang TV)
    if entry_f > 0:
        if side_u == "LONG" and tv >= entry_f:
            meta["warn"] = "tv_sl_not_below_entry_long"
        elif side_u == "SHORT" and tv <= entry_f:
            meta["warn"] = "tv_sl_not_above_entry_short"

    meta["stop_price"] = round_price(tv)
    meta["limit_price"] = compute_hard_sl_limit_price(meta["stop_price"], side_u)
    meta["tv_sl_reference"] = round(tv, 2)
    return meta


def compute_hard_sl_limit_price(
    stop_price: float,
    side: str | None,
    *,
    offset: float | None = None,
    pct: float = HARD_SL_LIMIT_PCT,
) -> float:
    """
    Stop-Limit execution price buffer.
    LONG: limit = trigger − pct×trigger; SHORT: limit = trigger + pct×trigger.
    """
    sp = float(stop_price or 0)
    if sp <= 0 or side not in ("LONG", "SHORT"):
        return round_price(sp)
    if offset is not None and float(offset) > 0:
        delta = float(offset)
    else:
        delta = sp * float(pct or HARD_SL_LIMIT_PCT)
    if side == "LONG":
        return round_price(sp - delta)
    return round_price(sp + delta)
