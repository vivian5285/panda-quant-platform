"""VPS-computed hard stop — regime × ATR breathing space (v6.9.103).

ETH / XAU share the same ATR multipliers so absolute stop distance tracks
volatility, not price level. Entry-% conversion was wrong for XAU (e.g. R3
5.56% @4000 ≈ 15×ATR — far wider than the ATR×3.3 spec).
"""

from __future__ import annotations

from typing import Any

from app.core.regime_utils import clamp_regime
from app.core.symbol_precision import round_price

# sl_m × regime_multiplier → final ATR multiplier
# Reference: ATR=16.65 → R1≈15U / R2≈31.5U / R3≈55U / R4≈100U
REGIME_HARD_SL: dict[int, dict[str, float]] = {
    1: {"sl_m": 0.9, "regime_multiplier": 1.0},   # 0.90×
    2: {"sl_m": 1.05, "regime_multiplier": 1.8},  # 1.89×
    3: {"sl_m": 1.10, "regime_multiplier": 3.0},  # 3.30×
    4: {"sl_m": 1.25, "regime_multiplier": 4.8},  # 6.00×
}

# Fallback when ATR missing: map final multiplier → approx entry% @ ETH 1800 / ATR 16.65
_REF_ENTRY = 1800.0
_REF_ATR = 16.65

# Stop-Limit: limit worse than trigger by this fraction of trigger
HARD_SL_LIMIT_PCT = 0.0015  # 0.15%
HARD_SL_STOP_LIMIT_OFFSET = 0.5

# Back-compat alias for callers/tests that still import pct table name
REGIME_HARD_SL_PCT: dict[int, float] = {
    r: (REGIME_HARD_SL[r]["sl_m"] * REGIME_HARD_SL[r]["regime_multiplier"] * _REF_ATR) / _REF_ENTRY
    for r in REGIME_HARD_SL
}


def hard_sl_final_multiplier(regime: int) -> float:
    """ATR multiplier for breathing-room distance."""
    r = clamp_regime(regime)
    row = REGIME_HARD_SL[r]
    return float(row["sl_m"]) * float(row["regime_multiplier"])


def hard_sl_pct(regime: int) -> float:
    """Approx entry-% equivalent at reference ETH/ATR (docs / legacy callers)."""
    return float(REGIME_HARD_SL_PCT[clamp_regime(regime)])


def compute_hard_sl_distance(
    entry: float,
    regime: int,
    *,
    atr: float = 0.0,
    relax_pct: float = 0.0,
) -> float:
    """
    Breathing space in price units: ATR × final_multiplier (+ optional relax).
    If ATR missing/zero, fall back to entry × reference-equivalent pct.
    """
    atr_f = max(float(atr or 0), 0.0)
    mult = hard_sl_final_multiplier(regime)
    if atr_f > 0:
        dist = atr_f * mult
    else:
        e = max(float(entry or 0), 0.0)
        if e <= 0:
            return 0.0
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
    VPS authoritative hard stop from ATR × regime multipliers.
    LONG: entry − distance; SHORT: entry + distance.
    TV tv_sl is reference-only (logged, never the hung price).
    """
    entry_f = float(entry or 0)
    atr_f = float(atr or 0)
    side_u = str(side or "").upper()
    r = clamp_regime(regime)
    mult = hard_sl_final_multiplier(r)
    dist = compute_hard_sl_distance(entry_f, r, atr=atr_f, relax_pct=relax_pct)
    meta: dict[str, Any] = {
        "source": "vps_computed",
        "method": "atr_regime",
        "regime": r,
        "atr": round(atr_f, 4),
        "sl_m": REGIME_HARD_SL[r]["sl_m"],
        "regime_multiplier": REGIME_HARD_SL[r]["regime_multiplier"],
        "final_multiplier": round(mult, 4),
        "hard_sl_pct": round(hard_sl_pct(r), 4),
        "hard_sl_pct_display": f"ATR×{mult:.2f}",
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
