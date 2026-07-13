"""VPS-computed hard stop — regime × ATR breathing space (四档均匀递增版)."""

from __future__ import annotations

from typing import Any

from app.core.regime_utils import clamp_regime
from app.core.symbol_precision import round_price

# sl_m × regime_multiplier → final multiplier (Regime 4 ≈ 100U @ ATR≈16)
REGIME_HARD_SL: dict[int, dict[str, float]] = {
    1: {"sl_m": 0.9, "regime_multiplier": 2.0},   # 1.80× ≈ 30 U
    2: {"sl_m": 1.05, "regime_multiplier": 3.0},  # 3.15× ≈ 50 U
    3: {"sl_m": 1.10, "regime_multiplier": 4.0},  # 4.40× ≈ 70 U
    4: {"sl_m": 1.25, "regime_multiplier": 5.0},  # 6.25× ≈ 100 U
}

# Stop-Limit buffer: limit worse than trigger by 0.5~1 U to absorb gaps
HARD_SL_STOP_LIMIT_OFFSET = 0.5


def hard_sl_final_multiplier(regime: int) -> float:
    r = clamp_regime(regime)
    row = REGIME_HARD_SL[r]
    return float(row["sl_m"]) * float(row["regime_multiplier"])


def compute_hard_sl_distance(
    atr: float,
    regime: int,
    *,
    relax_pct: float = 0.0,
) -> float:
    """Breathing space in price units: ATR × sl_m × regime_multiplier (+ optional relax)."""
    a = max(float(atr or 0), 0.0)
    if a <= 0:
        return 0.0
    mult = hard_sl_final_multiplier(regime)
    dist = a * mult
    rp = max(float(relax_pct or 0), 0.0)
    if rp > 0:
        dist *= 1.0 + rp
    return dist


def compute_vps_hard_sl(
    entry: float,
    side: str | None,
    atr: float,
    regime: int,
    *,
    relax_pct: float = 0.0,
    tv_sl_reference: float | None = None,
) -> dict[str, Any]:
    """
    VPS authoritative hard stop (TV tv_sl is reference-only).
    LONG: entry − distance; SHORT: entry + distance.
    """
    entry_f = float(entry or 0)
    side_u = str(side or "").upper()
    r = clamp_regime(regime)
    row = REGIME_HARD_SL[r]
    dist = compute_hard_sl_distance(atr, r, relax_pct=relax_pct)
    meta: dict[str, Any] = {
        "source": "vps_computed",
        "regime": r,
        "atr": round(float(atr or 0), 4),
        "sl_m": row["sl_m"],
        "regime_multiplier": row["regime_multiplier"],
        "final_multiplier": round(hard_sl_final_multiplier(r), 4),
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
    offset: float = HARD_SL_STOP_LIMIT_OFFSET,
) -> float:
    """
    Stop-Limit execution price for buffer hard stop.
    LONG: limit = trigger − offset; SHORT: limit = trigger + offset.
    """
    sp = float(stop_price or 0)
    if sp <= 0 or side not in ("LONG", "SHORT"):
        return round_price(sp)
    off = max(float(offset or 0), 0.0)
    if side == "LONG":
        return round_price(sp - off)
    return round_price(sp + off)
