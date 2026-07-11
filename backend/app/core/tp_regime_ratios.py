"""Pine v6.9.94 strategy.exit qty_percent — TP1/TP2/TP3 split per regime.

Source: gemini止损_动态加仓.txt (tp1_p / tp2_p / tp3_p, lines ~206-217).
All exchanges share the same ratios via regime_settings.
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import merge_regime_radar

# Pine qty_percent for strategy.exit("止盈1/2/3", qty_percent=...)
PINE_TP_QTY_PERCENT: dict[int, tuple[int, int, int]] = {
    1: (25, 35, 40),
    2: (20, 35, 45),
    3: (18, 32, 50),
    4: (5, 20, 75),
}

REGIME_MARGIN_PCT: dict[int, float] = {
    1: 0.15,
    2: 0.25,
    3: 0.35,
    4: 0.50,
}


def clamp_regime(regime: int) -> int:
    r = int(regime or 3)
    return r if r in PINE_TP_QTY_PERCENT else 3


def pine_tp_ratios_frac(regime: int) -> list[float]:
    """Fractional TP1/2/3 ratios for compute_tp_slices."""
    r = clamp_regime(regime)
    p1, p2, p3 = PINE_TP_QTY_PERCENT[r]
    return [p1 / 100.0, p2 / 100.0, p3 / 100.0]


def format_tp_ratio_pct(regime: int) -> str:
    """Human label for DingTalk / logs, e.g. 25/35/40."""
    r = clamp_regime(regime)
    p1, p2, p3 = PINE_TP_QTY_PERCENT[r]
    return f"{p1}/{p2}/{p3}"


def build_regime_settings() -> dict[int, dict[str, Any]]:
    """Margin + Pine TP ratios + radar overlay — single source for all exchanges."""
    base = {
        r: {"margin": REGIME_MARGIN_PCT[r], "ratios": pine_tp_ratios_frac(r)}
        for r in PINE_TP_QTY_PERCENT
    }
    return merge_regime_radar(base)


def enrich_tp_alert_detail(detail: dict | None, *, regime: int) -> dict:
    """Attach regime TP split metadata for trade alerts."""
    out = dict(detail or {})
    r = clamp_regime(regime)
    out["regime"] = r
    out["tp_ratios_pct"] = format_tp_ratio_pct(r)
    out["tp_ratios"] = pine_tp_ratios_frac(r)
    return out
