"""TP slice ratios — v6.5.6 fixed 30/30/40 (all exchanges).

Leg1/Leg2 = placeable limit TPs (~30%/30%).
Leg3 (~40%) = NO limit order — VPS continuous-ladder radar manages exit.
Regime-based PINE_TP_QTY_PERCENT tables REMOVED.
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import merge_regime_radar

# Fixed split: qty1/qty2/qty3 ≈ 30/30/40
FIXED_TP_QTY_PERCENT: tuple[int, int, int] = (30, 30, 40)
# Only TP1 + TP2 are hung as reduceOnly LIMIT; TP3 is reference only
PLACEABLE_TP_LEVELS: frozenset[int] = frozenset({1, 2})

# Compat: all regimes share the same fixed ratios (regime key inert)
PINE_TP_QTY_PERCENT: dict[int, tuple[int, int, int]] = {
    1: FIXED_TP_QTY_PERCENT,
    2: FIXED_TP_QTY_PERCENT,
    3: FIXED_TP_QTY_PERCENT,
    4: FIXED_TP_QTY_PERCENT,
}

REGIME_MARGIN_PCT: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}


def clamp_regime(regime: int) -> int:
    r = int(regime or 3)
    return r if r in PINE_TP_QTY_PERCENT else 3


def pine_tp_ratios_frac(regime: int = 3) -> list[float]:
    p1, p2, p3 = FIXED_TP_QTY_PERCENT
    return [p1 / 100.0, p2 / 100.0, p3 / 100.0]


def format_tp_ratio_pct(regime: int = 3) -> str:
    p1, p2, p3 = FIXED_TP_QTY_PERCENT
    return f"{p1}/{p2}/{p3}"


def build_regime_settings() -> dict[int, dict[str, Any]]:
    base = {
        r: {"margin": 0.0, "ratios": pine_tp_ratios_frac(r)}
        for r in PINE_TP_QTY_PERCENT
    }
    return merge_regime_radar(base)


def enrich_tp_alert_detail(detail: dict | None, *, regime: int = 3) -> dict:
    out = dict(detail or {})
    out["regime"] = clamp_regime(regime)
    out["tp_ratios_pct"] = format_tp_ratio_pct()
    out["tp_ratios"] = pine_tp_ratios_frac()
    out["tp3_limit_placed"] = False
    out["tp_placeable_levels"] = sorted(PLACEABLE_TP_LEVELS)
    return out


def resolve_tp_ratios_from_payload(payload: dict | None) -> list[float]:
    """Prefer qty1/qty2/qty3 proportions from TV; else fixed 30/30/40."""
    data = payload or {}
    parts = []
    for k in ("qty1", "qty2", "qty3"):
        try:
            v = float(data.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        parts.append(max(v, 0.0))
    total = sum(parts)
    if total > 0:
        return [p / total for p in parts]
    return pine_tp_ratios_frac()
