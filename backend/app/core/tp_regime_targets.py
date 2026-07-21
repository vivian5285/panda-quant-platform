"""TP slice ratios — fixed 30/30/40; only TP1+TP2 hung as limits.

TP3 remainder (40%) is managed by breathing-stop phase-2 — no TP3 limit order.
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import merge_regime_radar

FIXED_TP_QTY_PERCENT: tuple[int, int, int] = (30, 30, 40)
PLACEABLE_TP_LEVELS: frozenset[int] = frozenset({1, 2})

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


def resolve_tp_ratios_from_payload(payload: dict | None = None) -> list[float]:
    return pine_tp_ratios_frac()
