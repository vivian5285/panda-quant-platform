"""VPS-computed hard stop — regime % of entry price (scales with ETH price)."""

from __future__ import annotations

from typing import Any

from app.core.regime_utils import clamp_regime
from app.core.symbol_precision import round_price

# Hard stop distance = entry × regime_pct (breathing room scales with price)
REGIME_HARD_SL_PCT: dict[int, float] = {
    1: 0.028,  # 2.8%
    2: 0.039,  # 3.9%
    3: 0.056,  # 5.6%
    4: 0.083,  # 8.3%
}

# Stop-Limit: limit worse than trigger by this fraction of trigger (0.1%~0.2%)
HARD_SL_LIMIT_PCT = 0.0015  # 0.15%
# Legacy absolute offset kept for callers that still pass fixed USD
HARD_SL_STOP_LIMIT_OFFSET = 0.5


def hard_sl_pct(regime: int) -> float:
    """Regime breathing-room as fraction of entry price."""
    return float(REGIME_HARD_SL_PCT[clamp_regime(regime)])


def hard_sl_final_multiplier(regime: int) -> float:
    """Alias for hard_sl_pct — retained for older call sites / logs."""
    return hard_sl_pct(regime)


def compute_hard_sl_distance(
    entry: float,
    regime: int,
    *,
    atr: float = 0.0,
    relax_pct: float = 0.0,
) -> float:
    """
    Breathing space in price units: entry × regime_pct (+ optional relax).
    `atr` is ignored (kept for backward-compatible callers).
    """
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
    VPS authoritative hard stop from entry × regime % (TV tv_sl reference-only).
    LONG: entry − distance; SHORT: entry + distance.
    `atr` is ignored — distance scales with entry price, not ATR.
    """
    entry_f = float(entry or 0)
    side_u = str(side or "").upper()
    r = clamp_regime(regime)
    pct = hard_sl_pct(r)
    dist = compute_hard_sl_distance(entry_f, r, atr=atr, relax_pct=relax_pct)
    meta: dict[str, Any] = {
        "source": "vps_computed",
        "method": "entry_pct",
        "regime": r,
        "atr": round(float(atr or 0), 4),
        "hard_sl_pct": round(pct, 4),
        "hard_sl_pct_display": f"{pct * 100:.1f}%",
        "final_multiplier": round(pct, 4),
        "sl_distance": round(dist, 4),
        "relax_pct": round(float(relax_pct or 0), 4),
        "entry": round(entry_f, 2),
        "side": side_u,
    }
    if tv_sl_reference and float(tv_sl_reference) > 0:
        meta["tv_sl_reference"] = round(float(tv_sl_reference), 2)

    if entry_f <= 0 or dist <= 0 or side_u not in ("LONG", "SHORT"):
        meta["stop_price"] = 0.0
        meta["error"] = "invalid_inputs"
        return meta

    if side_u == "LONG":
        meta["stop_price"] = round_price(entry_f - dist)
    else:
        meta["stop_price"] = round_price(entry_f + dist)
    meta["limit_price"] = compute_hard_sl_limit_price(meta["stop_price"], side_u)
    return meta


def compute_hard_sl_limit_price(
    stop_price: float,
    side: str | None,
    *,
    offset: float | None = None,
    pct: float = HARD_SL_LIMIT_PCT,
) -> float:
    """
    Stop-Limit execution price for buffer hard stop.
    LONG: limit = trigger − (pct × trigger); SHORT: limit = trigger + (pct × trigger).
    Optional fixed `offset` (USD) overrides pct when provided explicitly as positive.
    """
    sp = float(stop_price or 0)
    if sp <= 0 or side not in ("LONG", "SHORT"):
        return round_price(sp)
    if offset is not None and float(offset) > 0:
        off = float(offset)
    else:
        off = max(sp * max(float(pct or 0), 0.0), HARD_SL_STOP_LIMIT_OFFSET * 0.2)
    if side == "LONG":
        return round_price(sp - off)
    return round_price(sp + off)
